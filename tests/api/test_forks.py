import asyncio
import json
import uuid
from typing import Any

import pytest
from httpx import AsyncClient

from tests.conftest import (
    HINDI_VOICE,
    Db,
    FakeJsonModel,
    FakeProviders,
    create_agent_id,
    create_persona,
    create_scenario,
    data_sets,
    save_settings,
)
from yaksh.domain.forks import ForkRequest
from yaksh.domain.surroundings import NoiseSound, Sound, Speaker, SpeakerKind, Surroundings
from yaksh.simulation import forks, personas

FORKED_FIELDS = (
    "category",
    "description",
    "persona_id",
    "instructions",
    "unknown_facts",
    "criteria",
    "data_sets",
    "first_words",
    "caller",
)


async def test_a_scenario_fork_copies_every_field_under_a_free_name(client: AsyncClient) -> None:
    agent_id = await create_agent_id(client)
    original = await create_scenario(
        client,
        agent_id,
        name="Moves the cleaning",
        category="messy_input",
        description="Checks a corrected date.",
        data_sets=data_sets(known_facts=[{"name": "Date of birth", "value": "4 May 1990"}]),
        unknown_facts=["Patient ID"],
        first_words="Hi, it's about my cleaning.",
        caller={"model": "gpt-6-astra", "reasoning_effort": "low"},
    )

    first = await client.post(f"/api/v1/scenarios/{original['id']}/fork")
    second = await client.post(f"/api/v1/scenarios/{original['id']}/fork")
    missing = await client.post(f"/api/v1/scenarios/{uuid.uuid4()}/fork")

    assert first.status_code == second.status_code == 201, first.text
    fork = first.json()
    assert (fork["name"], second.json()["name"]) == (
        "Moves the cleaning (fork)",
        "Moves the cleaning (fork) (2)",
    )
    assert (fork["agent_id"], fork["forked_from_id"], fork["current_version"]) == (
        agent_id,
        original["id"],
        1,
    )
    assert {key: fork[key] for key in FORKED_FIELDS} == {
        key: original[key] for key in FORKED_FIELDS
    }
    assert missing.status_code == 404


async def test_a_long_name_keeps_its_fork_suffix_within_the_limit(client: AsyncClient) -> None:
    agent_id = await create_agent_id(client)
    original = await create_scenario(client, agent_id, name="n" * 80)

    fork = (await client.post(f"/api/v1/scenarios/{original['id']}/fork")).json()

    assert fork["name"] == "n" * 73 + " (fork)"


async def test_a_scenario_is_created_as_a_fork_only_of_its_own_agent(client: AsyncClient) -> None:
    mine = await create_agent_id(client, name="Mine")
    theirs = await create_agent_id(client, name="Theirs")
    original = await create_scenario(client, theirs)

    refused = await client.post(
        f"/api/v1/agents/{mine}/scenarios",
        json={
            "name": "Copy",
            "persona_id": original["persona_id"],
            "instructions": original["instructions"],
            "criteria": original["criteria"],
            "data_sets": original["data_sets"],
            "forked_from_id": original["id"],
        },
    )

    assert refused.status_code == 422, refused.text


async def test_a_persona_fork_copies_its_settings_but_not_the_built_in_mark(
    client: AsyncClient,
) -> None:
    original = await create_persona(
        client, name="Busy parent", language="hi", sample_line="Haan, bolo?"
    )

    response = await client.post(f"/api/v1/personas/{original['id']}/fork")

    assert response.status_code == 201, response.text
    fork = response.json()
    assert (fork["name"], fork["forked_from_id"], fork["builtin_key"]) == (
        "Busy parent (fork)",
        original["id"],
        None,
    )
    settings = ("prompt", "language", "voice", "voice_gender", "surroundings", "sample_line")
    assert {key: fork[key] for key in settings} == {key: original[key] for key in settings}


def events_of(body: str) -> list[tuple[str, dict[str, Any]]]:
    events = []
    for block in body.strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        events.append((fields["event"], json.loads(fields["data"])))
    return events


def moved_to(prompt: str) -> dict[str, Any]:
    """A fork that moves the destination named in the change, in each data set it was given."""
    scenario, city = prompt.split("## Scenario\n", 1)[1].split("\n\n## Change\n", 1)
    given = json.loads(scenario)["data_sets"]
    return {
        "name": f"Moves to {city.strip()}",
        "description": f"Tests a move to {city.strip()}.",
        "instructions": "Confirm the move when the agent reads it back.",
        "unknown_facts": [],
        "criteria": [f"Reads back the move to {city.strip()}."],
        "data_sets": [
            {"known_facts": item["known_facts"], "agent_data": item["agent_data"]} for item in given
        ],
    }


