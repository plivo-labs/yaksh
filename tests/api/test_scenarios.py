import asyncio
import uuid
from typing import Any

import pytest
from httpx import AsyncClient

from tests.conftest import (
    SCENARIO,
    Db,
    create_agent_id,
    create_persona,
    create_scenario,
    wait_for_lock_waiters,
)
from yaksha.db.models import Agent


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
        f"/api/v1/agents/{agent}/scenarios",
        json={**SCENARIO, "name": "reschedule a CLEANING", "persona_id": first["persona_id"]},
    )
    await create_scenario(client, other)
    await client.delete(f"/api/v1/scenarios/{first['id']}")
    await create_scenario(client, agent)

    assert taken.status_code == 409 and taken.json()["error"]["code"] == "conflict"


async def test_facts_and_criteria_must_be_distinct_after_normalization(
    client: AsyncClient,
) -> None:
    agent = await create_agent_id(client)
    persona = (await create_persona(client))["id"]

    async def rejected(**overrides: Any) -> str:
        response = await client.post(
            f"/api/v1/agents/{agent}/scenarios",
            json={**SCENARIO, "persona_id": persona, **overrides},
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
    assert missing.json()["error"]["message"] == "goal: Field required (and 2 more errors)"
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
    created = await client.post(
        f"/api/v1/agents/{agent}/scenarios",
        json={**SCENARIO, "persona_id": scenario["persona_id"]},
    )
    assert created.status_code == 404


async def test_a_missing_agent_cannot_have_or_list_scenarios(client: AsyncClient) -> None:
    url = f"/api/v1/agents/{uuid.uuid4()}/scenarios"
    persona = (await create_persona(client))["id"]

    assert (await client.post(url, json={**SCENARIO, "persona_id": persona})).status_code == 404
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


async def test_category_and_description_change_without_a_new_version(
    client: AsyncClient,
) -> None:
    agent_id = await create_agent_id(client)
    created = await create_scenario(
        client, agent_id, category="recovery", description="  Wrong date of birth first.  "
    )

    updated = await client.patch(
        f"/api/v1/scenarios/{created['id']}", json={"category": "boundary", "description": ""}
    )
    refused = await client.patch(f"/api/v1/scenarios/{created['id']}", json={"category": None})

    assert (created["category"], created["description"]) == (
        "recovery",
        "Wrong date of birth first.",
    )
    assert (updated.json()["category"], updated.json()["description"]) == ("boundary", None)
    assert updated.json()["current_version"] == 1
    assert refused.status_code == 422


async def test_a_scenario_runs_with_a_persona_that_changes_without_a_new_version(
    client: AsyncClient,
) -> None:
    agent = await create_agent_id(client)
    first = (await create_persona(client))["id"]
    second = (await create_persona(client, name="Calm caller"))["id"]
    gone = (await create_persona(client, name="Gone caller"))["id"]
    await client.delete(f"/api/v1/personas/{gone}")
    scenario = await create_scenario(client, agent, persona_id=first)
    url = f"/api/v1/scenarios/{scenario['id']}"
    create = f"/api/v1/agents/{agent}/scenarios"

    moved = await client.patch(url, json={"persona_id": second})
    cleared = await client.patch(url, json={"persona_id": None})
    unknown = await client.patch(url, json={"persona_id": str(uuid.uuid4())})
    with_gone = await client.post(create, json={**SCENARIO, "name": "Other", "persona_id": gone})
    without = await client.post(create, json={**SCENARIO, "name": "Other"})

    assert scenario["persona_id"] == first
    assert moved.status_code == 200 and moved.json()["persona_id"] == second
    assert moved.json()["current_version"] == 1
    assert cleared.status_code == 422
    assert unknown.status_code == 404
    assert (await client.get(url)).json()["persona_id"] == second
    assert with_gone.status_code == 404
    assert without.status_code == 422 and "persona_id" in without.text


async def test_set_persona_changes_every_selected_scenario_or_none(client: AsyncClient) -> None:
    agent, other = await create_agent_id(client), await create_agent_id(client, name="Other")
    one = await create_scenario(client, agent)
    two = await create_scenario(client, agent, name="Cancel a cleaning")
    foreign = await create_scenario(client, other)
    target = (await create_persona(client, name="Calm caller"))["id"]
    url = f"/api/v1/agents/{agent}/scenarios/persona"

    with_foreign = await client.post(
        url, json={"scenario_ids": [one["id"], foreign["id"]], "persona_id": target}
    )
    unknown_persona = await client.post(
        url, json={"scenario_ids": [one["id"]], "persona_id": str(uuid.uuid4())}
    )
    untouched = [
        (await client.get(f"/api/v1/scenarios/{s['id']}")).json()["persona_id"] for s in (one, two)
    ]
    done = await client.post(
        url, json={"scenario_ids": [one["id"], two["id"]], "persona_id": target}
    )
    after = [(await client.get(f"/api/v1/scenarios/{s['id']}")).json() for s in (one, two)]

    assert with_foreign.status_code == 404 and unknown_persona.status_code == 404
    assert untouched == [one["persona_id"], two["persona_id"]]
    assert done.status_code == 204
    assert [(s["persona_id"], s["current_version"]) for s in after] == [(target, 1), (target, 1)]


@pytest.mark.parametrize("action", ["delete", "persona"])
async def test_a_bulk_change_waits_while_the_agent_is_locked(
    client: AsyncClient, db: Db, action: str
) -> None:
    agent = await create_agent_id(client)
    scenario = await create_scenario(client, agent)
    body: dict[str, Any] = {"scenario_ids": [scenario["id"]]}
    if action == "persona":
        body["persona_id"] = (await create_persona(client, name="Calm caller"))["id"]

    async with db() as other:
        await other.get_one(Agent, uuid.UUID(agent), with_for_update=True)
        changing = asyncio.create_task(
            client.post(f"/api/v1/agents/{agent}/scenarios/{action}", json=body)
        )
        await wait_for_lock_waiters(db, 1)
        await other.rollback()
    response = await changing

    assert response.status_code == 204
