from typing import Any

from httpx import AsyncClient
from sqlalchemy import update

from tests.conftest import AGENT, APP_SETTINGS, POOL_APP_ID, Db, claim, create_agent, start
from yaksh.db.models import Conversation, PhoneNumber
from yaksh.domain.agents import Transport
from yaksh.simulation import conversations

TEXT_AGENT: dict[str, Any] = {
    "agent_number": None,
    "transport": "text",
    "endpoint": {
        "url": "https://agents.example.com/v1/agent/123/text-test",
        "headers": [{"name": "Authorization", "value": "Bearer {{secrets.AGENT_TOKEN}}"}],
    },
}


async def test_a_text_agent_keeps_its_endpoint_and_takes_no_phone_settings(
    client: AsyncClient,
) -> None:
    created = await create_agent(client, **TEXT_AGENT)
    mixed = await client.post(
        "/api/v1/agents", json={**AGENT, **TEXT_AGENT, "agent_number": "+14155550100"}
    )
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

    assert created["transport"] == "text"
    assert created["endpoint"] == TEXT_AGENT["endpoint"]
    assert mixed.status_code == 422
    assert placeholder.status_code == 422


async def test_a_text_run_starts_and_is_claimed_with_no_voice_number_and_leases_none(
    client: AsyncClient, db: Db
) -> None:
    async with db() as session:
        await session.execute(update(PhoneNumber).values(voice=False))
        await session.commit()
    agent = await create_agent(client, **TEXT_AGENT)
    conversation = await start(client, agent["id"])

    claimed = await claim(db)
    async with db() as session:
        row = await session.get_one(Conversation, conversation["id"])
        call = await conversations.prepare_call(session, APP_SETTINGS, row, POOL_APP_ID, None)

    assert conversation["transport"] == "text"
    assert claimed == conversation["id"]
    assert call.caller_number is None
    assert call.agent.endpoint is not None


async def test_text_and_phone_conversations_are_claimed_within_their_own_limits(
    client: AsyncClient, db: Db
) -> None:
    agent = await create_agent(client, **TEXT_AGENT)
    conversation = await start(client, agent["id"])

    assert await claim(db, transports=frozenset({Transport.PHONE})) is None
    assert await claim(db, transports=frozenset({Transport.TEXT})) == conversation["id"]