async def test_scenario_forks_stream_as_drafts_and_nothing_is_saved(
    client: AsyncClient, generation_model: FakeJsonModel
) -> None:
    agent_id = await create_agent_id(client)
    original = await create_scenario(
        client,
        agent_id,
        category="edge_case",
        first_words="Hello?",
        caller={"model": "gpt-6-astra", "reasoning_effort": "low"},
    )
    generation_model.changes = ["Madrid", "Shanghai", "madrid"]
    generation_model.write = moved_to

    response = await client.post(
        f"/api/v1/scenarios/{original['id']}/forks/draft",
        json={"instruction": "Moves to Madrid and Shanghai", "count": 5},
    )
    listed = (await client.get(f"/api/v1/agents/{agent_id}/scenarios")).json()["total"]

    events = events_of(response.text)
    drafts = [data for kind, data in events if kind == "fork"]
    assert events[0] == ("planned", {"count": 2}), "a repeated change is one fork"
    assert sorted(draft["name"] for draft in drafts) == ["Moves to Madrid", "Moves to Shanghai"]
    assert {
        (d["category"], d["persona_id"], d["first_words"], d["forked_from_id"]) for d in drafts
    } == {("edge_case", original["persona_id"], "Hello?", original["id"])}
    assert all(d["caller"] == original["caller"] for d in drafts)
    assert listed == 1


async def test_a_saved_scenario_fork_links_to_its_original(
    client: AsyncClient, generation_model: FakeJsonModel
) -> None:
    agent_id = await create_agent_id(client)
    original = await create_scenario(client, agent_id)
    generation_model.changes = ["Madrid"]
    generation_model.write = moved_to
    response = await client.post(
        f"/api/v1/scenarios/{original['id']}/forks/draft",
        json={"instruction": "Moves to Madrid", "count": 1},
    )
    draft = next(data for kind, data in events_of(response.text) if kind == "fork")

    saved = await client.post(f"/api/v1/agents/{agent_id}/scenarios", json=draft)

    assert saved.status_code == 201, saved.text
    assert saved.json()["forked_from_id"] == original["id"]


async def test_an_instruction_with_nothing_to_change_plans_no_forks(
    client: AsyncClient, generation_model: FakeJsonModel
) -> None:
    original = await create_scenario(client, await create_agent_id(client))

    response = await client.post(
        f"/api/v1/scenarios/{original['id']}/forks/draft",
        json={"instruction": "make it different", "count": 3},
    )

    assert events_of(response.text) == [("planned", {"count": 0})]


async def test_forks_are_refused_before_the_stream_without_a_model(
    client: AsyncClient, providers: FakeProviders
) -> None:
    original = await create_scenario(client, await create_agent_id(client))
    providers.generation_model_ = None

    response = await client.post(
        f"/api/v1/scenarios/{original['id']}/forks/draft",
        json={"instruction": "Moves to Madrid", "count": 1},
    )

    assert response.status_code == 503, response.text


async def test_a_failed_plan_ends_the_stream_with_its_reason(
    client: AsyncClient, generation_model: FakeJsonModel
) -> None:
    original = await create_scenario(client, await create_agent_id(client))
    generation_model.down = True

    response = await client.post(
        f"/api/v1/scenarios/{original['id']}/forks/draft",
        json={"instruction": "Moves to Madrid", "count": 1},
    )

    assert events_of(response.text) == [("failed", {"error": "the model call failed: timed out"})]


def fork_answer(**changes: Any) -> dict[str, Any]:
    """A persona fork as the writer returns it: null keeps the persona's own value."""
    unchanged = {
        "name": "Rushed caller (changed)",
        "prompt": None,
        "language": None,
        "voice_gender": None,
        "speed": None,
        "noise": None,
        "noise_level": None,
        "speaker": None,
        "unsupported": [],
    }
    return {**unchanged, **changes}


async def persona_draft(
    client: AsyncClient, generation_model: FakeJsonModel, persona_id: str, **changes: Any
) -> list[tuple[str, dict[str, Any]]]:
    generation_model.changes = ["The change."]
    generation_model.persona = fork_answer(**changes)
    response = await client.post(
        f"/api/v1/personas/{persona_id}/forks/draft",
        json={"instruction": "The change", "count": 1},
    )
    return events_of(response.text)


async def test_a_persona_fork_in_another_language_gets_a_voice_that_speaks_it(
    client: AsyncClient, generation_model: FakeJsonModel
) -> None:
    original = await create_persona(client, name="Rushed caller", sample_line="Hi there.")

    events = await persona_draft(
        client, generation_model, original["id"], language="hi", voice_gender="female"
    )

    draft = next(data for kind, data in events if kind == "fork")
    assert (draft["language"], draft["voice"]["id"], draft["forked_from_id"]) == (
        "hi",
        HINDI_VOICE.id,
        original["id"],
    )
    assert draft["sample_line"] is None


