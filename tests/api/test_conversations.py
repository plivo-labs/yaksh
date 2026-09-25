import asyncio
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import insert, update
from sqlalchemy.ext.asyncio import create_async_engine

from tests.conftest import (
    PERSONA,
    TOKEN,
    FakeCaller,
    create_agent_id,
    create_persona,
    start,
    wait_for,
    wait_until,
)
from truman.config import Settings
from truman.db.models import Conversation
from truman.db.session import create_engine, create_sessionmaker
from truman.domain.conversations import ConversationStatus
from truman.domain.languages import Language
from truman.simulation import conversations
from truman.simulation.calls import STOP_IGNORED
from truman.worker.worker import FINALIZE_ATTEMPTS, Worker

FINAL = {"completed", "failed", "invalid", "cancelled"}


def unchecked(agent_id: str) -> dict[str, str]:
    """A start body for requests refused before the persona is read."""
    return {"agent_id": agent_id, "persona_id": str(uuid.uuid4()), "goal": "hello"}


async def stuck_worker(kind: str, settings: Settings, data_dir: Path) -> asyncio.subprocess.Process:
    return await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "tests.stuck_workers",
        kind,
        settings.database_url.encoded_string(),
        str(data_dir),
        cwd=Path(__file__).parents[2],
    )


async def wait_for_event(client: AsyncClient, conversation_id: str, kind: str) -> None:
    async def seen() -> bool:
        detail = (await client.get(f"/api/v1/conversations/{conversation_id}")).json()
        return any(event["kind"] == kind for event in detail["wire_events"])

    deadline = asyncio.get_running_loop().time() + 15
    while not await seen():
        assert asyncio.get_running_loop().time() < deadline
        await asyncio.sleep(0.05)


async def test_a_conversation_runs_to_completion_with_its_transcript(
    client: AsyncClient, worker: Worker, caller: FakeCaller
) -> None:
    agent_id = await create_agent_id(client)
    started = await start(client, agent_id)
    assert started["status"] == "queued" and started["agent_version"] == 1

    done = await wait_for(client, started["id"], {"completed"})

    assert done["end_reason"] == "agent_hangup" and done["validity"] == {"ok": True, "reasons": []}
    assert done["call_uuid"] == "call-42"
    assert [turn["role"] for turn in done["transcript"]] == ["agent", "caller"]
    assert done["transcript"][1]["provenance"] == "transmitted"
    assert done["caller_claim"] is None

    assert [event["kind"] for event in done["wire_events"]] == [
        "connect_started",
        "connected",
        "stop",
    ]
    assert done["recording_url"] is None
    assert (await client.get(f"/api/v1/conversations/{started['id']}/recording")).status_code == 404
    listed = (await client.get("/api/v1/conversations", params={"agent_id": agent_id})).json()
    assert [item["status"] for item in listed["items"]] == ["completed"]
    assert caller.calls == 1


async def test_the_caller_hanging_up_keeps_its_claim_apart_from_the_end_reason(
    client: AsyncClient, worker: Worker, caller: FakeCaller
) -> None:
    caller.mode = "caller_hangs_up"
    started = await start(client, await create_agent_id(client))

    done = await wait_for(client, started["id"], {"completed"})

    assert done["end_reason"] == "caller_hangup"
    assert done["caller_claim"] == {"success": True, "reason": "the room is booked"}


async def test_ending_a_queued_conversation_cancels_it_without_a_call(
    client: AsyncClient, caller: FakeCaller
) -> None:
    agent_id = await create_agent_id(client)
    started = await start(client, agent_id)

    ended = await client.post(f"/api/v1/conversations/{started['id']}/end")

    assert ended.status_code == 200
    assert ended.json()["status"] == "cancelled" and ended.json()["end_reason"] == "user_request"
    assert ended.json()["transcript"] == [] and ended.json()["validity"] is None
    assert caller.calls == 0


