import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import func, insert, select, update

from tests.conftest import (
    APP_SETTINGS,
    FAST,
    OUTBOUND_AGENT,
    Db,
    FakeCaller,
    claim,
    create_agent,
    create_persona,
    create_scenario,
    data_sets,
    expire_leases,
    finish,
    make_settings,
    make_worker,
    reap,
    run_conversations,
    save_settings,
    start,
    start_run,
)
from yaksh.config import Settings
from yaksh.db.models import Conversation, PhoneNumber, RunningWorker
from yaksh.db.session import create_engine, create_sessionmaker
from yaksh.domain.answering import AnsweredBy, MachineLine
from yaksh.domain.conversations import CallOutcome, EndReason
from yaksh.simulation import conversations
from yaksh.simulation.workers import report_worker
from yaksh.timings import TIMINGS

APP_ID = "31216907353261579"
RECEIVING = "+15716535187"
AGENT_DATA = [{"name": "Customer name", "value": "Priya Raman"}]
WITH_DATA = data_sets(agent_data=AGENT_DATA)


@pytest.fixture
def settings(database_url: str, tmp_path: Path) -> Settings:
    return make_settings(tmp_path, database_url=database_url)


@pytest.fixture(autouse=True)
async def receiving(client: AsyncClient, db: Db) -> None:
    """The receiving application is APP_ID: RECEIVING, once linked, is the only test number."""
    await save_settings(db, values={"phone": {"application_id": APP_ID}})


async def link_number(settings: Settings, **columns: Any) -> None:
    engine = create_engine(settings.database_url.encoded_string())
    async with engine.begin() as connection:
        await connection.execute(
            insert(PhoneNumber).values(number=RECEIVING, application_id=APP_ID, **columns)
        )
    await engine.dispose()


async def report(
    settings: Settings,
    worker_id: str = "w1",
    *,
    receiving_app_id: str | None = APP_ID,
    outbound_problem: str | None = None,
) -> None:
    engine = create_engine(settings.database_url.encoded_string())
    async with create_sessionmaker(engine)() as session:
        await report_worker(
            session,
            worker_id,
            receiving_app_id=receiving_app_id,
            outbound_problem=outbound_problem,
            lease_s=FAST.worker_lease_s,
        )
    await engine.dispose()


async def start_outbound(client: AsyncClient, **scenario: Any) -> Response:
    agent = await create_agent(client, **OUTBOUND_AGENT)
    created = await create_scenario(client, agent["id"], **scenario)
    return await start_run(client, agent["id"], [created["id"]])


async def test_an_outbound_run_needs_a_linked_number_and_names_a_scenario_without_agent_data(
    client: AsyncClient, settings: Settings
) -> None:
    agent = await create_agent(client, **OUTBOUND_AGENT)
    with_data = await create_scenario(client, agent["id"], data_sets=WITH_DATA)
    without = await create_scenario(client, agent["id"], name="No data")

    await report(settings)
    unlinked = await start_run(client, agent["id"], [with_data["id"]])
    await link_number(settings)
    lacking = await start_run(client, agent["id"], [with_data["id"], without["id"]])
    started = await start_run(client, agent["id"], [with_data["id"]])

    assert unlinked.status_code == 422
    assert unlinked.json()["error"]["message"] == (
        "outbound tests are off: choose test numbers on the Numbers page"
    )
    assert lacking.status_code == 422
    assert lacking.json()["error"]["message"] == (
        'the scenario "No data" has no agent data named customer name'
    )
    assert started.status_code == 202, started.text
    queued = await client.get("/api/v1/conversations", params={"run_id": started.json()["id"]})
    assert [c["direction"] for c in queued.json()["items"]] == ["outbound"]


async def test_an_outbound_conversation_runs_only_where_its_call_can_be_received(
    client: AsyncClient, settings: Settings, db: Db
) -> None:
    await report(settings)
    await link_number(settings, available_after=datetime.now(UTC) + timedelta(minutes=5))
    (started,) = await run_conversations(
        client,
        (await start_outbound(client, data_sets=WITH_DATA)).json()["id"],
    )

    no_application = await claim(db)
    resting = await claim(db, receiving_app_id=APP_ID)
    async with db.begin() as session:
        await session.execute(update(PhoneNumber).values(available_after=None))
    rested = await claim(db, receiving_app_id=APP_ID)

    assert no_application is None and resting is None
    assert rested == started["id"]


