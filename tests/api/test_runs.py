import asyncio
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, update

from tests.conftest import (
    TOKEN,
    Db,
    FakeCaller,
    claim,
    create_agent_id,
    create_persona,
    create_scenario,
    finish,
    make_settings,
    run_conversations,
    start,
    start_run,
    wait_for_lock_waiters,
    wait_for_run,
)
from truman.api import create_app
from truman.config import Settings
from truman.db.models import Conversation, Persona, Scenario
from truman.domain.conversations import CallOutcome, ConversationStatus, EndReason
from truman.worker.worker import Worker

NO_OUTCOMES = dict.fromkeys(
    ("waiting", "in_progress", "completed", "did_not_connect", "error", "cancelled"), 0
)


@pytest.fixture
def settings(database_url: str, tmp_path: Path) -> Settings:
    return make_settings(
        tmp_path,
        database_url=database_url,
        max_run_conversations=6,
        max_run_repeats=3,
        max_run_retries=2,
        max_run_start_interval_s=60,
    )


async def test_a_run_starts_each_repeat_of_every_scenario_in_order_with_its_persona(
    client: AsyncClient,
) -> None:
    agent = await create_agent_id(client)
    calm = (await create_persona(client, name="Calm caller"))["id"]
    hurried = (await create_persona(client, name="Hurried caller"))["id"]
    first = await create_scenario(client, agent, persona_id=calm)
    second = await create_scenario(client, agent, name="Cancel a cleaning", persona_id=hurried)
    single = await start(client, agent)

    response = await start_run(
        client,
        agent,
        [second["id"], first["id"]],
        repeats=3,
        name="Nightly",
        max_parallel=2,
        start_interval_s=5,
        max_retries=2,
    )

    assert response.status_code == 202, response.text
    run = response.json()
    assert (run["status"], run["name"], run["repeats"], run["max_retries"]) == (
        "queued",
        "Nightly",
        3,
        2,
    )
    assert (run["max_parallel"], run["start_interval_s"], run["max_duration_s"]) == (2, 5, 300)
    assert run["counts"] == {**NO_OUTCOMES, "waiting": 6}
    assert run["started_at"] is None and run["ended_at"] is None
    queued = await run_conversations(client, run["id"])
    assert [(c["repeat"], c["scenario_id"], c["persona_id"]) for c in queued] == [
        (repeat, scenario["id"], persona)
        for repeat in (1, 2, 3)
        for scenario, persona in ((second, hurried), (first, calm))
    ]
    assert {(c["run_id"], c["attempt"], c["retry_of"], c["status"]) for c in queued} == {
        (run["id"], 1, None, "queued")
    }
    assert single["run_id"] is None and single["id"] not in {c["id"] for c in queued}
    detail = (await client.get(f"/api/v1/runs/{run['id']}")).json()
    assert detail["scenario_ids"] == [second["id"], first["id"]]
    assert detail["median_talk_ms"] is None


async def test_every_conversation_of_a_run_pins_what_was_current_when_it_started(
    client: AsyncClient,
) -> None:
    agent = await create_agent_id(client)
    persona = (await create_persona(client, name="Calm caller"))["id"]
    first = await create_scenario(client, agent, persona_id=persona)
    second = await create_scenario(client, agent, name="Cancel a cleaning", persona_id=persona)
    run = (await start_run(client, agent, [first["id"], second["id"]], repeats=2)).json()

    edits = [
        await client.patch(f"/api/v1/agents/{agent}", json={"brief": "Changed."}),
        await client.patch(f"/api/v1/scenarios/{first['id']}", json={"goal": "Cancel it."}),
        await client.patch(f"/api/v1/personas/{persona}", json={"prompt": "Someone else."}),
    ]

    queued = await run_conversations(client, run["id"])
    details = [(await client.get(f"/api/v1/conversations/{c['id']}")).json() for c in queued]
    assert [edit.json()["current_version"] for edit in edits] == [2, 2, 2]
    assert {
        (c["agent_version_id"], c["agent_version"], c["scenario_version"], c["persona_version"])
        for c in queued
    } == {(run["agent_version_id"], 1, 1, 1)}
    assert (await client.get(f"/api/v1/runs/{run['id']}")).json()["agent_version"] == 1
    assert not any(
        "Cancel it." in d["instructions"] or "Someone else." in d["instructions"] for d in details
    )