async def test_a_persona_fork_changes_only_what_the_change_names(
    client: AsyncClient, generation_model: FakeJsonModel
) -> None:
    surroundings = {
        "sounds": [{"sound": "cafe", "db": -12}, {"sound": "street", "db": -16}],
        "auto": None,
        "speaker": {"kind": "tv", "db": -9, "start_s": 3},
    }
    original = await create_persona(
        client, name="Rushed caller", prompt="You are impatient.", surroundings=surroundings
    )

    louder = await persona_draft(client, generation_model, original["id"], noise_level="loud")
    no_tv = await persona_draft(client, generation_model, original["id"], speaker="none")

    loud = next(data for kind, data in louder if kind == "fork")
    quiet = next(data for kind, data in no_tv if kind == "fork")
    own = original["surroundings"]
    louder_sounds = [{**sound, "db": -4} for sound in own["sounds"]]
    assert loud["surroundings"] == {**own, "sounds": louder_sounds}
    assert (loud["prompt"], loud["voice"]) == ("You are impatient.", original["voice"])
    assert quiet["surroundings"] == {**own, "speaker": None}
    assert loud["name"] == "Rushed caller (changed)"


async def test_a_persona_fork_keeps_an_unchanged_name_as_a_fork(
    client: AsyncClient, generation_model: FakeJsonModel
) -> None:
    original = await create_persona(client, name="Rushed caller")

    events = await persona_draft(
        client, generation_model, original["id"], name="Rushed caller", speed="slow"
    )

    draft = next(data for kind, data in events if kind == "fork")
    assert (draft["name"], draft["voice"]["speed"]) == ("Rushed caller (fork)", 0.85)


async def test_a_change_no_field_can_hold_drops_the_fork_with_the_reason(
    client: AsyncClient, generation_model: FakeJsonModel
) -> None:
    original = await create_persona(client, name="Rushed caller")

    events = await persona_draft(
        client,
        generation_model,
        original["id"],
        unsupported=["speaks French: French is not supported"],
    )

    assert events == [
        ("planned", {"count": 1}),
        (
            "dropped",
            {"reason": "not supported: speaks French: French is not supported"},
        ),
    ]


async def test_closing_the_fork_stream_stops_its_writers(
    generation_model: FakeJsonModel,
) -> None:
    generation_model.changes = ["One.", "Two."]
    started, stopped = asyncio.Event(), []

    async def write(change: str) -> str:
        started.set()
        try:
            await asyncio.sleep(60)
        finally:
            stopped.append(change)
        return change

    events = forks.fork_drafts(
        generation_model, "scenario", "{}", ForkRequest(instruction="Two forks", count=2), write
    )
    planned = await anext(events)
    waiting = asyncio.ensure_future(anext(events))
    await asyncio.wait_for(started.wait(), 5)
    waiting.cancel()
    await asyncio.gather(waiting, return_exceptions=True)
    await events.aclose()

    assert planned == forks.Planned(2)
    assert sorted(stopped) == ["One.", "Two."]


async def test_an_agent_forked_twice_gets_two_free_names(client: AsyncClient) -> None:
    agent_id = await create_agent_id(client, name="Front desk")

    first = (await client.post(f"/api/v1/agents/{agent_id}/fork")).json()
    second = (await client.post(f"/api/v1/agents/{agent_id}/fork")).json()

    assert (first["name"], second["name"]) == ("Front desk (fork)", "Front desk (fork) (2)")