async def test_ending_a_running_conversation_hangs_up_and_is_idempotent(
    client: AsyncClient, worker: Worker, caller: FakeCaller
) -> None:
    caller.release.clear()
    agent_id = await create_agent_id(client)
    started = await start(client, agent_id)
    running = await wait_for(client, started["id"], {"running"})
    for _ in range(40):
        running = (await client.get(f"/api/v1/conversations/{started['id']}")).json()
        if running["transcript"]:
            break
        await asyncio.sleep(0.05)
    assert running["transcript"][0]["role"] == "agent"

    ending = await client.post(f"/api/v1/conversations/{started['id']}/end")
    assert ending.status_code == 202 and ending.json()["status"] == "ending"

    done = await wait_for(client, started["id"], FINAL)
    assert done["status"] == "completed" and done["end_reason"] == "user_request"
    again = await client.post(f"/api/v1/conversations/{started['id']}/end")
    assert again.status_code == 200 and again.json()["status"] == "completed"


async def test_starting_and_deleting_an_agent_cannot_both_succeed(client: AsyncClient) -> None:
    agent_id = await create_agent_id(client)
    persona = await create_persona(client)
    body = {"agent_id": agent_id, "persona_id": persona["id"], "goal": "race"}

    started, deleted = await asyncio.gather(
        client.post("/api/v1/conversations", json=body),
        client.delete(f"/api/v1/agents/{agent_id}"),
    )

    assert (started.status_code, deleted.status_code) in {(202, 409), (404, 204)}


async def test_two_workers_never_run_the_same_conversation_twice(
    client: AsyncClient, settings: Settings, caller: FakeCaller
) -> None:
    agent_id = await create_agent_id(client)
    ids = [(await start(client, agent_id))["id"] for _ in range(3)]
    engine = create_engine(settings.database_url.encoded_string())
    sessionmaker = create_sessionmaker(engine)
    workers = [Worker(sessionmaker, caller, settings, worker_id=f"w{n}") for n in range(2)]
    stop = asyncio.Event()
    tasks = [asyncio.create_task(worker.run(stop)) for worker in workers]

    for conversation_id in ids:
        await wait_for(client, conversation_id, {"completed"})
    stop.set()
    await asyncio.gather(*tasks)
    await engine.dispose()

    assert caller.calls == 3


async def test_an_exception_after_connecting_keeps_the_evidence(
    client: AsyncClient, worker: Worker, caller: FakeCaller
) -> None:
    caller.mode = "raise_after_connect"
    agent_id = await create_agent_id(client)
    started = await start(client, agent_id)

    done = await wait_for(client, started["id"], FINAL)

    assert done["status"] == "invalid" and done["end_reason"] == "error"
    assert done["failure_reason"] == "RuntimeError: tts exploded"
    assert done["validity"] == {"ok": False, "reasons": ["RuntimeError: tts exploded"]}
    assert "connected" in [event["kind"] for event in done["wire_events"]]
    assert done["transcript"][0]["text"] == "Hello, how can I help?"


async def test_a_caller_that_ignores_stop_is_cut_off_and_capacity_is_released(
    client: AsyncClient, worker: Worker, caller: FakeCaller
) -> None:
    caller.mode = "ignore_stop"
    agent_id = await create_agent_id(client)
    started = await start(client, agent_id)
    await wait_for_event(client, started["id"], "connected")

    await client.post(f"/api/v1/conversations/{started['id']}/end")
    done = await wait_for(client, started["id"], FINAL)

    assert done["status"] == "invalid" and done["failure_reason"] == STOP_IGNORED
    assert done["end_reason"] == "user_request"
    caller.mode = "normal"
    second = await start(client, agent_id)
    assert (await wait_for(client, second["id"], {"completed"}))["status"] == "completed"


async def test_an_expired_lease_is_marked_failed_while_a_live_one_is_not(
    client: AsyncClient, worker: Worker, caller: FakeCaller, settings: Settings
) -> None:
    caller.release.clear()
    agent_id = await create_agent_id(client)
    live = await start(client, agent_id)
    await wait_for(client, live["id"], {"running"})
    engine = create_async_engine(settings.database_url.encoded_string())
    async with engine.begin() as connection:
        orphan_id = await connection.scalar(
            insert(Conversation)
            .values(
                agent_id=uuid.UUID(agent_id),
                agent_version_id=uuid.UUID(live["agent_version_id"]),
                persona_id=uuid.UUID(live["persona_id"]),
                persona_version_id=uuid.UUID(live["persona_version_id"]),
                goal="orphaned by a dead worker",
                language=Language.EN,
                instructions="orphaned by a dead worker",
                nudge="Hello?",
                caller_number="+15550100000",
                max_duration_s=60,
                status=ConversationStatus.RUNNING,
                claimed_by="dead-worker",
                lease_expires_at=datetime.now(UTC) - timedelta(seconds=1),
            )
            .returning(Conversation.id)
        )
    await engine.dispose()

    reaped = await wait_for(client, str(orphan_id), FINAL)

    assert reaped["status"] == "failed" and reaped["end_reason"] == "lease_lost"
    assert "not retried" in reaped["failure_reason"]
    assert (await client.get(f"/api/v1/conversations/{live['id']}")).json()["status"] == "running"
    caller.release.set()
    await wait_for(client, live["id"], {"completed"})