async def test_preparing_the_call_opens_the_dial_window_and_keeps_the_pinned_data(
    client: AsyncClient, settings: Settings, db: Db
) -> None:
    await report(settings)
    await link_number(settings)
    outbound = {**OUTBOUND_AGENT["outbound"], "dial_window_s": 30}
    agent = await create_agent(client, **{**OUTBOUND_AGENT, "outbound": outbound})
    scenario = await create_scenario(client, agent["id"], data_sets=WITH_DATA)
    await start_run(client, agent["id"], [scenario["id"]])
    edited = [{"name": "Customer name", "value": "Someone else"}]
    changed = [{**scenario["data_sets"][0], "agent_data": edited}]
    await client.patch(f"/api/v1/scenarios/{scenario['id']}", json={"data_sets": changed})
    claimed = await claim(db, receiving_app_id=APP_ID)
    assert claimed is not None

    async with db() as session:
        conversation = await session.get_one(Conversation, uuid.UUID(claimed))
        request = await conversations.prepare_call(
            session, APP_SETTINGS, conversation, APP_ID, APP_ID
        )
        window = await session.scalar(
            select(Conversation.dial_deadline_at - func.now()).where(
                Conversation.id == conversation.id
            )
        )

    assert request.caller_number == RECEIVING
    assert [fact.value for fact in request.agent_data] == ["Priya Raman"]
    assert window is not None and 44 < window.total_seconds() <= 45, "trigger timeout + window"


async def test_a_waiting_outbound_conversation_does_not_hold_up_inbound_ones(
    client: AsyncClient, settings: Settings, db: Db
) -> None:
    await report(settings)
    await link_number(settings)
    waiting = await start_outbound(client, data_sets=WITH_DATA)
    assert waiting.status_code == 202
    queued = await start(client, (await create_agent(client))["id"])

    claimed = await claim(db)

    assert claimed == queued["id"]


async def test_the_numbers_page_shows_the_outbound_numbers_and_their_rest(
    client: AsyncClient, settings: Settings
) -> None:
    await report(settings)
    await link_number(settings, available_after=datetime.now(UTC) + timedelta(minutes=5))

    listed = (await client.get("/api/v1/phone-numbers")).json()

    receiving = next(n for n in listed["items"] if n["number"] == RECEIVING)
    others = [n for n in listed["items"] if n["number"] != RECEIVING]
    assert (
        listed["outbound_problem"] is None and listed["rest_s"] == APP_SETTINGS.phone.number_rest_s
    )
    assert receiving["owner"] == "test" and receiving["state"] == "resting"
    assert others and all(n["owner"] == "other" and n["state"] is None for n in others)


async def test_an_outbound_start_needs_a_running_worker_that_receives_its_calls(
    client: AsyncClient, settings: Settings
) -> None:
    await link_number(settings)
    nobody = await start_outbound(client, data_sets=WITH_DATA)
    await report(settings, "w1", receiving_app_id=None, outbound_problem="answer URL is wrong")
    await report(settings, "w2", receiving_app_id=None, outbound_problem="Plivo returned 401")
    misconfigured = await start_outbound(client, data_sets=WITH_DATA)
    engine = create_engine(settings.database_url.encoded_string())
    async with engine.begin() as connection:
        await connection.execute(
            insert(RunningWorker).values(
                id="gone",
                receiving_app_id=APP_ID,
                seen_at=func.now() - timedelta(seconds=TIMINGS.worker_lease_s + 1),
            )
        )
    await engine.dispose()
    stopped = await start_outbound(client, data_sets=WITH_DATA)
    engine = create_engine(settings.database_url.encoded_string())
    worker = make_worker(
        create_sessionmaker(engine), FakeCaller(), settings, receiving_app_id=APP_ID
    )
    await worker.poll()
    await engine.dispose()
    running = await start_outbound(client, data_sets=WITH_DATA)

    assert nobody.json()["error"]["message"] == (
        f"outbound tests are off: no running worker receives calls for application {APP_ID}"
    )
    assert misconfigured.json()["error"]["message"] == (
        "outbound tests are off: Plivo returned 401; answer URL is wrong"
    )
    assert stopped.status_code == 422, "a worker not seen for a lease has stopped"
    assert running.status_code == 202


