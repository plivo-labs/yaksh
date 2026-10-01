import asyncio
import uuid
from datetime import timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, update

from tests.conftest import (
    FINAL,
    Db,
    FakeCaller,
    checked_counts,
    claim,
    create_agent_id,
    expire_leases,
    new_run,
    reap,
    run_conversations,
    start,
    wait_for,
    wait_for_lock_waiters,
)
from truman.db.models import Conversation, PhoneNumber, Run
from truman.domain.conversations import ConversationStatus, EndReason
from truman.simulation import conversations, numbers
from truman.worker.worker import Worker


async def queue_of(client: AsyncClient, run: dict[str, Any]) -> list[str]:
    return [c["id"] for c in await run_conversations(client, run["id"])]


async def reason(client: AsyncClient, run: dict[str, Any]) -> str | None:
    return (await client.get(f"/api/v1/runs/{run['id']}")).json()["waiting_reason"]


async def test_workers_claiming_at_the_same_moment_keep_a_runs_max_parallel(
    client: AsyncClient, db: Db
) -> None:
    run = await new_run(client, scenarios=2, repeats=3, max_parallel=2)

    claimed = await asyncio.gather(*(claim(db, worker_id=f"w{n}") for n in range(6)))

    assert sorted(c for c in claimed if c is not None) == sorted((await queue_of(client, run))[:2])
    assert await reason(client, run) == "max_parallel"


async def test_a_run_waits_its_delay_between_calls_while_other_work_starts(
    client: AsyncClient, db: Db
) -> None:
    run = await new_run(client, repeats=2, start_interval_s=60)
    first, second = await queue_of(client, run)

    claimed_first = await claim(db)
    held_back = await claim(db)
    waiting = await reason(client, run)
    other = await new_run(client)
    claimed_other = await claim(db)
    async with db.begin() as session:
        await session.execute(
            update(Conversation)
            .where(Conversation.id == uuid.UUID(first))
            .values(started_at=func.now() - timedelta(seconds=61))
        )
    claimed_second = await claim(db)

    assert (claimed_first, held_back, waiting) == (first, None, "start_interval")
    assert claimed_other == (await queue_of(client, other))[0]
    assert claimed_second == second


async def test_a_claim_that_waited_for_its_run_starts_the_delay_when_it_claims(
    client: AsyncClient, db: Db
) -> None:
    run = await new_run(client, repeats=2, start_interval_s=1)

    async with db() as holder:
        await holder.get_one(Run, uuid.UUID(run["id"]), with_for_update=True)
        first = asyncio.create_task(claim(db))
        await wait_for_lock_waiters(db, 1)
        await asyncio.sleep(1.5)
        await holder.rollback()
    claimed = await first

    assert claimed == (await queue_of(client, run))[0]
    assert await claim(db) is None, "the delay runs from the claim, not from its wait"


async def test_single_calls_start_first_then_runs_in_the_order_they_were_started(
    client: AsyncClient, db: Db
) -> None:
    earlier = await new_run(client)
    later = await new_run(client)
    single = await start(client, await create_agent_id(client, name="Single calls"))
    waiting = await reason(client, earlier)

    order = [await claim(db) for _ in range(4)]

    assert waiting == "worker_or_number"
    assert order == [
        single["id"],
        *await queue_of(client, earlier),
        *await queue_of(client, later),
        None,
    ]


async def test_a_full_run_does_not_hold_up_a_later_run(client: AsyncClient, db: Db) -> None:
    full = await new_run(client, repeats=2, max_parallel=1)
    later = await new_run(client)

    order = [await claim(db) for _ in range(3)]

    assert order == [(await queue_of(client, full))[0], *await queue_of(client, later), None]
    assert await reason(client, full) == "max_parallel"
    assert await reason(client, later) is None