async def test_a_conversation_waits_until_a_worker_picks_it_up(
    client: AsyncClient, settings: Settings, caller: FakeCaller
) -> None:
    agent_id = await create_agent_id(client)
    started = await start(client, agent_id)
    await asyncio.sleep(0.3)
    assert (await client.get(f"/api/v1/conversations/{started['id']}")).json()["status"] == "queued"

    engine = create_engine(settings.database_url.encoded_string())
    worker = Worker(create_sessionmaker(engine), caller, settings, worker_id="late")
    stop = asyncio.Event()
    task = asyncio.create_task(worker.run(stop))
    done = await wait_for(client, started["id"], {"completed"})
    stop.set()
    await task
    await engine.dispose()

    assert done["status"] == "completed"


async def test_a_refused_connection_is_failed_and_still_readable(
    client: AsyncClient, worker: Worker, caller: FakeCaller
) -> None:
    caller.mode = "refuse"
    agent_id = await create_agent_id(client)
    started = await start(client, agent_id)

    done = await wait_for(client, started["id"], FINAL)

    assert done["status"] == "failed" and done["failure_reason"] == "connection refused"
    assert done["transcript"] == [] and done["validity"] is None
    assert [event["kind"] for event in done["wire_events"]] == ["connect_started"]


async def test_a_conversation_gets_its_number_from_the_pool_and_outbound_agents_are_refused(
    client: AsyncClient,
) -> None:
    agent = await create_agent_id(client)
    outbound = await create_agent_id(client, direction="outbound")

    queued = await start(client, agent)
    chosen = await client.post(
        "/api/v1/conversations",
        json={**unchecked(agent), "caller_number": "+15550100000"},
    )
    refused = await client.post("/api/v1/conversations", json=unchecked(outbound))

    assert queued["status"] == "queued" and queued["caller_number"] is None
    assert chosen.status_code == 422
    assert chosen.json()["error"]["details"][0]["loc"][-1] == "caller_number"
    assert refused.status_code == 422 and "not supported yet" in refused.json()["error"]["message"]


async def test_conversations_cannot_start_while_phone_calls_are_off(
    settings: Settings, tmp_path: Path
) -> None:
    from truman.api import create_app

    app = create_app(settings.model_copy(update={"public_url": None}))
    headers = {"Authorization": f"Bearer {TOKEN}"}
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", headers=headers
    ) as client:
        agent = await create_agent_id(client)
        response = await client.post("/api/v1/conversations", json=unchecked(agent))
    await app.state.engine.dispose()

    assert response.status_code == 422
    assert "phone calls are off" in response.json()["error"]["message"]


async def test_a_conversation_keeps_the_agent_version_it_started_with(
    client: AsyncClient, worker: Worker
) -> None:
    agent_id = await create_agent_id(client)
    started = await start(client, agent_id)
    await wait_for(client, started["id"], {"completed"})

    patched = await client.patch(f"/api/v1/agents/{agent_id}", json={"brief": "changed"})
    assert patched.json()["current_version"] == 2

    assert (await client.get(f"/api/v1/conversations/{started['id']}")).json()["agent_version"] == 1


async def test_capacity_queues_extra_conversations(
    client: AsyncClient, settings: Settings, caller: FakeCaller
) -> None:
    caller.release.clear()
    agent_id = await create_agent_id(client)
    first, second = await start(client, agent_id), await start(client, agent_id)
    engine = create_engine(settings.database_url.encoded_string())
    limited = settings.model_copy(update={"max_active_conversations": 1})
    worker = Worker(create_sessionmaker(engine), caller, limited, worker_id="one-at-a-time")
    stop = asyncio.Event()
    task = asyncio.create_task(worker.run(stop))

    await wait_for(client, first["id"], {"running"})
    await asyncio.sleep(0.2)
    assert (await client.get(f"/api/v1/conversations/{second['id']}")).json()["status"] == "queued"
    caller.release.set()
    await wait_for(client, first["id"], {"completed"})
    await wait_for(client, second["id"], {"completed"})
    stop.set()
    await task
    await engine.dispose()


