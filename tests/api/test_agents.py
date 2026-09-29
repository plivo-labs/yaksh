import asyncio
import uuid

import pytest
from httpx import AsyncClient
from pydantic import ValidationError

from tests.conftest import AGENT, SCENARIO, create_agent, create_scenario
from truman.config import Settings


async def test_changing_config_creates_a_version_but_renaming_does_not(
    client: AsyncClient,
) -> None:
    agent = await create_agent(client)
    url = f"/api/v1/agents/{agent['id']}"
    assert agent["current_version"] == 1 and agent["language"] == "en"

    renamed = await client.patch(url, json={"name": "Reception"})
    assert renamed.json()["current_version"] == 1

    changed = await client.patch(url, json={"agent_speaks_first": False, "brief": "Books rooms"})
    assert changed.json()["current_version"] == 2

    unchanged = await client.patch(url, json={"agent_speaks_first": False})
    assert unchanged.json()["current_version"] == 2

    relanguaged = await client.patch(url, json={"language": "hinglish"})
    assert relanguaged.json()["current_version"] == 3

    versions = (await client.get(f"{url}/versions")).json()
    assert [v["version"] for v in versions["items"]] == [3, 2, 1]
    assert versions["items"][0]["config"]["language"] == "hinglish"
    assert versions["items"][1]["config"]["brief"] == "Books rooms"


async def test_new_records_get_time_ordered_ids(client: AsyncClient) -> None:
    first = await create_agent(client)
    second = await create_agent(client)
    versions = (await client.get(f"/api/v1/agents/{second['id']}/versions")).json()
    ids = [uuid.UUID(first["id"]), uuid.UUID(second["id"]), uuid.UUID(versions["items"][0]["id"])]

    assert [i.version for i in ids] == [7, 7, 7]
    assert ids[0] < ids[1]


async def test_invalid_updates_are_rejected_before_the_database(client: AsyncClient) -> None:
    created = await client.post("/api/v1/agents", json={"name": "No number"})
    assert created.status_code == 422
    assert created.json()["error"]["code"] == "validation_error"
    assert created.json()["error"]["details"][0]["loc"][-1] == "agent_number"

    agent = await create_agent(client)
    url = f"/api/v1/agents/{agent['id']}"
    assert (await client.patch(url, json={"agent_number": None})).status_code == 422
    assert (await client.patch(url, json={"agent_number": "4155550100"})).status_code == 422
    assert (await client.patch(url, json={"name": None})).status_code == 422
    assert (await client.patch(url, json={"language": None})).status_code == 422
    assert (await client.patch(url, json={"language": "klingon"})).status_code == 422

    moved = await client.patch(url, json={"agent_number": "+14155550199"})
    assert moved.status_code == 200 and moved.json()["agent_number"] == "+14155550199"


async def test_external_id_is_unique_among_live_agents(client: AsyncClient) -> None:
    first = await create_agent(client, external_id="flow-42")

    duplicate = await client.post("/api/v1/agents", json={**AGENT, "external_id": "flow-42"})
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "conflict"

    assert (await client.delete(f"/api/v1/agents/{first['id']}")).status_code == 204
    assert (await client.get(f"/api/v1/agents/{first['id']}")).status_code == 404
    assert (await client.get(f"/api/v1/agents/{first['id']}/versions/1")).status_code == 200

    reused = await create_agent(client, external_id="flow-42")
    listed = (await client.get("/api/v1/agents", params={"external_id": "flow-42"})).json()
    assert [item["id"] for item in listed["items"]] == [reused["id"]]


async def test_concurrent_edits_get_distinct_versions(client: AsyncClient) -> None:
    agent = await create_agent(client)
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


async def test_a_duplicate_copies_the_config_and_live_scenarios_but_not_the_external_id(
    client: AsyncClient,
) -> None:
    original = await create_agent(client, external_id="flow-7", brief="Books rooms")
    kept = await create_scenario(client, original["id"])
    gone = await create_scenario(client, original["id"], name="Gone")
    await client.delete(f"/api/v1/scenarios/{gone['id']}")
    await client.patch(f"/api/v1/scenarios/{kept['id']}", json={"criteria": ["Books it."]})

    response = await client.post(f"/api/v1/agents/{original['id']}/duplicate")

    assert response.status_code == 201
    copy = response.json()
    assert copy["id"] != original["id"] and copy["name"] == f"{AGENT['name']} (copy)"
    assert (copy["external_id"], copy["brief"], copy["current_version"]) == (None, "Books rooms", 1)
    copied = (await client.get(f"/api/v1/agents/{copy['id']}/scenarios")).json()["items"]
    assert [(s["name"], s["criteria"], s["current_version"]) for s in copied] == [
        (SCENARIO["name"], ["Books it."], 1)
    ]
    assert (await client.get(f"/api/v1/agents/{original['id']}/scenarios")).json()["total"] == 1
    missing = await client.post(f"/api/v1/agents/{uuid.uuid4()}/duplicate")
    assert missing.status_code == 404


async def test_search_matches_name_number_external_id_and_id(client: AsyncClient) -> None:
    desk = await create_agent(client, name="Front desk", external_id="flow-42")
    pizza = await create_agent(client, name="Pizza orders", agent_number="+912245550199")
    await create_agent(client, name="100% uptime line", agent_number="+14155550111")

    async def found(q: str) -> list[str]:
        response = await client.get("/api/v1/agents", params={"q": q})
        return sorted(agent["name"] for agent in response.json()["items"])

    assert await found("FRONT") == ["Front desk"]
    assert await found("22 4555") == ["Pizza orders"]
    assert await found("flow-4") == ["Front desk"]
    assert await found(pizza["id"][-8:]) == ["Pizza orders"]
    assert await found("%") == ["100% uptime line"]
    assert await found("nothing like it") == []
    assert desk["id"] in [a["id"] for a in (await client.get("/api/v1/agents")).json()["items"]]


async def test_the_list_sorts_by_name_and_by_last_update(client: AsyncClient) -> None:
    bravo = await create_agent(client, name="bravo")
    await create_agent(client, name="Alpha")
    await create_agent(client, name="charlie")
    await client.patch(f"/api/v1/agents/{bravo['id']}", json={"brief": "touched"})

    async def names(sort: str) -> list[str]:
        response = await client.get("/api/v1/agents", params={"sort": sort})
        return [agent["name"] for agent in response.json()["items"]]

    assert await names("name") == ["Alpha", "bravo", "charlie"]
    assert await names("-name") == ["charlie", "bravo", "Alpha"]
    assert (await names("-updated_at"))[0] == "bravo"
    invalid = await client.get("/api/v1/agents", params={"sort": "agent_number"})
    assert invalid.status_code == 422