async def test_one_bad_scenario_refuses_the_whole_run_and_is_named(client: AsyncClient) -> None:
    agent, other = await create_agent_id(client), await create_agent_id(client, name="Other")
    kept = await create_scenario(client, agent)
    deleted = await create_scenario(client, agent, name="Deleted one")
    await client.delete(f"/api/v1/scenarios/{deleted['id']}")
    foreign = await create_scenario(client, other, name="Belongs elsewhere")
    unknown = str(uuid.uuid4())

    gone = await start_run(client, agent, [kept["id"], deleted["id"]])
    missing = await start_run(client, agent, [kept["id"], unknown])
    crossed = await start_run(client, agent, [kept["id"], foreign["id"]])

    assert gone.status_code == 404 and deleted["id"] in gone.json()["error"]["message"]
    assert missing.status_code == 404 and unknown in missing.json()["error"]["message"]
    assert crossed.status_code == 422
    assert crossed.json()["error"]["message"] == (
        'the scenario "Belongs elsewhere" belongs to another agent'
    )
    assert (await client.get("/api/v1/runs")).json()["total"] == 0
    assert (await client.get("/api/v1/conversations")).json()["total"] == 0


async def test_a_run_needs_distinct_scenarios_within_the_limits(client: AsyncClient) -> None:
    agent = await create_agent_id(client)
    ids = [(await create_scenario(client, agent, name=f"Scenario {n}"))["id"] for n in range(4)]

    async def refused(scenario_ids: list[str], **fields: Any) -> str:
        response = await start_run(client, agent, scenario_ids, **fields)
        assert response.status_code == 422, response.text
        return response.json()["error"]["message"]

    assert (await refused([])).startswith("scenario_ids: ")
    assert await refused([ids[0], ids[1], ids[0]]) == (
        f"scenario_ids: scenario {ids[0]} is listed more than once"
    )
    assert await refused(ids[:1], repeats=4) == "repeats: at most 3"
    assert await refused(ids[:1], max_retries=3) == "max_retries: at most 2"
    assert await refused(ids[:1], start_interval_s=61) == "start_interval_s: at most 60"
    assert (await refused(ids[:1], max_parallel=0)).startswith("max_parallel: ")
    assert await refused(ids[:1], max_parallel=7) == "max_parallel: at most 6"
    assert (await refused(ids[:1], priority="high")).startswith("priority: ")
    assert await refused(ids, repeats=2) == (
        "a run starts at most 6 conversations; 4 scenarios and 2 repeats make 8"
    )
    assert (await client.get("/api/v1/runs")).json()["total"] == 0


async def test_a_repeated_request_returns_its_run_and_its_key_cannot_start_another(
    client: AsyncClient,
) -> None:
    agent = await create_agent_id(client)
    scenario = (await create_scenario(client, agent))["id"]

    first = await start_run(client, agent, [scenario], key="nightly-1")
    again = await start_run(client, agent, [scenario], key="nightly-1", repeats=1)
    other = await start_run(client, agent, [scenario], key="nightly-1", repeats=2)
    unkeyed = await start_run(client, agent, [scenario])

    assert first.status_code == again.status_code == unkeyed.status_code == 202
    assert again.json()["id"] == first.json()["id"] != unkeyed.json()["id"]
    assert other.status_code == 409 and "Idempotency-Key" in other.json()["error"]["message"]
    assert (await client.get("/api/v1/conversations")).json()["total"] == 2


async def test_a_repeated_request_returns_its_run_after_the_operator_changes_the_defaults(
    client: AsyncClient, settings: Settings
) -> None:
    agent = await create_agent_id(client)
    scenario = (await create_scenario(client, agent))["id"]
    first = await start_run(client, agent, [scenario], key="nightly-3")

    async with client_with(settings, default_max_duration_s=600, max_run_retries=0) as changed:
        again = await start_run(changed, agent, [scenario], key="nightly-3")

    assert again.status_code == 202 and again.json()["id"] == first.json()["id"]
    assert (await client.get("/api/v1/conversations")).json()["total"] == 1


