from typing import Any

import pytest
from httpx import AsyncClient

from tests.conftest import AGENT, OUTBOUND_AGENT, SCENARIO, create_agent, create_scenario

TRIGGER = OUTBOUND_AGENT["outbound"]["trigger"]


def with_trigger(**changes: Any) -> dict[str, Any]:
    return {**OUTBOUND_AGENT, "outbound": {"trigger": {**TRIGGER, **changes}}}


async def test_each_version_of_an_outbound_agent_keeps_its_own_trigger(
    client: AsyncClient,
) -> None:
    agent = await create_agent(client, **OUTBOUND_AGENT)
    url = f"/api/v1/agents/{agent['id']}"
    new_body = {"to": "{{truman.number}}", "campaign": "renewals"}

    changed = await client.patch(url, json=with_trigger(body=new_body))
    versions = (await client.get(f"{url}/versions")).json()["items"]

    assert agent["agent_number"] is None and agent["outbound"]["dial_window_s"] == 120
    assert changed.json()["current_version"] == 2
    assert [v["config"]["outbound"]["trigger"]["body"] for v in versions] == [
        new_body,
        TRIGGER["body"],
    ]


@pytest.mark.parametrize(
    "body",
    [
        {**OUTBOUND_AGENT, "outbound": None},
        {**OUTBOUND_AGENT, "agent_number": "+14155550100"},
        {**AGENT, "outbound": OUTBOUND_AGENT["outbound"]},
        {"name": "No number"},
    ],
    ids=["outbound without trigger", "outbound with number", "inbound with trigger", "no number"],
)
async def test_the_direction_decides_which_settings_an_agent_needs(
    client: AsyncClient, body: dict[str, Any]
) -> None:
    response = await client.post("/api/v1/agents", json=body)

    assert response.status_code == 422, response.text


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"body": {"to": "{{truman.phone}}"}}, "unknown placeholder"),
        ({"body": {"to": "{{env.OPENAI_API_KEY}}"}}, "TRUMAN_TRIGGER_"),
        ({"body": {"to": "{{env.TRUMAN_WEBHOOK_SIGNING_KEY}}"}}, "TRUMAN_TRIGGER_"),
        ({"body": {"to": "{{truman.number}"}}, "unmatched braces"),
        ({"body": {"{{truman.number}}": "x"}}, "JSON keys"),
        ({"url": "https://example.com/{{truman.number}}"}, "URL"),
        ({"headers": [{"name": "X-Key", "value": "a\r\nb"}]}, "line break"),
        ({"headers": [{"name": "Content-Type", "value": "text/plain"}]}, "sets the"),
        ({"headers": [{"name": "X-Truman-Delivery", "value": "x"}]}, "sets the"),
        ({"headers": [{"name": "A", "value": "1"}, {"name": "a", "value": "2"}]}, "unique"),
        ({"url": "ftp://example.com/calls"}, "url"),
    ],
)
async def test_a_trigger_is_checked_when_the_agent_is_saved(
    client: AsyncClient, changes: dict[str, Any], reason: str
) -> None:
    response = await client.post("/api/v1/agents", json=with_trigger(**changes))

    assert response.status_code == 422
    assert reason in response.text


async def test_an_inbound_agent_can_become_outbound(client: AsyncClient) -> None:
    agent = await create_agent(client)
    url = f"/api/v1/agents/{agent['id']}"

    half = await client.patch(url, json={"direction": "outbound"})
    switched = await client.patch(
        url,
        json={
            "direction": "outbound",
            "agent_number": None,
            "outbound": OUTBOUND_AGENT["outbound"],
        },
    )

    assert half.status_code == 422 and "outbound settings" in half.text
    assert switched.status_code == 200 and switched.json()["current_version"] == 2
    assert switched.json()["agent_number"] is None


async def test_a_scenario_keeps_agent_data_with_distinct_names(client: AsyncClient) -> None:
    agent = await create_agent(client, **OUTBOUND_AGENT)
    agent_data = [{"name": "Customer name", "value": "Priya Raman"}]

    scenario = await create_scenario(client, agent["id"], agent_data=agent_data)
    duplicated = await client.post(
        f"/api/v1/agents/{agent['id']}/scenarios",
        json={
            **SCENARIO,
            "name": "Twice",
            "agent_data": agent_data * 2,
            "persona_id": scenario["persona_id"],
        },
    )

    assert scenario["agent_data"] == agent_data
    assert duplicated.status_code == 422 and "agent data names" in duplicated.text
