import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, insert, select, update

from tests.conftest import (
    OUTBOUND_AGENT,
    FakeCaller,
    create_agent,
    create_persona,
    create_scenario,
    make_settings,
)
from truman.config import Settings
from truman.db.models import Conversation, PhoneNumber, RunningWorker
from truman.db.session import create_engine, create_sessionmaker
from truman.simulation import conversations
from truman.simulation.workers import report_worker
from truman.worker.worker import Worker

APP_ID = "31216907353261579"
RECEIVING = "+15716535187"
AGENT_DATA = [{"name": "Customer name", "value": "Priya Raman"}]


@pytest.fixture
def settings(database_url: str, tmp_path: Path) -> Settings:
    return make_settings(tmp_path, database_url=database_url, plivo_app_id=APP_ID)


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
            lease_s=settings.worker_lease_s,
        )
    await engine.dispose()


async def start_outbound(client: AsyncClient, **scenario: Any) -> Any:
    agent = await create_agent(client, **OUTBOUND_AGENT)
    created = await create_scenario(client, agent["id"], **scenario)
    persona = await create_persona(client, name=f"Caller {uuid.uuid4()}")
    return await client.post(
        "/api/v1/conversations",
        json={"agent_id": agent["id"], "scenario_id": created["id"], "persona_id": persona["id"]},
    )


async def test_an_outbound_start_needs_a_linked_number_and_the_triggers_agent_data(
    client: AsyncClient, settings: Settings
) -> None:
    await report(settings)
    unlinked = await start_outbound(client, agent_data=AGENT_DATA)
    await link_number(settings)
    lacking = await start_outbound(client, name="No data")
    started = await start_outbound(client, name="With data", agent_data=AGENT_DATA)

    assert unlinked.status_code == 422
    assert unlinked.json()["error"]["message"] == (
        f"outbound tests are off: no enabled number is linked to Plivo application {APP_ID}"
    )
    assert lacking.status_code == 422
    assert lacking.json()["error"]["message"] == (
        'the scenario "No data" has no agent data named customer name'
    )
    assert started.status_code == 202 and started.json()["direction"] == "outbound"


async def test_an_outbound_run_needs_the_same_setup_and_names_a_scenario_without_agent_data(
    client: AsyncClient, settings: Settings
) -> None:
    agent = await create_agent(client, **OUTBOUND_AGENT)
    with_data = await create_scenario(client, agent["id"], agent_data=AGENT_DATA)
    without = await create_scenario(client, agent["id"], name="No data")

    async def start_run(*scenarios: dict[str, Any]) -> Any:
        return await client.post(
            "/api/v1/runs",
            json={"agent_id": agent["id"], "scenario_ids": [s["id"] for s in scenarios]},
        )

    off = await start_run(with_data)
    await report(settings)
    await link_number(settings)
    lacking = await start_run(with_data, without)
    started = await start_run(with_data)

    assert off.status_code == 422
    assert off.json()["error"]["message"].startswith("outbound tests are off: ")
    assert lacking.status_code == 422
    assert lacking.json()["error"]["message"] == (
        'the scenario "No data" has no agent data named customer name'
    )
    assert started.status_code == 202, started.text
    queued = await client.get("/api/v1/conversations", params={"run_id": started.json()["id"]})
    assert [c["direction"] for c in queued.json()["items"]] == ["outbound"]


async def claim(settings: Settings, receiving_app_id: str | None) -> Conversation | None:
    engine = create_engine(settings.database_url.encoded_string())
    async with create_sessionmaker(engine)() as session:
        claimed = await conversations.claim_next(session, "w1", 30, receiving_app_id)
    await engine.dispose()
    return claimed


async def test_an_outbound_conversation_runs_only_where_its_call_can_be_received(
    client: AsyncClient, settings: Settings
) -> None:
    await report(settings)
    await link_number(settings, available_after=datetime.now(UTC) + timedelta(minutes=5))
    started = (await start_outbound(client, agent_data=AGENT_DATA)).json()

    no_application = await claim(settings, None)
    resting = await claim(settings, APP_ID)
    engine = create_engine(settings.database_url.encoded_string())
    async with engine.begin() as connection:
        await connection.execute(update(PhoneNumber).values(available_after=None))
    await engine.dispose()
    rested = await claim(settings, APP_ID)

    assert no_application is None and resting is None
    assert rested is not None and str(rested.id) == started["id"]