async def test_a_repeated_request_returns_its_run_after_the_agent_is_gone(
    client: AsyncClient, db: Db
) -> None:
    agent = await create_agent_id(client)
    scenario = (await create_scenario(client, agent))["id"]
    first = (await start_run(client, agent, [scenario], key="nightly-2")).json()
    async with db.begin() as session:
        await session.execute(
            update(Conversation)
            .where(Conversation.run_id == uuid.UUID(first["id"]))
            .values(status=ConversationStatus.COMPLETED, ended_at=func.now())
        )
    assert (await client.delete(f"/api/v1/agents/{agent}")).status_code == 204

    again = await start_run(client, agent, [scenario], key="nightly-2")

    assert again.status_code == 202 and again.json()["id"] == first["id"]


async def test_a_request_that_waited_for_one_with_its_key_returns_that_run(
    client: AsyncClient, db: Db
) -> None:
    agent = await create_agent_id(client)
    scenario = await create_scenario(client, agent)

    async with db() as holder:
        await holder.get_one(Persona, uuid.UUID(scenario["persona_id"]), with_for_update=True)
        first = asyncio.create_task(start_run(client, agent, [scenario["id"]], key="k"))
        await wait_for_lock_waiters(db, 1)
        second = asyncio.create_task(start_run(client, agent, [scenario["id"]], key="k"))
        await wait_for_lock_waiters(db, 2)
        deleted = asyncio.create_task(client.delete(f"/api/v1/scenarios/{scenario['id']}"))
        await wait_for_lock_waiters(db, 3)
        await holder.rollback()
    responses = await asyncio.gather(first, second, deleted)

    assert [response.status_code for response in responses] == [202, 202, 204], (
        "the second request waits for the first, and the scenario is deleted in between"
    )
    assert responses[1].json()["id"] == responses[0].json()["id"]


async def test_a_run_does_not_wait_for_a_transaction_that_only_references_its_scenarios(
    client: AsyncClient, db: Db
) -> None:
    agent = await create_agent_id(client)
    scenario = await create_scenario(client, agent)

    async with db() as holder:
        for model, row_id in ((Scenario, scenario["id"]), (Persona, scenario["persona_id"])):
            await holder.execute(
                select(model.id)
                .where(model.id == uuid.UUID(row_id))
                .with_for_update(read=True, key_share=True)
            )
        response = await asyncio.wait_for(start_run(client, agent, [scenario["id"]]), 5)
        await holder.rollback()

    assert response.status_code == 202, "a copied agent or a retry holds such key-share locks"


async def test_two_requests_with_one_key_at_the_same_moment_start_one_run(
    client: AsyncClient,
) -> None:
    agent = await create_agent_id(client)
    scenario = (await create_scenario(client, agent))["id"]

    responses = await asyncio.gather(
        *(start_run(client, agent, [scenario], key="double-click", repeats=2) for _ in range(2))
    )

    assert [response.status_code for response in responses] == [202, 202]
    assert responses[0].json()["id"] == responses[1].json()["id"]
    assert (await client.get("/api/v1/conversations")).json()["total"] == 2


async def test_one_key_sent_for_two_agents_at_the_same_moment_starts_one_run(
    client: AsyncClient, db: Db
) -> None:
    persona = (await create_persona(client, name="Shared caller"))["id"]
    agents = [await create_agent_id(client), await create_agent_id(client, name="Other")]
    scenarios = [(await create_scenario(client, a, persona_id=persona))["id"] for a in agents]

    async with db() as holder:
        await holder.get_one(Persona, uuid.UUID(persona), with_for_update=True)
        starts = [
            asyncio.create_task(start_run(client, agent, [scenario], key="shared"))
            for agent, scenario in zip(agents, scenarios, strict=True)
        ]
        await wait_for_lock_waiters(db, 2)
        await holder.rollback()
    responses = [await task for task in starts]

    assert sorted(response.status_code for response in responses) == [202, 409]
    assert (await client.get("/api/v1/runs")).json()["total"] == 1


async def test_a_run_is_counted_from_its_conversations_as_they_finish(
    client: AsyncClient, caller: FakeCaller, worker: Worker
) -> None:
    caller.mode = "caller_hangs_up"
    agent = await create_agent_id(client)
    ids = [(await create_scenario(client, agent, name=f"Scenario {n}"))["id"] for n in range(2)]
    run = (await start_run(client, agent, ids, repeats=2)).json()

    done = await wait_for_run(client, run["id"], "done")

    assert done["counts"] == {**NO_OUTCOMES, "completed": 4}
    assert done["end_reasons"] == {"caller_hangup": 4}
    assert done["started_at"] is not None and done["ended_at"] is not None
    completed = await run_conversations(client, run["id"], group="completed")
    assert [c["caller_reason"] for c in completed] == ["the room is booked"] * 4
    assert await run_conversations(client, run["id"], group="waiting") == []