async def test_a_persona_fork_whose_name_was_taken_meanwhile_tries_the_next(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = await create_persona(client, name="Rushed caller")
    await client.post(f"/api/v1/personas/{original['id']}/fork")
    real = personas.persona_names
    calls: list[int] = []

    async def stale_once(session: Any) -> list[str]:
        calls.append(1)
        return [] if len(calls) == 1 else await real(session)

    monkeypatch.setattr(personas, "persona_names", stale_once)

    response = await client.post(f"/api/v1/personas/{original['id']}/fork")

    assert response.status_code == 201, response.text
    assert response.json()["name"] == "Rushed caller (fork) (2)"


async def test_a_gender_no_listed_voice_has_drops_the_fork(
    client: AsyncClient, generation_model: FakeJsonModel
) -> None:
    original = await create_persona(client, name="Rushed caller")

    events = await persona_draft(client, generation_model, original["id"], voice_gender="neutral")

    assert events == [
        ("planned", {"count": 1}),
        ("dropped", {"reason": "no listed neutral voice speaks en"}),
    ]


def test_surroundings_a_fork_does_not_touch_stay_as_they_are() -> None:
    own = Surroundings(
        sounds=(Sound(sound=NoiseSound.TV, db=-12),),
        speaker=Speaker(kind=SpeakerKind.TV, db=-9, start_s=3),
    )

    assert forks.changed_surroundings(own, None, None, None) == own


TWO_SETS = [
    {"name": "Austin", "known_facts": [{"name": "Moving to", "value": "Austin, Texas"}]},
    {"name": "Denver", "known_facts": [{"name": "Moving to", "value": "Denver, Colorado"}]},
]


async def test_a_fork_keeps_only_the_data_sets_asked_for(
    client: AsyncClient, generation_model: FakeJsonModel
) -> None:
    original = await create_scenario(client, await create_agent_id(client), data_sets=TWO_SETS)
    denver = original["data_sets"][1]
    url = f"/api/v1/scenarios/{original['id']}"
    generation_model.changes = ["Madrid"]
    generation_model.write = moved_to

    manual = await client.post(f"{url}/fork", json={"data_set_ids": [denver["id"]]})
    drafted = await client.post(
        f"{url}/forks/draft",
        json={"instruction": "Moves to Madrid", "count": 1, "data_set_ids": [denver["id"]]},
    )
    unknown = await client.post(f"{url}/fork", json={"data_set_ids": [str(uuid.uuid4())]})
    twice = await client.post(f"{url}/fork", json={"data_set_ids": [denver["id"]] * 2})

    assert manual.status_code == 201, manual.text
    assert manual.json()["data_sets"] == [denver]
    draft = next(data for kind, data in events_of(drafted.text) if kind == "fork")
    assert [(item["name"], item["known_facts"]) for item in draft["data_sets"]] == [
        ("Denver", denver["known_facts"])
    ]
    assert unknown.status_code == 422 and "no data set" in unknown.text
    assert twice.status_code == 422 and "listed more than once" in twice.text


async def test_a_written_fork_that_renames_a_fact_is_dropped(
    client: AsyncClient, generation_model: FakeJsonModel
) -> None:
    original = await create_scenario(client, await create_agent_id(client))

    def renames(prompt: str) -> dict[str, Any]:
        fork = moved_to(prompt)
        fork["data_sets"][0]["known_facts"][0]["name"] = "Full name"
        return fork

    generation_model.changes = ["Madrid"]
    generation_model.write = renames

    response = await client.post(
        f"/api/v1/scenarios/{original['id']}/forks/draft",
        json={"instruction": "Moves to Madrid", "count": 1},
    )

    assert [kind for kind, _ in events_of(response.text)] == ["planned", "dropped"]
    assert "changed the names" in events_of(response.text)[1][1]["reason"]


def data_set_for(prompt: str) -> dict[str, Any]:
    """A data set that moves the destination to the city its line names, named as written."""
    line = prompt.rsplit("## This data set\n", 1)[1]
    city = " ".join(line.split())
    return {"name": line, "known_facts": [{"name": "moving TO", "value": city}], "agent_data": []}


async def test_written_data_sets_keep_the_names_and_get_free_set_names(
    client: AsyncClient, generation_model: FakeJsonModel, db: Db
) -> None:
    original = await create_scenario(client, await create_agent_id(client), data_sets=TWO_SETS)
    url = f"/api/v1/scenarios/{original['id']}"
    generation_model.changes = ["Austin", "  New   York "]
    generation_model.write = data_set_for

    await client.patch(
        url, json={"data_sets": [*original["data_sets"], {**TWO_SETS[0], "name": "new york"}]}
    )
    response = await client.post(
        f"{url}/data-sets/draft", json={"instruction": "Austin and New York", "count": 2}
    )
    drafts = [data for kind, data in events_of(response.text) if kind == "data_set"]
    current = (await client.get(url)).json()["data_sets"]
    saved = await client.patch(url, json={"data_sets": [*current, *drafts]})
    await save_settings(db, {"limits": {"max_scenario_data_sets": 5}})
    no_room = await client.post(
        f"{url}/data-sets/draft", json={"instruction": "Austin and Madrid", "count": 2}
    )

    assert sorted((d["name"], d["known_facts"][0]["value"]) for d in drafts) == [
        ("Austin (2)", "Austin"),
        ("New York (2)", "New York"),
    ]
    assert all(d["known_facts"][0]["name"] == "Moving to" for d in drafts)
    assert len(current) == 3, "writing data sets saves nothing"
    assert saved.status_code == 200, saved.text
    assert no_room.status_code == 422 and "room for 0 more data sets" in no_room.text
