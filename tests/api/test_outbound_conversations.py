import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, insert, select, update

from tests.conftest import (
    OUTBOUND_AGENT,
    create_agent,
    create_persona,
    create_scenario,
    make_settings,
)
from truman.config import Settings
from truman.db.models import Conversation, PhoneNumber
from truman.db.session import create_engine, create_sessionmaker
from truman.simulation import conversations

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
    unlinked = await start_outbound(client, agent_data=AGENT_DATA)
    await link_number(settings)
    lacking = await start_outbound(client, name="No data")
    started = await start_outbound(client, name="With data", agent_data=AGENT_DATA)

    assert unlinked.status_code == 422
    assert unlinked.json()["error"]["message"] == (
        f"no enabled number is linked to Plivo application {APP_ID}"
    )
    assert lacking.status_code == 422
    assert (
        lacking.json()["error"]["message"] == "the scenario has no agent data named customer name"
    )
    assert started.status_code == 202 and started.json()["direction"] == "outbound"


async def claim(settings: Settings, receiving_app_id: str | None) -> Conversation | None:
    engine = create_engine(settings.database_url.encoded_string())
    async with create_sessionmaker(engine)() as session:
        claimed = await conversations.claim_next(session, "w1", 30, receiving_app_id)
    await engine.dispose()
    return claimed


async def test_an_outbound_conversation_runs_only_where_its_call_can_be_received(
    client: AsyncClient, settings: Settings
) -> None:
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
    await link_number(settings)
    await start_outbound(client, agent_data=AGENT_DATA)
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