async def test_cancelling_a_run_cancels_its_queue_and_ends_its_live_call(
    client: AsyncClient, caller: FakeCaller, worker: Worker, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = conversations.finalize
    recording = asyncio.Event()

    async def held(*args: Any, **kwargs: Any) -> bool:
        await recording.wait()
        return await record(*args, **kwargs)

    monkeypatch.setattr("truman.simulation.conversations.finalize", held)
    caller.release.clear()
    run = await new_run(client, repeats=3, max_parallel=1)
    live = (await queue_of(client, run))[0]
    await wait_for(client, live, {"running"})
    before = await checked_counts(client, run["id"])

    cancelled = await client.post(f"/api/v1/runs/{run['id']}/cancel")

    assert (before["waiting"], before["in_progress"]) == (2, 1)
    assert cancelled.status_code == 202 and cancelled.json()["status"] == "cancelling"
    rest = (await run_conversations(client, run["id"]))[1:]
    assert [(c["status"], c["end_reason"]) for c in rest] == [("cancelled", "user_request")] * 2
    assert all(c["ended_at"] is not None for c in rest)
    ending = await checked_counts(client, run["id"])
    assert (ending["in_progress"], ending["cancelled"]) == (1, 2)
    recording.set()
    assert (await wait_for(client, live, FINAL))["end_reason"] == "user_request"
    after = (await client.get(f"/api/v1/runs/{run['id']}")).json()
    assert (after["status"], after["counts"]["cancelled"]) == ("cancelled", 3)
    again = await client.post(f"/api/v1/runs/{run['id']}/cancel")
    assert again.status_code == 200 and again.json()["cancelled_at"] == after["cancelled_at"]
    assert (await checked_counts(client, run["id"]))["cancelled"] == 3


async def test_a_cancel_that_meets_a_requeue_cancels_the_returned_conversation(
    client: AsyncClient, db: Db
) -> None:
    run = await new_run(client)
    returned = await claim(db)
    assert returned is not None

    async def requeue() -> bool:
        async with db() as session:
            return await conversations.requeue(session, uuid.UUID(returned), "w1")

    async with db() as holder:
        await holder.get_one(Conversation, uuid.UUID(returned), with_for_update=True)
        requeueing = asyncio.create_task(requeue())
        await wait_for_lock_waiters(db, 1)
        cancelling = asyncio.create_task(client.post(f"/api/v1/runs/{run['id']}/cancel"))
        await wait_for_lock_waiters(db, 2)
        await holder.rollback()
    requeued, cancelled = await asyncio.wait_for(asyncio.gather(requeueing, cancelling), 10)

    after = (await client.get(f"/api/v1/conversations/{returned}")).json()
    assert requeued is True and cancelled.json()["status"] == "cancelled"
    assert (after["status"], after["end_reason"]) == ("cancelled", "user_request")


async def test_cancelling_a_finished_run_changes_nothing(client: AsyncClient, db: Db) -> None:
    run = await new_run(client)
    async with db.begin() as session:
        await session.execute(
            update(Conversation)
            .where(Conversation.run_id == uuid.UUID(run["id"]))
            .values(
                status=ConversationStatus.COMPLETED,
                end_reason=EndReason.AGENT_HANGUP,
                ended_at=func.now(),
            )
        )

    response = await client.post(f"/api/v1/runs/{run['id']}/cancel")
    missing = await client.post(f"/api/v1/runs/{uuid.uuid4()}/cancel")

    assert response.status_code == 200
    assert (response.json()["status"], response.json()["cancelled_at"]) == ("done", None)
    assert missing.status_code == 404


@pytest.mark.parametrize("claim_first", [True, False])
async def test_a_claim_and_a_cancel_at_the_same_moment_leave_nothing_queued(
    client: AsyncClient, db: Db, claim_first: bool
) -> None:
    run = await new_run(client, repeats=2)

    async with db() as holder:
        await holder.get_one(Run, uuid.UUID(run["id"]), with_for_update=True)
        if claim_first:
            claiming = asyncio.create_task(claim(db))
            await wait_for_lock_waiters(db, 1)
            cancelling = asyncio.create_task(client.post(f"/api/v1/runs/{run['id']}/cancel"))
        else:
            cancelling = asyncio.create_task(client.post(f"/api/v1/runs/{run['id']}/cancel"))
            await wait_for_lock_waiters(db, 1)
            claiming = asyncio.create_task(claim(db))
        await wait_for_lock_waiters(db, 2)
        await holder.rollback()
    claimed = await asyncio.wait_for(claiming, 10)
    cancelled = (await asyncio.wait_for(cancelling, 10)).json()

    statuses = [c["status"] for c in await run_conversations(client, run["id"])]
    if claim_first:
        assert claimed is not None and statuses == ["ending", "cancelled"]
        assert cancelled["status"] == "cancelling"
    else:
        assert claimed is None and statuses == ["cancelled", "cancelled"]
        assert cancelled["status"] == "cancelled"


async def test_a_reaper_that_waited_for_its_run_still_rests_the_number(
    client: AsyncClient, db: Db
) -> None:
    run = await new_run(client)
    lost = await claim(db)
    assert lost is not None
    async with db() as session:
        number = await numbers.lease_number(session, uuid.UUID(lost))
    await expire_leases(db, Conversation.id == uuid.UUID(lost))

    async with db() as holder:
        await holder.get_one(Run, uuid.UUID(run["id"]), with_for_update=True)
        reaping = asyncio.create_task(reap(db, rest_s=1))
        await wait_for_lock_waiters(db, 1)
        await asyncio.sleep(1.5)
        await holder.rollback()
    reaped = await reaping
    async with db() as session:
        resting = await session.scalar(
            select(PhoneNumber.available_after > func.now()).where(PhoneNumber.number == number)
        )

    assert reaped == 1 and resting, "the rest runs from the release, not from the lock wait"


@pytest.mark.parametrize("reap_first", [True, False])
async def test_the_reaper_and_a_cancel_of_the_same_run_take_turns(
    client: AsyncClient, db: Db, reap_first: bool
) -> None:
    run = await new_run(client, repeats=2, max_retries=0)
    assert None not in [await claim(db), await claim(db)]
    await expire_leases(db, Conversation.run_id == uuid.UUID(run["id"]))

    async with db() as holder:
        await holder.get_one(Run, uuid.UUID(run["id"]), with_for_update=True)
        if reap_first:
            reaping = asyncio.create_task(reap(db))
            await wait_for_lock_waiters(db, 1)
            cancelling = asyncio.create_task(client.post(f"/api/v1/runs/{run['id']}/cancel"))
        else:
            cancelling = asyncio.create_task(client.post(f"/api/v1/runs/{run['id']}/cancel"))
            await wait_for_lock_waiters(db, 1)
            reaping = asyncio.create_task(reap(db))
        await wait_for_lock_waiters(db, 2)
        await holder.rollback()
    reaped = await asyncio.wait_for(reaping, 10)
    await asyncio.wait_for(cancelling, 10)

    after = (await client.get(f"/api/v1/runs/{run['id']}")).json()
    ended = await run_conversations(client, run["id"])
    assert reaped == 2
    assert {(c["status"], c["end_reason"]) for c in ended} == {("failed", "lease_lost")}
    assert after["status"] == ("done" if reap_first else "cancelled")