async def test_counts_take_the_latest_attempt_and_the_list_can_leave_out_retried_ones(
    client: AsyncClient, db: Db
) -> None:
    agent = await create_agent_id(client)
    scenario = (await create_scenario(client, agent))["id"]
    run = (await start_run(client, agent, [scenario], repeats=2)).json()
    first, second = await run_conversations(client, run["id"])
    assert [await claim(db), await claim(db)] == [first["id"], second["id"]]
    failed = CallOutcome(
        connected=True, end_reason=EndReason.ERROR, caller_error="boom", talk_ms=4000
    )
    completed = CallOutcome(connected=True, end_reason=EndReason.AGENT_HANGUP, talk_ms=9000)
    assert await finish(db, first["id"], failed)
    assert await finish(db, second["id"], completed)

    retry = (await run_conversations(client, run["id"]))[-1]["id"]
    detail = (await client.get(f"/api/v1/runs/{run['id']}")).json()
    latest = await run_conversations(client, run["id"], latest_attempts=True)
    errors = await run_conversations(client, run["id"], group="error")
    retried_from = (await client.get(f"/api/v1/conversations/{first['id']}")).json()
    retried_to = (await client.get(f"/api/v1/conversations/{retry}")).json()

    assert detail["counts"] == {**NO_OUTCOMES, "waiting": 1, "completed": 1}
    assert detail["end_reasons"] == {"agent_hangup": 1}
    assert (detail["retries"], detail["median_talk_ms"]) == (1, 9000)
    assert len(await run_conversations(client, run["id"])) == 3
    assert [c["id"] for c in latest] == [second["id"], retry]
    assert [c["id"] for c in errors] == [first["id"]]
    assert await run_conversations(client, run["id"], group="error", latest_attempts=True) == []
    assert retried_from["retried_as"] == retry and retried_to["retried_as"] is None
    assert (retried_to["retry_of"], retried_to["attempt"]) == (first["id"], 2)


async def test_runs_are_listed_newest_first_and_by_agent(client: AsyncClient) -> None:
    agent, other = await create_agent_id(client), await create_agent_id(client, name="Other")
    mine = (await create_scenario(client, agent))["id"]
    theirs = (await create_scenario(client, other))["id"]
    older = (await start_run(client, agent, [mine])).json()
    newer = (await start_run(client, agent, [mine], name="Second")).json()
    await start_run(client, other, [theirs])

    listed = (await client.get("/api/v1/runs", params={"agent_id": agent})).json()

    assert [run["id"] for run in listed["items"]] == [newer["id"], older["id"]]
    assert listed["total"] == 2
    assert (await client.get("/api/v1/runs")).json()["total"] == 3
    assert (await client.get(f"/api/v1/runs/{uuid.uuid4()}")).status_code == 404


async def test_omitted_fields_take_the_operators_defaults_as_the_api_reports_them(
    client: AsyncClient, settings: Settings
) -> None:
    agent = await create_agent_id(client)
    scenario = (await create_scenario(client, agent))["id"]
    standard = (await client.get("/api/v1/defaults")).json()

    async with client_with(settings, default_max_duration_s=120, max_run_retries=0) as strict:
        reported = (await strict.get("/api/v1/defaults")).json()
        started = await start_run(strict, agent, [scenario])
        refused = await start_run(strict, agent, [scenario], max_retries=1)

    assert standard == {"max_duration_s": 300, "max_retries": 1}
    assert reported == {"max_duration_s": 120, "max_retries": 0}
    assert started.status_code == 202
    assert (started.json()["max_duration_s"], started.json()["max_retries"]) == (120, 0)
    assert refused.status_code == 422 and refused.json()["error"]["message"] == (
        "max_retries: at most 0"
    )


@asynccontextmanager
async def client_with(settings: Settings, **changes: Any) -> AsyncGenerator[AsyncClient]:
    """A client of a second app on the same database, with other operator settings."""
    app = create_app(settings.model_copy(update=changes))
    headers = {"Authorization": f"Bearer {TOKEN}"}
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test", headers=headers
        ) as client:
            yield client
    finally:
        await app.state.engine.dispose()