async def test_events_stream_turns_and_the_final_status(
    client: AsyncClient, worker: Worker, caller: FakeCaller, settings: Settings
) -> None:
    caller.release.clear()
    agent_id = await create_agent_id(client)
    started = await start(client, agent_id)
    engine = create_engine(settings.database_url.encoded_string())
    events = conversations.stream_events(
        create_sessionmaker(engine), uuid.UUID(started["id"]), interval_s=0.05
    )
    seen: list[tuple[str, Any]] = []

    async for event, data in events:
        seen.append((event, data))
        if event == "turn" and data["role"] == "agent":
            caller.release.set()
    await engine.dispose()

    assert [event for event, _ in seen if event == "turn"] == ["turn", "turn"]
    statuses = [data["status"] for event, data in seen if event == "status"]
    assert statuses == ["queued", "running", "completed"][-len(statuses) :]
    assert seen[-1] == ("status", {"status": "completed"})


async def test_the_events_route_serves_server_sent_events(
    client: AsyncClient, worker: Worker
) -> None:
    agent_id = await create_agent_id(client)
    started = await start(client, agent_id)
    await wait_for(client, started["id"], {"completed"})

    response = await client.get(f"/api/v1/conversations/{started['id']}/events")

    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: turn" in response.text and "event: status" in response.text
    assert '"status": "completed"' in response.text


async def test_worker_shutdown_stops_the_caller_and_keeps_the_evidence(
    client: AsyncClient, settings: Settings, caller: FakeCaller, tmp_path: Path
) -> None:
    caller.release.clear()
    caller.recording_path = tmp_path / "recording.wav"
    caller.recording_path.write_bytes(b"RIFF")
    agent_id = await create_agent_id(client)
    started = await start(client, agent_id)
    unhurried = settings.model_copy(update={"worker_lease_s": 30})
    engine = create_engine(settings.database_url.encoded_string())
    worker = Worker(create_sessionmaker(engine), caller, unhurried, worker_id="shutting-down")
    stop = asyncio.Event()
    task = asyncio.create_task(worker.run(stop))
    await wait_for_event(client, started["id"], "connected")

    stop.set()
    await task
    await engine.dispose()

    done = (await client.get(f"/api/v1/conversations/{started['id']}")).json()
    assert done["status"] == "failed" and done["end_reason"] == "worker_stopped"
    assert "worker stopped" in done["failure_reason"]
    assert "connected" in [event["kind"] for event in done["wire_events"]]
    assert done["transcript"][0]["role"] == "agent"
    assert done["recording_url"] is not None


async def test_shutdown_waits_while_result_writes_time_out_and_unwind_slowly(
    client: AsyncClient, settings: Settings, caller: FakeCaller, monkeypatch: pytest.MonkeyPatch
) -> None:
    from truman.simulation import conversations

    real_finalize = conversations.finalize
    attempts = {"n": 0}

    async def slow_to_cancel(*args: Any, **kwargs: Any) -> bool:
        attempts["n"] += 1
        if attempts["n"] < FINALIZE_ATTEMPTS:
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                await asyncio.sleep(settings.end_timeout_s * 0.8)
                raise
        return await real_finalize(*args, **kwargs)

    monkeypatch.setattr("truman.simulation.conversations.finalize", slow_to_cancel)
    monkeypatch.setattr("truman.worker.worker.FINALIZE_TIMEOUT_S", 0.2)
    monkeypatch.setattr("truman.worker.worker.FINALIZE_RETRY_S", 0.05)
    caller.release.clear()
    agent_id = await create_agent_id(client)
    started = await start(client, agent_id)
    unhurried = settings.model_copy(update={"worker_lease_s": 30})
    engine = create_engine(settings.database_url.encoded_string())
    worker = Worker(create_sessionmaker(engine), caller, unhurried, worker_id="shutting-down")
    stop = asyncio.Event()
    task = asyncio.create_task(worker.run(stop))
    await wait_for_event(client, started["id"], "connected")

    stop.set()
    await task
    await engine.dispose()

    done = (await client.get(f"/api/v1/conversations/{started['id']}")).json()
    assert done["status"] == "failed" and "worker stopped" in done["failure_reason"]
    assert done["transcript"][0]["role"] == "agent" and attempts["n"] == FINALIZE_ATTEMPTS