async def test_an_outbound_retry_runs_as_outbound(
    client: AsyncClient, settings: Settings, db: Db
) -> None:
    await report(settings)
    await link_number(settings)
    agent = await create_agent(client, **OUTBOUND_AGENT)
    scenario = await create_scenario(client, agent["id"], data_sets=WITH_DATA)
    run = await start_run(client, agent["id"], [scenario["id"]])
    lost = await claim(db, receiving_app_id=APP_ID)
    assert run.status_code == 202 and lost is not None
    await expire_leases(db, Conversation.id == uuid.UUID(lost))
    await reap(db)

    inbound_only = await claim(db)
    retried = await claim(db, receiving_app_id=APP_ID)

    assert inbound_only is None and retried is not None
    detail = (await client.get(f"/api/v1/conversations/{retried}")).json()
    assert (detail["direction"], detail["attempt"]) == ("outbound", 2)


async def test_a_run_calls_each_persona_and_data_set_once_for_each_answer(
    client: AsyncClient, settings: Settings
) -> None:
    await report(settings)
    await link_number(settings)
    agent = await create_agent(client, **OUTBOUND_AGENT)
    noisy = await create_persona(client, name="Noisy caller", surroundings={"auto": {"db": -10}})
    scenario = await create_scenario(
        client, agent["id"], persona_id=noisy["id"], data_sets=WITH_DATA
    )
    answers = ["caller", "voicemail", "screener"]

    started = await start_run(
        client, agent["id"], [{"scenario_id": scenario["id"], "answered_by": answers}]
    )
    run_id = started.json()["id"]
    queued = await run_conversations(client, run_id)
    detail = (await client.get(f"/api/v1/runs/{run_id}")).json()
    voicemails = await run_conversations(client, run_id, answered_by="voicemail")
    caller, voicemail = [
        (await client.get(f"/api/v1/conversations/{queued[n]['id']}")).json() for n in (0, 1)
    ]

    assert started.status_code == 202, started.text
    assert [c["answered_by"] for c in queued] == answers
    assert detail["scenarios"][0]["answered_by"] == answers
    assert detail["answered_by"] == {"caller": 1, "voicemail": 1, "screener": 1}
    assert [c["id"] for c in voicemails] == [queued[1]["id"]]
    assert caller["answering"] is None and caller["sounds"] != []
    assert voicemail["answering"] == noisy["answering"]
    assert voicemail["sounds"] == [], "a recording has no surroundings behind it"


async def test_preparing_a_call_that_a_machine_answers_plans_what_the_phone_plays(
    client: AsyncClient, settings: Settings, db: Db
) -> None:
    await report(settings)
    await link_number(settings)
    agent = await create_agent(client, **OUTBOUND_AGENT)
    phone = {"voicemail": "carrier", "greeting": "Hi, it's Rachel.", "after_screening": "voicemail"}
    persona = await create_persona(client, name="Busy caller", answering=phone)
    scenario = await create_scenario(
        client, agent["id"], persona_id=persona["id"], data_sets=WITH_DATA
    )
    await start_run(
        client, agent["id"], [{"scenario_id": scenario["id"], "answered_by": ["screener"]}]
    )
    claimed = await claim(db, receiving_app_id=APP_ID)
    assert claimed is not None

    async with db() as session:
        conversation = await session.get_one(Conversation, uuid.UUID(claimed))
        request = await conversations.prepare_call(
            session, APP_SETTINGS, conversation, APP_ID, APP_ID
        )

    plan = request.answering
    assert request.answered_by is AnsweredBy.SCREENER
    assert plan is not None and plan.screener is not None and plan.voicemail is not None
    assert plan.screener.label == "iPhone call screening"
    assert plan.screener.prompt.line is MachineLine.SCREENER
    assert Path(plan.screener.prompt.file).is_file()
    assert (plan.voicemail.greeting, plan.voicemail.own_greeting) == (None, "Hi, it's Rachel.")
    assert plan.voicemail.tone is not None


async def test_a_retry_keeps_who_answers(client: AsyncClient, settings: Settings, db: Db) -> None:
    await report(settings)
    await link_number(settings)
    agent = await create_agent(client, **OUTBOUND_AGENT)
    scenario = await create_scenario(client, agent["id"], data_sets=WITH_DATA)
    started = await start_run(
        client,
        agent["id"],
        [{"scenario_id": scenario["id"], "answered_by": ["voicemail"]}],
        max_retries=1,
    )
    claimed = await claim(db, receiving_app_id=APP_ID)
    assert claimed is not None

    await finish(
        db, claimed, CallOutcome(connected=False, end_reason=EndReason.ERROR, caller_error="x")
    )
    attempts = await run_conversations(client, started.json()["id"])

    assert [(c["attempt"], c["answered_by"]) for c in attempts] == [
        (1, "voicemail"),
        (2, "voicemail"),
    ]
