import asyncio
import uuid
from typing import Any

from httpx import AsyncClient, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import (
    OUTBOUND_AGENT,
    RECEIVING_APP_ID,
    WITH_AGENT_DATA,
    Db,
    claim,
    create_agent,
    create_agent_id,
    create_persona,
    create_scenario,
    finish,
    link_receiving_number,
    receive_outbound_calls,
    report_receiving_worker,
    run_conversations,
    wait_for_lock_waiters,
)
from yaksh.config import Settings
from yaksh.db.models import Agent, Conversation, Evaluation, Persona, Run, Suite, SuiteRun
from yaksh.domain.answering import AnsweredBy
from yaksh.domain.conversations import CallOutcome, EndReason
from yaksh.domain.evaluations import Verdict
from yaksh.evaluation import evaluations
from yaksh.evaluation.evaluations import Evaluated

SUITES = "/api/v1/suites"


async def new_suite(client: AsyncClient, name: str = "Release check") -> dict[str, Any]:
    response = await client.post(SUITES, json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


async def save_entries(
    client: AsyncClient, suite: dict[str, Any], entries: list[dict[str, Any]]
) -> Response:
    return await client.patch(
        f"{SUITES}/{suite['id']}", json={"revision": suite["revision"], "entries": entries}
    )


async def suite_with(
    client: AsyncClient, entries: list[dict[str, Any]], **name: str
) -> dict[str, Any]:
    response = await save_entries(client, await new_suite(client, **name), entries)
    assert response.status_code == 200, response.text
    return response.json()


async def start_suite(client: AsyncClient, suite_id: str, key: str | None = None) -> Response:
    return await client.post(
        f"{SUITES}/{suite_id}/runs", headers={} if key is None else {"Idempotency-Key": key}
    )


def entry(agent: str, scenarios: Any, transport: str = "phone", **settings: Any) -> dict[str, Any]:
    return {"agent_id": agent, "transport": transport, "scenarios": scenarios, **settings}


async def rows(db: Db, model: type[Any]) -> int:
    async with db() as session:
        return await session.scalar(select(func.count()).select_from(model)) or 0


async def test_a_start_makes_one_run_for_each_entry_in_entry_order(client: AsyncClient) -> None:
    first, second = await create_agent_id(client), await create_agent_id(client, name="Second")
    chosen = await create_scenario(client, first)
    own = chosen["persona_id"]
    early = await create_scenario(client, second, name="Early")
    suite = await suite_with(
        client,
        [entry(first, [{"scenario_id": chosen["id"]}], repeats=2), entry(second, {})],
    )
    late = await create_scenario(client, second, name="Late")
    other = (await create_persona(client, name="Someone else"))["id"]
    await client.patch(f"/api/v1/scenarios/{chosen['id']}", json={"persona_id": other})

    started = await start_suite(client, suite["id"], key="nightly-1")
    await client.patch(
        f"{SUITES}/{suite['id']}", json={"revision": suite["revision"], "required_pass_percent": 50}
    )
    again = await start_suite(client, suite["id"], key="nightly-1")
    elsewhere = await start_suite(
        client, (await suite_with(client, [entry(first, {})], name="Other"))["id"], key="nightly-1"
    )
    found = (await client.get(f"/api/v1/suite-runs/{started.json()['id']}")).json()

    assert started.status_code == 202, started.text
    assert suite["entries"][0]["scenarios"][0]["persona_ids"] == [own]
    assert [part["run"]["agent_id"] for part in found["runs"]] == [first, second]
    assert [part["run"]["suite_run"]["position"] for part in found["runs"]] == [1, 2]
    first_run, second_run = (part["run"]["id"] for part in found["runs"])
    assert [c["persona_id"] for c in await run_conversations(client, first_run)] == [own, own]
    assert {c["scenario_id"] for c in await run_conversations(client, second_run)} == {
        early["id"],
        late["id"],
    }
    assert found["required_pass_percent"] == 80, "the suite run keeps the rate it started with"
    assert (again.status_code, again.json()["id"]) == (202, found["id"])
    assert elsewhere.status_code == 409


async def test_starts_with_one_key_make_one_suite_run_whatever_happens_while_they_wait(
    client: AsyncClient, db: Db
) -> None:
    agent = await create_agent_id(client)
    scenario = (await create_scenario(client, agent))["id"]
    suite = await suite_with(client, [entry(agent, [{"scenario_id": scenario}])])
    one, two = [await suite_with(client, [entry(agent, {})], name=name) for name in ("A", "B")]

    async with db() as holder:
        await holder.get_one(Suite, uuid.UUID(suite["id"]), with_for_update=True)
        first = asyncio.create_task(start_suite(client, suite["id"], key="k"))
        await wait_for_lock_waiters(db, 1)
        emptied = asyncio.create_task(save_entries(client, suite, []))
        await wait_for_lock_waiters(db, 2)
        second = asyncio.create_task(start_suite(client, suite["id"], key="k"))
        await wait_for_lock_waiters(db, 3)
        await holder.rollback()
    same_suite = await asyncio.gather(first, emptied, second)
    async with db() as holder:
        await holder.get_one(Agent, uuid.UUID(agent), with_for_update=True)
        racing = [
            asyncio.create_task(start_suite(client, suite_id, key="shared"))
            for suite_id in (one["id"], two["id"])
        ]
        await wait_for_lock_waiters(db, 2)
        await holder.rollback()
    two_suites = [await task for task in racing]

    assert [response.status_code for response in same_suite] == [202, 200, 202], (
        "the second start waits for the first, and the suite is emptied in between"
    )
    assert same_suite[2].json()["id"] == same_suite[0].json()["id"]
    assert sorted(response.status_code for response in two_suites) == [202, 409]


async def test_a_start_names_every_broken_entry_and_starts_nothing(
    client: AsyncClient, db: Db
) -> None:
    kept = await create_agent_id(client, name="Kept")
    dropped = await create_agent_id(client, name="Dropped")
    deleted = await create_scenario(client, kept, name="Deleted")
    spare = await create_scenario(client, kept, name="Spare")
    other = await create_scenario(client, dropped, name="Other")
    suite = await suite_with(
        client,
        [
            entry(kept, [{"scenario_id": deleted["id"]}]),
            entry(dropped, [{"scenario_id": other["id"]}]),
        ],
    )
    await client.delete(f"/api/v1/scenarios/{deleted['id']}")
    await client.delete(f"/api/v1/agents/{dropped}")

    broken = await start_suite(client, suite["id"])
    shown = (await client.get(f"{SUITES}/{suite['id']}")).json()
    fixed = await save_entries(
        client,
        shown,
        [
            entry(kept, [{"scenario_id": spare["id"]}]),
            entry(dropped, [{"scenario_id": other["id"]}]),
        ],
    )
    still = await start_suite(client, suite["id"])
    unknown = await save_entries(
        client,
        fixed.json(),
        [entry(kept, [{"scenario_id": spare["id"], "persona_ids": [str(uuid.uuid4())]}])],
    )

    assert broken.status_code == 422
    assert broken.json()["error"]["message"] == (
        'entry 1, Kept (phone): the scenario "Deleted" was deleted; '
        "entry 2, Dropped (phone): the agent was deleted"
    )
    assert [e["problems"] for e in shown["entries"]] == [
        ['the scenario "Deleted" was deleted'],
        ["the agent was deleted"],
    ]
    assert (shown["entries"][0]["scenario_count"], shown["entries"][0]["calls"]) == (0, 0)
    assert fixed.status_code == 200, "a broken entry does not stop the fix of another one"
    assert still.json()["error"]["message"] == "entry 2, Dropped (phone): the agent was deleted"
    assert unknown.status_code == 422 and "entry 1: persona" in unknown.text
    assert (await rows(db, SuiteRun), await rows(db, Run), await rows(db, Conversation)) == (
        0,
        0,
        0,
    )


async def test_a_start_plays_what_an_edit_that_it_waited_for_left(
    client: AsyncClient, db: Db
) -> None:
    agent = await create_agent_id(client)
    scenario = await create_scenario(client, agent)
    suite = await suite_with(client, [entry(agent, {})])
    new_persona = (await create_persona(client, name="New caller"))["id"]

    async with db() as holder:
        await holder.get_one(Persona, uuid.UUID(new_persona), with_for_update=True)
        edit = asyncio.create_task(
            client.patch(f"/api/v1/scenarios/{scenario['id']}", json={"persona_id": new_persona})
        )
        await wait_for_lock_waiters(db, 1)
        started = asyncio.create_task(start_suite(client, suite["id"]))
        await wait_for_lock_waiters(db, 2)
        await holder.rollback()
    edited, start = await asyncio.gather(edit, started)
    (conversation,) = await run_conversations(client, start.json()["runs"][0]["run"]["id"])

    assert (edited.status_code, start.status_code) == (200, 202)
    assert conversation["persona_id"] == new_persona, (
        "the start read the scenario before the edit, and waited for it on the scenario's lock"
    )


async def test_a_stale_save_and_a_delete_during_a_suite_run_are_refused(
    client: AsyncClient,
) -> None:
    agent = await create_agent_id(client)
    scenario = (await create_scenario(client, agent))["id"]
    suite = await suite_with(client, [entry(agent, [{"scenario_id": scenario}])])

    stale = await save_entries(client, {**suite, "revision": suite["revision"] - 1}, [])
    await new_suite(client, "Taken")
    renamed = await client.patch(
        f"{SUITES}/{suite['id']}",
        json={"revision": suite["revision"], "name": "Taken", "entries": []},
    )
    started = await start_suite(client, suite["id"])
    busy = await client.delete(f"{SUITES}/{suite['id']}")
    cancelled = await client.post(f"/api/v1/suite-runs/{started.json()['id']}/cancel")
    deleted = await client.delete(f"{SUITES}/{suite['id']}")

    assert stale.status_code == 409
    assert renamed.status_code == 409 and "name is already used" in renamed.text
    assert busy.status_code == 409
    assert cancelled.json()["result"] == "cancelled"
    assert [part["run"]["status"] for part in cancelled.json()["runs"]] == ["cancelled"]
    assert deleted.status_code == 204
    assert (await client.get(f"{SUITES}/{suite['id']}")).status_code == 404
    assert (await client.get(f"/api/v1/suite-runs/{started.json()['id']}")).status_code == 200


async def test_each_run_counts_its_own_calls_and_a_failed_voicemail_call_fails_its_run(
    client: AsyncClient, settings: Settings, db: Db
) -> None:
    await receive_outbound_calls(db)
    await report_receiving_worker(settings)
    await link_receiving_number(settings)
    agent = (await create_agent(client, **OUTBOUND_AGENT))["id"]
    persona = await create_persona(client, name="Picks up")
    talks = await create_scenario(client, agent, name="Talks", data_sets=WITH_AGENT_DATA)
    machines = await create_scenario(
        client, agent, name="Machines", persona_id=persona["id"], data_sets=WITH_AGENT_DATA
    )
    suite = await suite_with(
        client,
        [
            entry(agent, [{"scenario_id": talks["id"]}], repeats=4, max_retries=1),
            entry(
                agent,
                [
                    {
                        "scenario_id": machines["id"],
                        "answered_by": ["caller", "voicemail", "screener"],
                    }
                ],
            ),
        ],
    )
    started = (await start_suite(client, suite["id"])).json()
    await client.patch(
        f"/api/v1/personas/{persona['id']}", json={"answering": {"after_screening": "voicemail"}}
    )
    plain, answered = (part["run"]["id"] for part in started["runs"])
    plays = {c["id"]: c for run in (plain, answered) for c in await run_conversations(client, run)}
    outcomes = [
        CallOutcome(connected=True, end_reason=EndReason.AGENT_HANGUP),
        CallOutcome(connected=False, end_reason=EndReason.ERROR, caller_error="lost"),
        CallOutcome(connected=True, end_reason=EndReason.USER_REQUEST),
        CallOutcome(connected=False, end_reason=EndReason.NO_ANSWER),
    ]
    order = iter(outcomes)
    while (claimed := await claim(db, receiving_app_id=RECEIVING_APP_ID)) is not None:
        first = plays.get(claimed, {}).get("run_id") == plain and plays[claimed]["attempt"] == 1
        await finish(db, claimed, next(order) if first else outcomes[0])
    held = await judge(db)
    judging = (await client.get(f"/api/v1/suite-runs/{started['id']}")).json()
    assert held is not None
    async with db() as session:
        await judged(session, held, Verdict.FAIL)
    found = (await client.get(f"/api/v1/suite-runs/{started['id']}")).json()

    assert [part["result"] for part in judging["runs"]] == ["not_decided", "judging"]
    assert [part["result"] for part in found["runs"]] == ["not_decided", "failed"]
    assert found["result"] == "failed"
    numbers = [part["numbers"] for part in found["runs"]]
    assert [(n["passed"], n["failed"], n["not_scored"]) for n in numbers] == [(2, 0, 2), (1, 0, 0)]
    assert [(n["unplayed_passed"], n["unplayed_failed"]) for n in numbers] == [(0, 0), (1, 1)]


async def judge(db: Db) -> Evaluation | None:
    """Pass every queued evaluation, except a voicemail call's: it stays running, as under a
    judge at work, and is returned."""
    held = None
    async with db() as session:
        while (evaluation := await evaluations.claim(session, "e1", 60)) is not None:
            conversation = await session.get_one(Conversation, evaluation.conversation_id)
            if conversation.answered_by is AnsweredBy.VOICEMAIL:
                held = evaluation
            else:
                await judged(session, evaluation, Verdict.PASS)
    return held


async def judged(session: AsyncSession, evaluation: Evaluation, verdict: Verdict) -> None:
    await evaluations.finish(
        session,
        evaluation.id,
        evaluation.claim_seq,
        Evaluated(metrics={}, scenario_verdict=verdict, conversation_verdict=verdict),
        audit=False,
    )
