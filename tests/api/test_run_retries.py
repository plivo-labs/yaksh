import asyncio
import uuid
from datetime import timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, update

from tests.conftest import (
    FakeCaller,
    claim,
    new_run,
    reap,
    run_conversations,
    wait_for_lock_waiters,
    wait_for_run,
)
from truman.config import Settings
from truman.db.models import Conversation, Run
from truman.db.session import create_engine, create_sessionmaker
from truman.domain.conversations import CallOutcome, EndReason, Transcript
from truman.simulation import conversations
from truman.worker.worker import Worker

INPUTS = (
    "agent_id",
    "agent_version_id",
    "channel",
    "direction",
    "persona_id",
    "persona_version_id",
    "scenario_id",
    "scenario_version_id",
    "language",
    "instructions",
    "nudge",
    "max_duration_s",
    "run_id",
    "repeat",
)
RESULTS = ("caller_number", "call_uuid", "dial_deadline_at", "talk_ms", "transcript", "ended_at")


async def expire_leases(settings: Settings, run: dict[str, Any]) -> None:
    engine = create_engine(settings.database_url.encoded_string())
    async with engine.begin() as connection:
        await connection.execute(
            update(Conversation)
            .where(Conversation.run_id == uuid.UUID(run["id"]))
            .values(lease_expires_at=func.now() - timedelta(seconds=1))
        )
    await engine.dispose()


async def fail(settings: Settings, conversation_id: str) -> bool:
    """Finalize a conversation claimed by w1 as a call that failed on Truman's side."""
    engine = create_engine(settings.database_url.encoded_string())
    async with create_sessionmaker(engine)() as session:
        recorded = await conversations.finalize(
            session,
            uuid.UUID(conversation_id),
            "w1",
            CallOutcome(connected=False, end_reason=EndReason.ERROR, caller_error="boom"),
            Transcript(),
            0,
        )
    await engine.dispose()
    return recorded


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


@pytest.mark.parametrize(
    ("mode", "status", "end_reason"),
    [("normal", "completed", "agent_hangup"), ("no_answer", "failed", "no_answer")],
)
async def test_only_the_error_group_is_tried_again(
    client: AsyncClient,
    caller: FakeCaller,
    worker: Worker,
    mode: str,
    status: str,
    end_reason: str,
) -> None:
    caller.mode = mode
    run = await new_run(client, max_retries=2)

    done = await wait_for_run(client, run["id"], "done")

    only = await run_conversations(client, run["id"])
    assert [(c["status"], c["end_reason"]) for c in only] == [(status, end_reason)]
    assert done["retries"] == 0


async def test_a_lost_lease_is_tried_again_with_the_inputs_and_nothing_else(
    client: AsyncClient, settings: Settings
) -> None:
    run = await new_run(client)
    lost = await claim(settings)
    assert lost is not None
    engine = create_engine(settings.database_url.encoded_string())
    async with engine.begin() as connection:
        await connection.execute(
            update(Conversation)
            .where(Conversation.id == uuid.UUID(lost))
            .values(
                caller_number="+15550100000",
                call_uuid="call-1",
                dial_deadline_at=func.now(),
                talk_ms=1200,
                transcript={"turns": [], "wire_events": []},
                lease_expires_at=func.now() - timedelta(seconds=1),
            )
        )

    reaped = await reap(settings)

    async with create_sessionmaker(engine)() as session:
        original, retry = await session.scalars(
            select(Conversation)
            .where(Conversation.run_id == uuid.UUID(run["id"]))
            .order_by(Conversation.attempt)
        )
    await engine.dispose()
    assert reaped == 1
    assert (original.status, original.end_reason) == ("failed", "lease_lost")
    assert {name: getattr(retry, name) for name in INPUTS} == {
        name: getattr(original, name) for name in INPUTS
    }
    assert (retry.status, retry.attempt, retry.retry_of) == ("queued", 2, original.id)
    assert [getattr(retry, name) for name in RESULTS] == [None] * len(RESULTS)


async def test_reapers_and_a_late_result_write_make_one_retry(
    client: AsyncClient, settings: Settings
) -> None:
    run = await new_run(client)
    lost = await claim(settings)
    assert lost is not None
    await expire_leases(settings, run)

    first, second, recorded = await asyncio.gather(
        reap(settings), reap(settings), fail(settings, lost)
    )

    attempts = await run_conversations(client, run["id"])
    assert [c["attempt"] for c in attempts] == [1, 2]
    assert sorted([first, second]) == [0, 1] and recorded is False


async def test_a_result_write_that_outlived_the_lease_while_waiting_is_refused(
    client: AsyncClient, settings: Settings
) -> None:
    run = await new_run(client)
    late = await claim(settings)
    assert late is not None
    engine = create_engine(settings.database_url.encoded_string())
    async with engine.begin() as connection:
        await connection.execute(
            update(Conversation)
            .where(Conversation.id == uuid.UUID(late))
            .values(lease_expires_at=func.now() + timedelta(seconds=1))
        )

    async with create_sessionmaker(engine)() as holder:
        await holder.get_one(Run, uuid.UUID(run["id"]), with_for_update=True)
        writing = asyncio.create_task(fail(settings, late))
        await wait_for_lock_waiters(settings, 1)
        await asyncio.sleep(1.5)
        await holder.rollback()
    recorded = await writing
    await engine.dispose()
    reaped = await reap(settings)

    attempts = await run_conversations(client, run["id"])
    assert recorded is False and reaped == 1
    assert [(c["attempt"], c["end_reason"]) for c in attempts] == [(1, "lease_lost"), (2, None)]


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
    client: AsyncClient, settings: Settings, path: str, cancel_first: bool
) -> None:
    run = await new_run(client)
    conversation = await claim(settings)
    assert conversation is not None
    if path == "reaper":
        await expire_leases(settings, run)
    engine = create_engine(settings.database_url.encoded_string())

    def ending() -> asyncio.Task[Any]:
        if path == "reaper":
            return asyncio.create_task(reap(settings))
        assert conversation is not None
        return asyncio.create_task(fail(settings, conversation))

    async with create_sessionmaker(engine)() as holder:
        await holder.get_one(Run, uuid.UUID(run["id"]), with_for_update=True)
        if cancel_first:
            cancelling = asyncio.create_task(client.post(f"/api/v1/runs/{run['id']}/cancel"))
            await wait_for_lock_waiters(settings, 1)
            ended = ending()
        else:
            ended = ending()
            await wait_for_lock_waiters(settings, 1)
            cancelling = asyncio.create_task(client.post(f"/api/v1/runs/{run['id']}/cancel"))
        await wait_for_lock_waiters(settings, 2)
        await holder.rollback()
    await asyncio.wait_for(asyncio.gather(ended, cancelling), 10)
    await engine.dispose()

    attempts = await run_conversations(client, run["id"])
    assert "queued" not in {c["status"] for c in attempts}
    assert len(attempts) == (1 if cancel_first else 2)
    after = (await client.get(f"/api/v1/runs/{run['id']}")).json()
    assert after["status"] == "cancelled"
