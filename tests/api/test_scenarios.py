import uuid
from typing import Any

from httpx import AsyncClient

from tests.conftest import create_agent_id

SCENARIO: dict[str, Any] = {
    "name": "Reschedule a cleaning",
    "goal": "Move your cleaning to an evening next week; if none is free, keep the current one.",
    "known_facts": [
        {"name": "Name", "value": "Priya Raman"},
        {"name": "Current appointment", "value": "next Thursday, 10:30 am"},
    ],
    "unknown_facts": ["Patient ID"],
    "criteria": ["Reads the new date and time back before it moves the appointment."],
}


async def create_scenario(client: AsyncClient, agent_id: str, **overrides: Any) -> dict[str, Any]:
    response = await client.post(
        f"/api/v1/agents/{agent_id}/scenarios", json={**SCENARIO, **overrides}
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_a_config_change_writes_a_version_but_a_rename_does_not(
    client: AsyncClient,
) -> None:
    scenario = await create_scenario(client, await create_agent_id(client))
    url = f"/api/v1/scenarios/{scenario['id']}"
    assert scenario["current_version"] == 1
    assert scenario["known_facts"] == SCENARIO["known_facts"]

    renamed = await client.patch(url, json={"name": "Move a cleaning"})
    same = await client.patch(url, json={"goal": SCENARIO["goal"]})
    changed = await client.patch(url, json={"criteria": ["Offers only evening slots."]})

    assert renamed.json()["current_version"] == same.json()["current_version"] == 1
    assert changed.json()["current_version"] == 2
    assert changed.json()["goal"] == SCENARIO["goal"]
    versions = (await client.get(f"{url}/versions")).json()["items"]
    assert [v["version"] for v in versions] == [2, 1]
    first = (await client.get(f"{url}/versions/1")).json()
    assert first["config"]["criteria"] == SCENARIO["criteria"]


async def test_names_are_unique_per_agent_among_live_scenarios(client: AsyncClient) -> None:
    agent, other = await create_agent_id(client), await create_agent_id(client, name="Other")
    first = await create_scenario(client, agent)

    taken = await client.post(
        f"/api/v1/agents/{agent}/scenarios", json={**SCENARIO, "name": "reschedule a CLEANING"}
    )
    await create_scenario(client, other)
    await client.delete(f"/api/v1/scenarios/{first['id']}")
    await create_scenario(client, agent)

    assert taken.status_code == 409 and taken.json()["error"]["code"] == "conflict"


async def test_facts_and_criteria_must_be_distinct_after_normalization(
    client: AsyncClient,
) -> None:
    agent = await create_agent_id(client)

    async def rejected(**overrides: Any) -> str:
        response = await client.post(
            f"/api/v1/agents/{agent}/scenarios", json={**SCENARIO, **overrides}
        )
        assert response.status_code == 422, response.text
        return response.json()["error"]["message"]

    both = await rejected(unknown_facts=["  name "])
    await rejected(known_facts=[{"name": "Name", "value": "A"}, {"name": "NAME", "value": "B"}])
    await rejected(criteria=["Greets the caller.", "greets  the caller."])
    await rejected(goal="   ")

    assert both == "a fact cannot be both known and unknown: name"
    assert (await rejected(criteria=[])).startswith("criteria: ")
    missing = await client.post(f"/api/v1/agents/{agent}/scenarios", json={"name": "Only a name"})
    assert missing.json()["error"]["message"] == "goal: Field required (and 1 more errors)"
    assert (await client.get(f"/api/v1/agents/{agent}/scenarios")).json()["total"] == 0


async def test_a_deleted_scenario_is_gone_but_its_versions_remain(client: AsyncClient) -> None:
    scenario = await create_scenario(client, await create_agent_id(client))
    url = f"/api/v1/scenarios/{scenario['id']}"

    assert (await client.delete(url)).status_code == 204

    assert (await client.get(url)).status_code == 404
    assert (await client.patch(url, json={"name": "Back"})).status_code == 404
    assert (await client.get(f"{url}/versions")).json()["total"] == 1
    listed = await client.get(f"/api/v1/agents/{scenario['agent_id']}/scenarios")
    assert listed.json()["total"] == 0


async def test_deleting_an_agent_deletes_its_scenarios(client: AsyncClient) -> None:
    agent = await create_agent_id(client)
    scenario = await create_scenario(client, agent)

    assert (await client.delete(f"/api/v1/agents/{agent}")).status_code == 204

    assert (await client.get(f"/api/v1/scenarios/{scenario['id']}")).status_code == 404
    assert (await client.get(f"/api/v1/agents/{agent}/scenarios")).status_code == 404
    created = await client.post(f"/api/v1/agents/{agent}/scenarios", json=SCENARIO)
    assert created.status_code == 404


async def test_a_missing_agent_cannot_have_or_list_scenarios(client: AsyncClient) -> None:
    url = f"/api/v1/agents/{uuid.uuid4()}/scenarios"

    assert (await client.post(url, json=SCENARIO)).status_code == 404
    assert (await client.get(url)).status_code == 404


async def test_an_update_keeps_names_unique_and_facts_distinct(client: AsyncClient) -> None:
    agent = await create_agent_id(client)
    await create_scenario(client, agent)
    other = await create_scenario(client, agent, name="Cancel a cleaning")
    url = f"/api/v1/scenarios/{other['id']}"

    taken = await client.patch(url, json={"name": "RESCHEDULE a cleaning"})
    overlap = await client.patch(url, json={"unknown_facts": ["name"]})
    emptied = await client.patch(url, json={"criteria": []})

    assert taken.status_code == 409
    assert overlap.status_code == 422 and "both known and unknown" in overlap.text
    assert emptied.status_code == 422 and "criteria" in emptied.text
