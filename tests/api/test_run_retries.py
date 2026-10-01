import asyncio
import uuid
from datetime import timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, update

from tests.conftest import (
    TRUMAN_FAILED,
    Db,
    FakeCaller,
    checked_counts,
    claim,
    expire_leases,
    finish,
    new_run,
    reap,
    run_conversations,
    wait_for_lock_waiters,
    wait_for_run,
)
from truman.config import Settings
from truman.db.models import Conversation, Run, Scenario
from truman.worker.worker import Worker

ATTEMPT = {"id", "status", "attempt", "retry_of", "created_at"}
"""The columns that name an attempt."""
RESULTS = {
    "caller_number",
    "call_uuid",
    "dial_deadline_at",
    "agent_caller_id",
    "end_reason",
    "failure_reason",
    "started_at",
    "ended_at",
    "talk_ms",
    "recording_path",
    "transcript",
    "caller_claim",
    "claimed_by",
    "lease_expires_at",
}
"""What an attempt got while it ran; its retry starts with none of it."""


async def test_an_error_is_tried_again_up_to_the_runs_retries(
    client: AsyncClient, caller: FakeCaller, worker: Worker
) -> None:
    caller.mode = "refuse"
    run = await new_run(client, max_retries=2)

    done = await wait_for_run(client, run["id"], "done")

    attempts = await run_conversations(client, run["id"])
    assert [(c["attempt"], c["status"], c["end_reason"]) for c in attempts] == [
        (attempt, "failed", "error") for attempt in (1, 2, 3)
    ]
    assert [c["retry_of"] for c in attempts] == [None, attempts[0]["id"], attempts[1]["id"]]
    assert (done["counts"]["error"], sum(done["counts"].values()), done["retries"]) == (1, 1, 2)
    first = (await client.get(f"/api/v1/conversations/{attempts[0]['id']}")).json()
    assert first["retried_as"] == attempts[1]["id"] and caller.calls == 3
    assert (await checked_counts(client, run["id"]))["error"] == 1


@pytest.mark.parametrize(
    ("mode", "status", "end_reason", "group"),
    [
        ("normal", "completed", "agent_hangup", "completed"),
        ("no_answer", "failed", "no_answer", "did_not_connect"),
    ],
)
async def test_only_the_error_group_is_tried_again(
    client: AsyncClient,
    caller: FakeCaller,
    worker: Worker,
    mode: str,
    status: str,
    end_reason: str,
    group: str,
) -> None:
    caller.mode = mode
    run = await new_run(client, max_retries=2)

    done = await wait_for_run(client, run["id"], "done")

    only = await run_conversations(client, run["id"])
    assert [(c["status"], c["end_reason"]) for c in only] == [(status, end_reason)]
    assert done["retries"] == 0
    assert (await checked_counts(client, run["id"]))[group] == 1


async def test_a_lost_lease_is_tried_again_with_the_inputs_and_nothing_else(
    client: AsyncClient, db: Db
) -> None:
    run = await new_run(client)
    lost = await claim(db)
    assert lost is not None
    async with db.begin() as session:
        await session.execute(
            update(Conversation)
            .where(Conversation.id == uuid.UUID(lost))
            .values(
                caller_number="+15550100000",
                call_uuid="call-1",
                dial_deadline_at=func.now(),
                agent_caller_id="+15550100001",
                talk_ms=1200,
                recording_path="recording.wav",
                transcript={"turns": [], "wire_events": []},
                caller_claim={"success": True, "reason": "booked"},
                lease_expires_at=func.now() - timedelta(seconds=1),
            )
        )

    reaped = await reap(db)

    async with db() as session:
        original, retry = await session.scalars(
            select(Conversation)
            .where(Conversation.run_id == uuid.UUID(run["id"]))
            .order_by(Conversation.attempt)
        )
    copied = set(Conversation.__table__.columns.keys()) - ATTEMPT - RESULTS
    assert reaped == 1
    assert (original.status, original.end_reason) == ("failed", "lease_lost")
    assert {name: getattr(retry, name) for name in copied} == {
        name: getattr(original, name) for name in copied
    }
    assert (retry.status, retry.attempt, retry.retry_of) == ("queued", 2, original.id)
    assert {name: getattr(retry, name) for name in RESULTS} == dict.fromkeys(RESULTS)


