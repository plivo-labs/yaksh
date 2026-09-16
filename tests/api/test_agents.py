import asyncio
from typing import Any

import pytest
from httpx import AsyncClient
from pydantic import ValidationError

from truman.config import Settings

AGENT = {"name": "Front desk", "websocket_url": "wss://agent.example.com/stream"}


async def create(client: AsyncClient, **overrides: Any) -> dict[str, Any]:
    response = await client.post("/api/v1/agents", json={**AGENT, **overrides})
    assert response.status_code == 201, response.text
    return response.json()


async def test_changing_config_creates_a_version_but_renaming_does_not(
    client: AsyncClient,
) -> None:
    agent = await create(client)
    url = f"/api/v1/agents/{agent['id']}"
    assert agent["current_version"] == 1

    renamed = await client.patch(url, json={"name": "Reception"})
    assert renamed.json()["current_version"] == 1

    changed = await client.patch(url, json={"agent_speaks_first": False, "brief": "Books rooms"})
    assert changed.json()["current_version"] == 2

    unchanged = await client.patch(url, json={"agent_speaks_first": False})
    assert unchanged.json()["current_version"] == 2

    versions = (await client.get(f"{url}/versions")).json()
    assert [(v["version"], v["change"]) for v in versions["items"]] == [
        (2, "changed"),
        (1, "created"),
    ]
    assert versions["items"][0]["config"]["brief"] == "Books rooms"


async def test_invalid_updates_are_rejected_before_the_database(client: AsyncClient) -> None:
    created = await client.post("/api/v1/agents", json={"name": "No url"})
    assert created.status_code == 422
    assert created.json()["error"]["code"] == "validation_error"

    agent = await create(client)
    url = f"/api/v1/agents/{agent['id']}"
    assert (await client.patch(url, json={"websocket_url": None})).status_code == 422
    assert (await client.patch(url, json={"name": None})).status_code == 422

    phone = await client.patch(
        url, json={"transport": "phone", "websocket_url": None, "agent_number": "+14155550100"}
    )
    assert phone.status_code == 200, phone.text


async def test_external_id_is_unique_among_live_agents(client: AsyncClient) -> None:
    first = await create(client, external_id="flow-42")

    duplicate = await client.post("/api/v1/agents", json={**AGENT, "external_id": "flow-42"})
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "conflict"

    assert (await client.delete(f"/api/v1/agents/{first['id']}")).status_code == 204
    assert (await client.get(f"/api/v1/agents/{first['id']}")).status_code == 404
    assert (await client.get(f"/api/v1/agents/{first['id']}/versions/1")).status_code == 200

    reused = await create(client, external_id="flow-42")
    listed = (await client.get("/api/v1/agents", params={"external_id": "flow-42"})).json()
    assert [item["id"] for item in listed["items"]] == [reused["id"]]


async def test_concurrent_edits_get_distinct_versions(client: AsyncClient) -> None:
    agent = await create(client)
    url = f"/api/v1/agents/{agent['id']}"

    responses = await asyncio.gather(
        *(client.patch(url, json={"brief": f"brief {n}"}) for n in range(5))
    )

    assert [response.json()["brief"] for response in responses] == [f"brief {n}" for n in range(5)]
    versions = (await client.get(f"{url}/versions", params={"page_size": 10})).json()
    assert [item["version"] for item in versions["items"]] == [6, 5, 4, 3, 2, 1]
    assert (await client.get(url)).json()["current_version"] == 6


async def test_requests_without_a_valid_token_are_rejected(client: AsyncClient) -> None:
    missing = await client.get("/api/v1/agents", headers={"Authorization": ""})
    wrong = await client.get("/api/v1/agents", headers={"Authorization": "Bearer nope"})

    assert missing.status_code == 401 and wrong.status_code == 401
    assert wrong.json() == {
        "error": {"code": "unauthorized", "message": "missing or invalid bearer token"}
    }
    assert wrong.headers["www-authenticate"] == "Bearer"


def test_an_empty_token_is_refused_at_startup() -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate(
            {"api_token": "", "database_url": "postgresql+asyncpg://truman:truman@db/truman"}
        )