async def test_a_worker_that_cannot_renew_its_lease_stops_the_call(
    client: AsyncClient,
    worker: Worker,
    caller: FakeCaller,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    caller.release.clear()
    agent_id = await create_agent_id(client)
    started = await start(client, agent_id)
    await wait_until(lambda: caller.calls == 1)

    async def broken(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("database unreachable")

    monkeypatch.setattr("truman.simulation.conversations.renew_lease", broken)
    done = await wait_for(client, started["id"], FINAL, timeout=10)

    assert done["status"] == "failed" and done["end_reason"] == "lease_lost"
    assert caller.calls == 1


async def test_a_result_write_that_fails_past_the_lease_is_retried_and_kept(
    client: AsyncClient,
    worker: Worker,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from truman.simulation import conversations

    real_finalize = conversations.finalize
    failures = {"left": 1}

    async def slow_then_flaky(*args: Any, **kwargs: Any) -> bool:
        if failures["left"]:
            failures["left"] -= 1
            await asyncio.sleep(settings.worker_lease_s + 0.5)
            raise RuntimeError("connection reset")
        return await real_finalize(*args, **kwargs)

    monkeypatch.setattr("truman.simulation.conversations.finalize", slow_then_flaky)
    monkeypatch.setattr("truman.worker.worker.FINALIZE_RETRY_S", 0.05)
    agent_id = await create_agent_id(client)
    started = await start(client, agent_id)

    done = await wait_for(client, started["id"], FINAL, timeout=settings.worker_lease_s + 5)

    assert done["status"] == "completed" and failures["left"] == 0
    assert [turn["role"] for turn in done["transcript"]] == ["agent", "caller"]


async def test_a_renewal_that_hangs_stops_the_call_within_the_lease(
    client: AsyncClient,
    worker: Worker,
    caller: FakeCaller,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    caller.release.clear()
    agent_id = await create_agent_id(client)
    started = await start(client, agent_id)
    await wait_until(lambda: caller.calls == 1)

    async def hanging(*args: Any, **kwargs: Any) -> None:
        await asyncio.sleep(3600)

    monkeypatch.setattr("truman.simulation.conversations.renew_lease", hanging)
    done = await wait_for(client, started["id"], FINAL, timeout=10)

    assert done["status"] == "failed" and done["end_reason"] == "lease_lost"


async def test_an_expired_owner_can_neither_renew_nor_record(
    client: AsyncClient, settings: Settings
) -> None:
    agent_id = await create_agent_id(client)
    started = await start(client, agent_id)
    engine = create_async_engine(settings.database_url.encoded_string())
    async with engine.begin() as connection:
        await connection.execute(
            update(Conversation)
            .where(Conversation.id == uuid.UUID(started["id"]))
            .values(
                status=ConversationStatus.RUNNING,
                claimed_by="slow-worker",
                lease_expires_at=datetime.now(UTC) - timedelta(seconds=1),
            )
        )
    session = create_sessionmaker(engine)()
    conversation_id = uuid.UUID(started["id"])
    renewed = await conversations.renew_lease(session, conversation_id, "slow-worker", 30, None)
    outcome = conversations.CallOutcome(
        connected=True, end_reason=conversations.EndReason.AGENT_HANGUP
    )
    recorded = await conversations.finalize(
        session, conversation_id, "slow-worker", outcome, conversations.Transcript()
    )
    await session.close()
    await engine.dispose()

    assert renewed is None and recorded is False


async def test_a_caller_that_survives_cancellation_makes_the_worker_exit(
    client: AsyncClient, settings: Settings, caller: FakeCaller
) -> None:
    caller.mode = "immortal"
    agent_id = await create_agent_id(client)
    started = await start(client, agent_id)
    engine = create_engine(settings.database_url.encoded_string())
    worker = Worker(create_sessionmaker(engine), caller, settings, worker_id="doomed")
    stop = asyncio.Event()
    task = asyncio.create_task(worker.run(stop))
    await wait_for_event(client, started["id"], "connected")

    await client.post(f"/api/v1/conversations/{started['id']}/end")
    done = await wait_for(client, started["id"], FINAL, timeout=10)
    await asyncio.wait_for(task, timeout=10)
    await engine.dispose()

    assert done["status"] == "invalid" and done["failure_reason"] == STOP_IGNORED
    assert worker.fatal.is_set()


async def test_a_conversation_that_cannot_be_prepared_fails_without_stopping_the_worker(
    client: AsyncClient,
    worker: Worker,
    caller: FakeCaller,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_call_request = conversations.call_request
    broken = {"remaining": 1}

    async def flaky(*args: Any, **kwargs: Any) -> Any:
        if broken["remaining"]:
            broken["remaining"] -= 1
            raise RuntimeError("version row missing")
        return await real_call_request(*args, **kwargs)

    monkeypatch.setattr("truman.simulation.conversations.call_request", flaky)
    agent_id = await create_agent_id(client)
    first = await start(client, agent_id)
    failed = await wait_for(client, first["id"], FINAL)
    second = await start(client, agent_id)
    completed = await wait_for(client, second["id"], {"completed"})

    assert failed["status"] == "failed"
    assert failed["failure_reason"] == "RuntimeError: version row missing"
    assert completed["status"] == "completed" and caller.calls == 1


async def test_events_for_an_unknown_conversation_is_a_json_404(client: AsyncClient) -> None:
    response = await client.get(f"/api/v1/conversations/{uuid.uuid4()}/events")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_a_worker_with_an_uncancellable_caller_exits_nonzero(
    client: AsyncClient, settings: Settings, tmp_path: Path
) -> None:
    agent_id = await create_agent_id(client)
    started = await start(client, agent_id)
    process = await stuck_worker("immortal", settings, tmp_path)
    try:
        await wait_for_event(client, started["id"], "connected")
        await client.post(f"/api/v1/conversations/{started['id']}/end")
        exit_code = await asyncio.wait_for(process.wait(), timeout=20)
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()

    assert exit_code == 1
    done = (await client.get(f"/api/v1/conversations/{started['id']}")).json()
    assert done["status"] == "invalid" and done["failure_reason"] == STOP_IGNORED


async def test_a_call_whose_preparation_outlives_the_lease_is_not_started(
    client: AsyncClient,
    worker: Worker,
    caller: FakeCaller,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_call_request = conversations.call_request

    async def slow(*args: Any, **kwargs: Any) -> Any:
        await asyncio.sleep(settings.worker_lease_s + 0.5)
        return await real_call_request(*args, **kwargs)

    monkeypatch.setattr("truman.simulation.conversations.call_request", slow)
    agent_id = await create_agent_id(client)
    started = await start(client, agent_id)

    done = await wait_for(client, started["id"], FINAL, timeout=10)
    await asyncio.sleep(0.5)

    assert done["status"] == "failed" and done["end_reason"] == "lease_lost"
    assert caller.calls == 0


async def test_shutdown_interrupts_a_blocked_poll(
    settings: Settings, caller: FakeCaller, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def blocked(*args: Any, **kwargs: Any) -> int:
        await asyncio.sleep(3600)
        return 0

    monkeypatch.setattr("truman.simulation.conversations.reap_expired", blocked)
    engine = create_engine(settings.database_url.encoded_string())
    worker = Worker(create_sessionmaker(engine), caller, settings, worker_id="blocked")
    stop = asyncio.Event()
    task = asyncio.create_task(worker.run(stop))
    await asyncio.sleep(0.2)

    stop.set()
    await asyncio.wait_for(task, timeout=3)
    await engine.dispose()


async def test_a_stalled_result_write_does_not_hold_capacity(
    client: AsyncClient, settings: Settings, caller: FakeCaller, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def stalled(*args: Any, **kwargs: Any) -> bool:
        await asyncio.sleep(3600)
        return True

    monkeypatch.setattr("truman.simulation.conversations.finalize", stalled)
    monkeypatch.setattr("truman.worker.worker.FINALIZE_TIMEOUT_S", 0.2)
    monkeypatch.setattr("truman.worker.worker.FINALIZE_ATTEMPTS", 2)
    monkeypatch.setattr("truman.worker.worker.FINALIZE_RETRY_S", 0.05)
    agent_id = await create_agent_id(client)
    await start(client, agent_id)
    await start(client, agent_id)
    engine = create_engine(settings.database_url.encoded_string())
    limited = settings.model_copy(update={"max_active_conversations": 1})
    worker = Worker(create_sessionmaker(engine), caller, limited, worker_id="one-at-a-time")
    stop = asyncio.Event()
    task = asyncio.create_task(worker.run(stop))

    await wait_until(lambda: caller.calls == 2, timeout=10)
    stop.set()
    await asyncio.wait_for(task, timeout=10)
    await engine.dispose()

    assert not worker.fatal.is_set()


async def test_shutdown_with_an_uncancellable_result_write_still_exits(
    client: AsyncClient, settings: Settings, tmp_path: Path
) -> None:
    agent_id = await create_agent_id(client)
    started = await start(client, agent_id)
    process = await stuck_worker("stuck_write", settings, tmp_path)
    try:
        await wait_for_event(client, started["id"], "connected")
        await asyncio.sleep(0.5)
        process.terminate()
        exit_code = await asyncio.wait_for(process.wait(), timeout=20)
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()

    assert exit_code == 1


async def test_shutdown_with_stuck_engine_disposal_still_exits(
    client: AsyncClient, settings: Settings, tmp_path: Path
) -> None:
    process = await stuck_worker("stuck_disposal", settings, tmp_path)
    try:
        await asyncio.sleep(1.5)
        process.terminate()
        exit_code = await asyncio.wait_for(process.wait(), timeout=20)
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()

    assert exit_code == 1


async def test_a_conversation_freezes_its_persona_goal_and_prompt(
    client: AsyncClient, settings: Settings
) -> None:
    agent_id = await create_agent_id(client)
    persona = await create_persona(client, language="hinglish")
    started = await start(client, agent_id, persona_id=persona["id"], goal="Book a table for two.")
    await client.patch(
        f"/api/v1/personas/{persona['id']}",
        json={"prompt": "Someone else.", "voice": {**persona["voice"], "speed": 1.2}},
    )

    detail = (await client.get(f"/api/v1/conversations/{started['id']}")).json()
    engine = create_engine(settings.database_url.encoded_string())
    async with create_sessionmaker(engine)() as session:
        row = await conversations.get_conversation(session, uuid.UUID(started["id"]))
        request = await conversations.call_request(session, settings, row, "+15550100000")
    await engine.dispose()

    assert (detail["persona_name"], detail["persona_version"]) == (persona["name"], 1)
    assert (detail["goal"], detail["language"]) == ("Book a table for two.", "hinglish")
    assert (
        PERSONA["prompt"] in detail["instructions"] and "Someone else." not in request.instructions
    )
    assert "Book a table for two." in request.instructions and "Hinglish" in request.instructions
    assert request.voice.speed == 1.0 and request.nudge == "हेलो? आप वहाँ हैं?"


async def test_a_conversation_needs_a_live_persona(client: AsyncClient) -> None:
    agent_id = await create_agent_id(client)
    persona = await create_persona(client)
    await client.delete(f"/api/v1/personas/{persona['id']}")

    for persona_id in (persona["id"], str(uuid.uuid4())):
        body = {"agent_id": agent_id, "persona_id": persona_id, "goal": "hello"}
        response = await client.post("/api/v1/conversations", json=body)
        assert response.status_code == 404 and "persona" in response.json()["error"]["message"]


async def test_a_queued_conversation_still_runs_after_its_persona_is_deleted(
    client: AsyncClient, settings: Settings, caller: FakeCaller
) -> None:
    agent_id = await create_agent_id(client)
    started = await start(client, agent_id)
    await client.delete(f"/api/v1/personas/{started['persona_id']}")

    engine = create_engine(settings.database_url.encoded_string())
    worker = Worker(create_sessionmaker(engine), caller, settings, worker_id="late-worker")
    stop = asyncio.Event()
    task = asyncio.create_task(worker.run(stop))
    try:
        done = await wait_for(client, started["id"], FINAL)
    finally:
        stop.set()
        await task
        await engine.dispose()

    assert done["status"] == "completed"
