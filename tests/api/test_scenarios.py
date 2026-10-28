import asyncio
import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from tests.conftest import (
    SCENARIO,
    Db,
    create_agent_id,
    create_persona,
    create_scenario,
    data_sets,
    save_settings,
    wait_for_lock_waiters,
)
from yaksh.db.models import Agent, Scenario, ScenarioVersion


async def test_a_config_change_writes_a_version_but_a_rename_does_not(
    client: AsyncClient,
) -> None:
    scenario = await create_scenario(client, await create_agent_id(client))
    url = f"/api/v1/scenarios/{scenario['id']}"
    assert scenario["current_version"] == 1
    assert scenario["data_sets"][0]["known_facts"] == SCENARIO["data_sets"][0]["known_facts"]

    renamed = await client.patch(url, json={"name": "Move a cleaning"})
    same = await client.patch(url, json={"instructions": SCENARIO["instructions"]})
    changed = await client.patch(url, json={"criteria": ["Offers only evening slots."]})

    assert renamed.json()["current_version"] == same.json()["current_version"] == 1
    assert changed.json()["current_version"] == 2
    assert changed.json()["instructions"] == SCENARIO["instructions"]
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
    await rejected(
        data_sets=data_sets(
            known_facts=[{"name": "Name", "value": "A"}, {"name": "NAME", "value": "B"}]
        )
    )
    await rejected(criteria=["Greets the caller.", "greets  the caller."])
    await rejected(instructions="   ")

    assert both == "a fact cannot be both known and unknown: name"
    assert (await rejected(criteria=[])).startswith("criteria: ")
    missing = await client.post(f"/api/v1/agents/{agent}/scenarios", json={"name": "Only a name"})
    assert missing.json()["error"]["message"] == "instructions: Field required (and 3 more errors)"
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
        client, agent_id, category="messy_input", description="  Wrong date of birth first.  "
    )

    updated = await client.patch(
        f"/api/v1/scenarios/{created['id']}", json={"category": "edge_case", "description": ""}
    )
    refused = await client.patch(f"/api/v1/scenarios/{created['id']}", json={"category": None})

    assert (created["category"], created["description"]) == (
        "messy_input",
        "Wrong date of birth first.",
    )
    assert (updated.json()["category"], updated.json()["description"]) == ("edge_case", None)
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


async def test_data_sets_share_their_names_and_placeholders_name_known_facts(
    client: AsyncClient,
) -> None:
    agent = await create_agent_id(client)
    persona = (await create_persona(client))["id"]
    url = f"/api/v1/agents/{agent}/scenarios"
    moving = {"name": "Austin", "known_facts": [{"name": "Moving to", "value": "Austin, Texas"}]}

    async def refused(**overrides: Any) -> str:
        response = await client.post(
            url, json={**SCENARIO, "persona_id": persona, "data_sets": [moving], **overrides}
        )
        assert response.status_code == 422, response.text
        return response.json()["error"]["message"]

    other_names = await refused(
        data_sets=[moving, {"name": "Denver", "known_facts": [{"name": "City", "value": "Denver"}]}]
    )
    same_name = await refused(data_sets=[moving, {**moving, "name": " austin "}])
    unknown = await refused(criteria=["Reads back {{Destination}}."])
    agent_data = await refused(
        instructions="Ask about {{To_city}}.",
        data_sets=[{**moving, "agent_data": [{"name": "To_city", "value": "Austin"}]}],
    )
    braces = await refused(instructions="Say {{Moving to} twice.")

    assert "must have the same known facts" in other_names
    assert "data set names must be unique" in same_name
    assert "{{Destination}} names no known fact; use one of: Moving to" in unknown
    assert "{{To_city}} names no known fact" in agent_data
    assert "unmatched braces" in braces


async def test_a_scenario_holds_at_most_the_operator_limit_of_data_sets(
    client: AsyncClient, db: Db
) -> None:
    await save_settings(db, {"limits": {"max_scenario_data_sets": 2}})
    agent = await create_agent_id(client)
    sets = [
        {"name": f"Set {n}", "known_facts": [{"name": "Name", "value": f"Caller {n}"}]}
        for n in range(1, 4)
    ]
    persona = (await create_persona(client))["id"]

    three = await client.post(
        f"/api/v1/agents/{agent}/scenarios",
        json={**SCENARIO, "persona_id": persona, "data_sets": sets},
    )
    two = await create_scenario(client, agent, data_sets=sets[:2])
    url = f"/api/v1/scenarios/{two['id']}"
    grown = await client.patch(url, json={"data_sets": [*two["data_sets"], sets[2]]})
    await save_settings(db, {"limits": {"max_scenario_data_sets": 1}})
    kept = await client.patch(url, json={"criteria": ["Greets the caller."]})
    over = await client.post(f"{url}/fork")
    one = await client.post(f"{url}/fork", json={"data_set_ids": [two["data_sets"][0]["id"]]})
    shrunk = await client.patch(url, json={"data_sets": two["data_sets"][:1]})

    assert three.status_code == 422 and "at most 2 data sets" in three.text
    assert over.status_code == 422 and "at most 1 data set" in over.text
    assert one.status_code == 201, one.text
    assert grown.status_code == 422 and "at most 2 data sets" in grown.text
    assert shrunk.status_code == 200, shrunk.text
    assert kept.status_code == 200, kept.text