async def test_preparing_the_call_opens_the_dial_window_and_keeps_the_pinned_data(
    client: AsyncClient, settings: Settings
) -> None:
    await report(settings)
    await link_number(settings)
    outbound = {**OUTBOUND_AGENT["outbound"], "dial_window_s": 30}
    agent = await create_agent(client, **{**OUTBOUND_AGENT, "outbound": outbound})
    scenario = await create_scenario(client, agent["id"], agent_data=AGENT_DATA)
    persona = await create_persona(client, name=f"Caller {uuid.uuid4()}")
    await client.post(
        "/api/v1/conversations",
        json={"agent_id": agent["id"], "scenario_id": scenario["id"], "persona_id": persona["id"]},
    )
    edited = [{"name": "Customer name", "value": "Someone else"}]
    await client.patch(f"/api/v1/scenarios/{scenario['id']}", json={"agent_data": edited})
    claimed = await claim(settings, APP_ID)
    assert claimed is not None

    engine = create_engine(settings.database_url.encoded_string())
    async with create_sessionmaker(engine)() as session:
        request = await conversations.prepare_call(session, settings, claimed, APP_ID)
        window = await session.scalar(
            select(Conversation.dial_deadline_at - func.now()).where(Conversation.id == claimed.id)
        )
    await engine.dispose()

    assert request.caller_number == RECEIVING
    assert [fact.value for fact in request.agent_data] == ["Priya Raman"]
    assert window is not None and 44 < window.total_seconds() <= 45, "trigger timeout + window"


async def test_a_waiting_outbound_conversation_does_not_hold_up_inbound_ones(
    client: AsyncClient, settings: Settings
) -> None:
    await report(settings)
    await link_number(settings)
    waiting = await start_outbound(client, agent_data=AGENT_DATA)
    assert waiting.status_code == 202
    inbound = await create_agent(client)
    scenario = await create_scenario(client, inbound["id"])
    persona = await create_persona(client, name=f"Caller {uuid.uuid4()}")
    queued = await client.post(
        "/api/v1/conversations",
        json={
            "agent_id": inbound["id"],
            "scenario_id": scenario["id"],
            "persona_id": persona["id"],
        },
    )

    claimed = await claim(settings, None)

    assert claimed is not None and str(claimed.id) == queued.json()["id"]


async def test_the_numbers_page_shows_the_outbound_numbers_and_their_rest(
    client: AsyncClient, settings: Settings
) -> None:
    await report(settings)
    await link_number(settings, available_after=datetime.now(UTC) + timedelta(minutes=5))

    listed = (await client.get("/api/v1/phone-numbers")).json()

    receiving = next(n for n in listed["items"] if n["number"] == RECEIVING)
    others = [n for n in listed["items"] if n["number"] != RECEIVING]
    assert listed["outbound_problem"] is None
    assert receiving["on_outbound_application"] and receiving["state"] == "resting"
    assert others and not any(n["on_outbound_application"] for n in others)


async def test_an_outbound_start_needs_a_running_worker_that_receives_its_calls(
    client: AsyncClient, settings: Settings
) -> None:
    await link_number(settings)
    nobody = await start_outbound(client, agent_data=AGENT_DATA)
    await report(settings, "w1", receiving_app_id=None, outbound_problem="answer URL is wrong")
    await report(settings, "w2", receiving_app_id=None, outbound_problem="Plivo returned 401")
    misconfigured = await start_outbound(client, agent_data=AGENT_DATA)
    engine = create_engine(settings.database_url.encoded_string())
    async with engine.begin() as connection:
        await connection.execute(
            insert(RunningWorker).values(
                id="gone",
                receiving_app_id=APP_ID,
                seen_at=func.now() - timedelta(seconds=settings.worker_lease_s + 1),
            )
        )
    await engine.dispose()
    stopped = await start_outbound(client, agent_data=AGENT_DATA)
    engine = create_engine(settings.database_url.encoded_string())
    worker = Worker(create_sessionmaker(engine), FakeCaller(), settings, receiving_app_id=APP_ID)
    await worker.poll()
    await engine.dispose()
    running = await start_outbound(client, agent_data=AGENT_DATA)

    assert nobody.json()["error"]["message"] == (
        f"outbound tests are off: no running worker receives calls for application {APP_ID}"
    )
    assert misconfigured.json()["error"]["message"] == (
        "outbound tests are off: Plivo returned 401; answer URL is wrong"
    )
    assert stopped.status_code == 422, "a worker not seen for a lease has stopped"
    assert running.status_code == 202
