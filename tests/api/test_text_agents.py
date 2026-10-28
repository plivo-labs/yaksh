from typing import Any

from httpx import AsyncClient
from sqlalchemy import update

from tests.conftest import (
    AGENT,
    APP_SETTINGS,
    OUTBOUND_AGENT,
    POOL_APP_ID,
    Db,
    claim,
    create_agent,
    create_scenario,
    new_persona_id,
    run_conversations,
    start,
    start_run,
)
from yaksh.db.models import Conversation, PhoneNumber
from yaksh.domain.agents import Transport
from yaksh.simulation import conversations

ENDPOINT = {
    "url": "https://agents.example.com/v1/agent/123/text-test",
    "headers": [{"name": "Authorization", "value": "Bearer {{secrets.AGENT_TOKEN}}"}],
}
TEXT_AGENT: dict[str, Any] = {"agent_number": None, "endpoint": ENDPOINT}


async def test_an_agent_has_a_phone_connection_a_text_endpoint_or_both(
    client: AsyncClient,
) -> None:
    text = await create_agent(client, **TEXT_AGENT)
    both = await create_agent(client, endpoint=ENDPOINT)
    neither = await client.post("/api/v1/agents", json={**AGENT, **TEXT_AGENT, "endpoint": None})
    placeholder = await client.post(
        "/api/v1/agents",
        json={
            **AGENT,
            **TEXT_AGENT,
            "endpoint": {
                "url": TEXT_AGENT["endpoint"]["url"],
                "headers": [{"name": "X-Patient", "value": "{{agent_data.Patient name}}"}],
            },
        },
    )

    assert text["transports"] == ["text"]
    assert text["endpoint"] == ENDPOINT
    assert both["transports"] == ["phone", "text"]
    assert neither.status_code == 422 and "a way to reach it" in neither.text
    assert placeholder.status_code == 422


async def test_a_text_run_starts_and_is_claimed_with_no_voice_number_and_leases_none(
    client: AsyncClient, db: Db
) -> None:
    async with db() as session:
        await session.execute(update(PhoneNumber).values(voice=False))
        await session.commit()
    agent = await create_agent(client, **TEXT_AGENT)
    scenario = await create_scenario(client, agent["id"], interruptions=[{"say": "Mm-hmm."}])
    conversation = await start(client, agent["id"], scenario_id=scenario["id"])

    claimed = await claim(db)
    async with db() as session:
        row = await session.get_one(Conversation, conversation["id"])
        call = await conversations.prepare_call(session, APP_SETTINGS, row, POOL_APP_ID, None)

    assert conversation["transport"] == "text"
    assert claimed == conversation["id"]
    assert call.caller_number is None
    assert call.agent.endpoint is not None
    assert call.interruptions == [], "a text run plays no interruption"


async def test_text_and_phone_conversations_are_claimed_within_their_own_limits(
    client: AsyncClient, db: Db
) -> None:
    agent = await create_agent(client, **TEXT_AGENT)
    conversation = await start(client, agent["id"])

    assert await claim(db, transports=frozenset({Transport.PHONE})) is None
    assert await claim(db, transports=frozenset({Transport.TEXT})) == conversation["id"]


async def scenario_id(client: AsyncClient, agent_id: str) -> str:
    persona_id = await new_persona_id(client)
    return str((await create_scenario(client, agent_id, persona_id=persona_id))["id"])


async def test_a_run_of_an_agent_with_both_connections_names_its_transport(
    client: AsyncClient,
) -> None:
    agent = await create_agent(client, endpoint=ENDPOINT)
    scenario = await scenario_id(client, agent["id"])

    unnamed = await start_run(client, agent["id"], [scenario])
    text = await start_run(client, agent["id"], [scenario], transport="text")
    phone = await start_run(client, agent["id"], [scenario], transport="phone")
    (texted,) = await run_conversations(client, text.json()["id"])
    (called,) = await run_conversations(client, phone.json()["id"])

    assert unnamed.status_code == 422 and "choose phone or text" in unnamed.text
    assert text.json()["transport"] == "text" and texted["transport"] == "text"
    assert phone.json()["transport"] == "phone" and called["transport"] == "phone"


async def test_a_run_cannot_use_a_connection_the_agent_does_not_have(
    client: AsyncClient,
) -> None:
    phone_only = await create_agent(client)
    text_only = await create_agent(client, **TEXT_AGENT)

    no_text = await start_run(
        client, phone_only["id"], [await scenario_id(client, phone_only["id"])], transport="text"
    )
    no_phone = await start_run(
        client, text_only["id"], [await scenario_id(client, text_only["id"])], transport="phone"
    )

    assert no_text.status_code == 422 and "no text endpoint" in no_text.text
    assert no_phone.status_code == 422 and "no phone connection" in no_phone.text


async def test_a_text_run_of_an_outbound_agent_needs_no_trigger_agent_data(
    client: AsyncClient, db: Db
) -> None:
    agent = await create_agent(client, **OUTBOUND_AGENT, endpoint=ENDPOINT)
    scenario = await scenario_id(client, agent["id"])

    text = await start_run(client, agent["id"], [scenario], transport="text")
    (conversation,) = await run_conversations(client, text.json()["id"])
    async with db() as session:
        row = await session.get_one(Conversation, conversation["id"])

    assert text.status_code == 202, text.text
    assert conversation["direction"] == "outbound"
    assert "received a phone call" in row.instructions


async def test_a_run_keeps_its_transport_after_the_agent_loses_that_connection(
    client: AsyncClient,
) -> None:
    agent = await create_agent(client, endpoint=ENDPOINT)
    started = await start_run(
        client, agent["id"], [await scenario_id(client, agent["id"])], transport="text"
    )
    changed = await client.patch(f"/api/v1/agents/{agent['id']}", json={"endpoint": None})
    run = (await client.get(f"/api/v1/runs/{started.json()['id']}")).json()
    texts = (await client.get("/api/v1/runs", params={"transport": "text"})).json()["items"]
    phones = (await client.get("/api/v1/runs", params={"transport": "phone"})).json()["items"]

    assert changed.json()["transports"] == ["phone"]
    assert run["transport"] == "text"
    assert [item["id"] for item in texts] == [run["id"]]
    assert run["id"] not in [item["id"] for item in phones]