async def test_interruptions_get_their_default_wait_and_a_change_writes_a_version(
    client: AsyncClient,
) -> None:
    lines = [
        {"say": "Sorry, is there a fee for that?", "agent_says": "first visit"},
        {"say": "Sorry, can you repeat that?"},
        {"say": "Hold on.", "agent_says": "your total", "after_s": 0.5},
    ]
    scenario = await create_scenario(client, await create_agent_id(client), interruptions=lines)
    url = f"/api/v1/scenarios/{scenario['id']}"

    same = await client.patch(url, json={"interruptions": scenario["interruptions"]})
    changed = await client.patch(url, json={"interruptions": lines[:1]})
    cleared = await client.patch(url, json={"interruptions": []})

    assert [(item["after_s"], item["from_answer"]) for item in scenario["interruptions"]] == [
        (0.0, 1),
        (2.0, 2),
        (0.5, 1),
    ]
    assert scenario["interruptions"][1] == {
        "say": "Sorry, can you repeat that?",
        "agent_says": None,
        "after_s": 2.0,
        "from_answer": 2,
    }
    assert same.json()["current_version"] == 1
    assert changed.json()["current_version"] == 2
    assert cleared.json()["interruptions"] == [] and cleared.json()["current_version"] == 3
    first = (await client.get(f"{url}/versions/1")).json()
    assert [item["say"] for item in first["config"]["interruptions"]] == [
        "Sorry, is there a fee for that?",
        "Sorry, can you repeat that?",
        "Hold on.",
    ]


async def test_interruptions_are_checked_like_the_rest_of_the_scenario(
    client: AsyncClient,
) -> None:
    agent = await create_agent_id(client)
    persona = (await create_persona(client))["id"]
    url = f"/api/v1/agents/{agent}/scenarios"

    async def refused(*interruptions: dict[str, Any], **fields: Any) -> str:
        response = await client.post(
            url,
            json={
                **SCENARIO,
                "persona_id": persona,
                "interruptions": list(interruptions),
                **fields,
            },
        )
        assert response.status_code == 422, response.text
        return response.json()["error"]["message"]

    too_many = await refused(*({"say": f"Line {n}."} for n in range(4)))
    unknown_fact = await refused({"say": "My name is {{Full name}}."})
    unknown_in_phrase = await refused({"say": "Wait.", "agent_says": "{{Card}}"})
    no_word = await refused({"say": "Wait.", "agent_says": "..."})
    no_canonical_word = await refused({"say": "Wait.", "agent_says": "½"})
    long_line = await refused({"say": "x" * 190 + " {{Name}}"})
    long_phrase = await refused({"say": "Wait.", "agent_says": "x" * 190 + " {{Name}}"})
    second_set_long = await refused(
        {"say": "x" * 185 + " {{Name}}"},
        data_sets=[
            {"name": "Short", "known_facts": [{"name": "Name", "value": "Priya"}]},
            {"name": "Long", "known_facts": [{"name": "Name", "value": "Priyadarshini Raman"}]},
        ],
    )
    turn = await refused({"say": "Wait.", "from_answer": 0})
    empty = await refused({"say": "  "})
    scenario = await create_scenario(client, agent)
    cleared = await client.patch(
        f"/api/v1/scenarios/{scenario['id']}", json={"interruptions": None}
    )

    assert "at most 3" in too_many
    assert "{{Full name}} names no known fact" in unknown_fact
    assert "{{Card}} names no known fact" in unknown_in_phrase
    assert "a phrase needs at least one word or number" in no_word
    assert "a phrase needs at least one word or number" in no_canonical_word
    too_long = "of interruption 1 is longer than 200 characters with the facts of the data set"
    assert f'the line {too_long} "Data set 1"' in long_line
    assert f'the phrase {too_long} "Data set 1"' in long_phrase
    assert f'the line {too_long} "Long"' in second_set_long
    assert "from_answer" in turn and "say" in empty
    assert cleared.status_code == 422 and "interruptions cannot be null" in cleared.text


async def test_a_scenario_without_interruptions_is_stored_as_older_versions_read_it(
    client: AsyncClient, db: Db
) -> None:
    agent = await create_agent_id(client)
    plain = await create_scenario(client, agent)
    with_lines = await create_scenario(
        client, agent, name="With lines", interruptions=[{"say": "Wait."}]
    )
    await client.patch(f"/api/v1/scenarios/{plain['id']}", json={"criteria": ["Says goodbye."]})
    ids = [uuid.UUID(plain["id"]), uuid.UUID(with_lines["id"])]

    async with db() as session:
        versions = await session.execute(
            select(
                ScenarioVersion.scenario_id, ScenarioVersion.version, ScenarioVersion.config
            ).where(ScenarioVersion.scenario_id.in_(ids))
        )
        scenarios = await session.execute(
            select(Scenario.id, Scenario.config).where(Scenario.id.in_(ids))
        )

    stored = {(str(id_), number): "interruptions" in config for id_, number, config in versions}
    assert stored == {
        (plain["id"], 1): False,
        (plain["id"], 2): False,
        (with_lines["id"], 1): True,
    }
    assert {str(id_): "interruptions" in config for id_, config in scenarios} == {
        plain["id"]: False,
        with_lines["id"]: True,
    }