@pytest.mark.parametrize("write_first", [True, False])
async def test_a_result_write_that_outlived_its_lease_and_the_reapers_make_one_retry(
    client: AsyncClient, db: Db, write_first: bool
) -> None:
    run = await new_run(client)
    late = await claim(db)
    assert late is not None
    async with db.begin() as session:
        await session.execute(
            update(Conversation)
            .where(Conversation.id == uuid.UUID(late))
            .values(lease_expires_at=func.now() + timedelta(seconds=1))
        )

    async with db() as holder:
        await holder.get_one(Run, uuid.UUID(run["id"]), with_for_update=True)
        if write_first:
            writing = asyncio.create_task(finish(db, late, TRUMAN_FAILED))
            await wait_for_lock_waiters(db, 1)
            await asyncio.sleep(1.5)
            reaping = [asyncio.create_task(reap(db)) for _ in range(2)]
        else:
            await asyncio.sleep(1.5)
            reaping = [asyncio.create_task(reap(db)) for _ in range(2)]
            await wait_for_lock_waiters(db, 2)
            writing = asyncio.create_task(finish(db, late, TRUMAN_FAILED))
        await wait_for_lock_waiters(db, 3)
        await holder.rollback()
    recorded = await asyncio.wait_for(writing, 10)
    reaped = sorted(await asyncio.wait_for(asyncio.gather(*reaping), 10))

    attempts = await run_conversations(client, run["id"])
    assert recorded is False and reaped == [0, 1], "the lease ran out while the run was locked"
    assert [(c["attempt"], c["end_reason"]) for c in attempts] == [(1, "lease_lost"), (2, None)]


async def test_a_retry_and_an_edit_of_its_scenario_at_the_same_moment_both_go_through(
    client: AsyncClient, db: Db
) -> None:
    run = await new_run(client)
    [queued] = await run_conversations(client, run["id"])
    assert await claim(db) == queued["id"]

    async with db() as holder:
        await holder.get_one(Scenario, uuid.UUID(queued["scenario_id"]), with_for_update=True)
        editing = asyncio.create_task(
            client.patch(
                f"/api/v1/scenarios/{queued['scenario_id']}",
                json={"goal": "Cancel the cleaning.", "persona_id": queued["persona_id"]},
            )
        )
        await wait_for_lock_waiters(db, 1)
        recording = asyncio.create_task(finish(db, queued["id"], TRUMAN_FAILED))
        await wait_for_lock_waiters(db, 2)
        await holder.rollback()
    edited, recorded = await asyncio.wait_for(asyncio.gather(editing, recording), 10)

    attempts = await run_conversations(client, run["id"])
    assert edited.status_code == 200 and recorded is True, "the retry key-shares in lock order"
    assert [(c["attempt"], c["status"]) for c in attempts] == [(1, "failed"), (2, "queued")]


async def test_the_reaper_makes_the_retry_when_every_result_write_fails(
    client: AsyncClient, settings: Settings, worker: Worker, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken(*args: Any, **kwargs: Any) -> bool:
        raise RuntimeError("connection reset")

    monkeypatch.setattr("truman.simulation.conversations.finalize", broken)
    monkeypatch.setattr("truman.worker.worker.FINALIZE_RETRY_S", 0.05)
    run = await new_run(client)

    await wait_for_run(client, run["id"], "done", timeout=settings.worker_lease_s * 3 + 5)

    attempts = await run_conversations(client, run["id"])
    assert [(c["attempt"], c["end_reason"]) for c in attempts] == [
        (1, "lease_lost"),
        (2, "lease_lost"),
    ]


@pytest.mark.parametrize("path", ["finalize", "reaper"])
@pytest.mark.parametrize("cancel_first", [True, False])
async def test_a_retry_and_a_cancel_at_the_same_moment_leave_nothing_queued(
    client: AsyncClient, db: Db, path: str, cancel_first: bool
) -> None:
    run = await new_run(client)
    conversation = await claim(db)
    assert conversation is not None
    if path == "reaper":
        await expire_leases(db, Conversation.run_id == uuid.UUID(run["id"]))

    def ending() -> asyncio.Task[Any]:
        if path == "reaper":
            return asyncio.create_task(reap(db))
        assert conversation is not None
        return asyncio.create_task(finish(db, conversation, TRUMAN_FAILED))

    async with db() as holder:
        await holder.get_one(Run, uuid.UUID(run["id"]), with_for_update=True)
        if cancel_first:
            cancelling = asyncio.create_task(client.post(f"/api/v1/runs/{run['id']}/cancel"))
            await wait_for_lock_waiters(db, 1)
            ended = ending()
        else:
            ended = ending()
            await wait_for_lock_waiters(db, 1)
            cancelling = asyncio.create_task(client.post(f"/api/v1/runs/{run['id']}/cancel"))
        await wait_for_lock_waiters(db, 2)
        await holder.rollback()
    await asyncio.wait_for(asyncio.gather(ended, cancelling), 10)

    attempts = await run_conversations(client, run["id"])
    assert "queued" not in {c["status"] for c in attempts}
    assert len(attempts) == (1 if cancel_first else 2)
    after = (await client.get(f"/api/v1/runs/{run['id']}")).json()
    assert after["status"] == "cancelled"
