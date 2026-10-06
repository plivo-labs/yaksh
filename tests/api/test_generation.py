import asyncio
import json
import uuid
from collections.abc import MutableMapping
from contextlib import aclosing
from typing import Any

import anyio
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from tests.conftest import (
    OUTBOUND_AGENT,
    TOKEN,
    FakeJsonModel,
    create_agent,
    create_scenario,
    new_persona_id,
)
from yaksha.api import create_app
from yaksha.config import Settings
from yaksha.db.models import Scenario, ScenarioGeneration
from yaksha.db.session import create_engine, create_sessionmaker
from yaksha.domain.errors import UnavailableError
from yaksha.domain.generation import MAX_PLANNER_CHARS, GenerateScenarios, GenerationStatus
from yaksha.domain.language_models import ModelAnswer
from yaksha.simulation import generation

BRIEF = "Reschedules missed clinic visits. Never gives medical advice; transfers to a nurse."
OPEN_REQUEST = "Make it a request a caller could plausibly make to this agent.\n"
"""The line before the request an open refusal test asks for."""


def capability(name: str, quote: str, priority: str = "core", tested: bool = False) -> dict:
    return {
        "name": name,
        "what_it_does": f"{name} for the caller.",
        "priority": priority,
        "quotes": [quote],
        "already_tested": tested,
    }


async def persona_ids(client: AsyncClient, count: int = 1) -> list[str]:
    return [await new_persona_id(client) for _ in range(count)]


async def generate(client: AsyncClient, agent_id: str, **body: Any) -> list[tuple[str, dict]]:
    if "persona_ids" not in body:
        body["persona_ids"] = await persona_ids(client)
    response = await client.post(f"/api/v1/agents/{agent_id}/scenarios/generate", json=body)
    assert response.status_code == 200, response.text
    events = []
    for block in response.text.strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        events.append((fields["event"], json.loads(fields["data"])))
    return events


async def generation_row(settings: Settings, generation_id: str) -> ScenarioGeneration:
    engine = create_engine(settings.database_url.encoded_string())
    async with create_sessionmaker(engine)() as session:
        row = await session.get_one(ScenarioGeneration, uuid.UUID(generation_id))
    await engine.dispose()
    return row


async def test_scenarios_are_planned_from_the_agent_and_saved_as_they_are_written(
    client: AsyncClient, generation_model: FakeJsonModel, settings: Settings
) -> None:
    agent = await create_agent(client, brief=BRIEF)
    generation_model.capabilities = [
        capability("Reschedule", "Reschedules missed clinic visits."),
        capability("Refill", "Refills every prescription by text."),
        capability("Medical advice", "Never gives medical advice", "boundary"),
    ]

    events = await generate(client, agent["id"], count=5)

    kinds = [kind for kind, _ in events]
    saved = [data for kind, data in events if kind == "scenario"]
    finished = events[-1][1]
    writer_prompts = [user for name, user in generation_model.calls if name == "scenario"]
    row = await generation_row(settings, events[0][1]["generation_id"])
    listed = (await client.get(f"/api/v1/agents/{agent['id']}/scenarios")).json()["items"]
    assert kinds == ["started", "planned", *["scenario"] * 5, "finished"]
    assert events[1][1] == {"count": 5}
    assert sorted(s["category"] for s in saved) == [
        "edge_case",
        "happy_path",
        "happy_path",
        "messy_input",
        "messy_input",
    ]
    assert not any("Refill" in prompt for prompt in writer_prompts), "its quote was invented"
    assert finished == {"status": "done", "saved": 5, "dropped": 0, "error": None}
    assert (row.status, row.saved, row.agent_version_id is not None) == (
        GenerationStatus.DONE,
        5,
        True,
    )
    assert sorted(s["name"] for s in listed) == [
        "Medical advice",
        "Reschedule",
        "Reschedule (2)",
        "Reschedule (3)",
        "Reschedule (4)",
    ]


async def test_knowledge_base_mode_asks_what_the_chosen_documents_answer(
    client: AsyncClient, generation_model: FakeJsonModel
) -> None:
    faq = (
        await client.post(
            "/api/v1/documents", json={"name": "faq.md", "text": "We accept Medi-Cal at all sites."}
        )
    ).json()["id"]
    agent = await create_agent(
        client, knowledge_base=[{"document_id": faq, "name": "Insurance FAQ"}]
    )
    generation_model.questions = {
        "answered": [
            {
                "question": "Do you take Medi-Cal?",
                "answer": "Yes, at all sites",
                "document": "Insurance FAQ",
                "quote": "We accept Medi-Cal at all sites",
            },
            {
                "question": "Do you take Aetna?",
                "answer": "Yes",
                "document": "Insurance FAQ",
                "quote": "We accept Aetna everywhere",
            },
        ],
        "unanswered": [{"question": "Is there parking?"}],
    }

    events = await generate(client, agent["id"], mode="knowledge_base", count=5, document_ids=[faq])

    saved = [(data["name"], data["category"]) for kind, data in events if kind == "scenario"]
    prompts = "\n".join(user for name, user in generation_model.calls if name == "scenario")
    assert sorted(category for _, category in saved) == [
        "edge_case",
        "happy_path",
        "happy_path",
        "happy_path",
        "messy_input",
    ]
    assert all(
        name.startswith("Is there parking?" if category == "edge_case" else "Do you take Medi-Cal?")
        for name, category in saved
    )
    assert "Aetna" not in prompts, "its quote is not in the document"
    assert 'The documented answer is "Yes, at all sites", from "Insurance FAQ"' in prompts


async def test_a_scenario_that_fails_its_check_twice_is_dropped_with_the_reason(
    client: AsyncClient, generation_model: FakeJsonModel
) -> None:
    agent = await create_agent(client, brief=BRIEF)
    generation_model.capabilities = [capability("Reschedule", "Reschedules missed clinic visits.")]
    generation_model.write = lambda prompt: {
        "name": "No criteria",
        "description": "",
        "goal": "Reschedule.",
        "known_facts": [],
        "unknown_facts": [],
        "criteria": [],
        "agent_data": [],
    }

    events = await generate(client, agent["id"], count=1)

    writes = [name for name, _ in generation_model.calls if name == "scenario"]
    assert [kind for kind, _ in events] == ["started", "planned", "dropped", "finished"]
    assert events[2][1]["reason"].startswith("the written scenario is not valid")
    assert len(writes) == 2
    assert events[-1][1] == {"status": "done", "saved": 0, "dropped": 1, "error": None}


async def test_an_outbound_scenario_must_give_the_agent_the_data_its_trigger_needs(
    client: AsyncClient, generation_model: FakeJsonModel
) -> None:
    agent = await create_agent(client, **{**OUTBOUND_AGENT, "brief": BRIEF})
    generation_model.capabilities = [capability("Reschedule", "Reschedules missed clinic visits.")]

    events = await generate(client, agent["id"], count=1)

    writer_prompt = next(user for name, user in generation_model.calls if name == "scenario")
    assert "agent_data must hold a value for each of these" in writer_prompt
    assert "customer name" in writer_prompt
    assert events[2] == (
        "dropped",
        {"reason": "the scenario has no agent data named customer name"},
    )


async def test_a_model_failure_ends_the_generation_as_failed(
    client: AsyncClient, generation_model: FakeJsonModel, settings: Settings
) -> None:
    agent = await create_agent(client, brief=BRIEF)
    generation_model.down = True

    events = await generate(client, agent["id"], count=3)

    row = await generation_row(settings, events[0][1]["generation_id"])
    assert [kind for kind, _ in events] == ["started", "finished"]
    assert events[-1][1]["error"] == "the model call failed: timed out"
    assert (row.status, row.error) == (GenerationStatus.FAILED, "the model call failed: timed out")


@pytest.mark.parametrize(
    ("setup", "body", "status", "message"),
    [
        ("empty", {}, 422, "add a brief, a config or knowledge base documents first"),
        (
            "brief",
            {"mode": "knowledge_base", "document_ids": [str(uuid.UUID(int=1))]},
            422,
            "not in",
        ),
        ("huge", {}, 422, "the limit is 800,000"),
        ("brief", {"count": 21}, 422, "count"),
    ],
    ids=["no context", "foreign document", "too much context", "too many"],
)
async def test_a_generation_is_refused_before_it_starts(
    client: AsyncClient, setup: str, body: dict, status: int, message: str
) -> None:
    extra = {
        "empty": {},
        "brief": {"brief": BRIEF},
        "huge": {"config": "x" * MAX_PLANNER_CHARS},
    }[setup]
    agent = await create_agent(client, **extra)

    refused = await client.post(
        f"/api/v1/agents/{agent['id']}/scenarios/generate",
        json={"persona_ids": await persona_ids(client), **body},
    )

    assert refused.status_code == status
    assert message in refused.json()["error"]["message"]


async def test_stopping_keeps_what_was_saved_and_records_the_stop(
    client: AsyncClient, generation_model: FakeJsonModel, settings: Settings
) -> None:
    agent = await create_agent(client, brief=BRIEF)
    await create_scenario(client, agent["id"])
    generation_model.capabilities = [capability("Reschedule", "Reschedules missed clinic visits.")]
    engine = create_engine(settings.database_url.encoded_string())
    sessionmaker = create_sessionmaker(engine)
    async with sessionmaker() as session:
        prepared = await generation.prepare(
            session,
            generation_model,
            uuid.UUID(agent["id"]),
            GenerateScenarios(count=4, persona_ids=await persona_ids(client)),
        )

    events = generation.generate(sessionmaker, generation_model, prepared)
    started = await anext(events)
    assert isinstance(started, generation.Started)
    await anext(events)
    first = await anext(events)
    await events.aclose()
    async with sessionmaker() as session:
        row = await session.get_one(ScenarioGeneration, started.generation_id)
        saved_rows = list(
            await session.scalars(
                select(Scenario.id).where(Scenario.generation_id == started.generation_id)
            )
        )
    await engine.dispose()

    assert isinstance(first, generation.Saved)
    assert first.scenario.generation_id == started.generation_id
    assert row.status is GenerationStatus.STOPPED
    assert row.saved == len(saved_rows) >= 1, "the count is what the database holds"


async def test_generation_is_off_without_a_model(client: AsyncClient, settings: Settings) -> None:
    agent = await create_agent(client, brief=BRIEF)
    engine = create_engine(settings.database_url.encoded_string())

    async with create_sessionmaker(engine)() as session:
        with pytest.raises(UnavailableError, match="scenario generation is off"):
            await generation.prepare(
                session,
                None,
                uuid.UUID(agent["id"]),
                GenerateScenarios(persona_ids=await persona_ids(client)),
            )
    await engine.dispose()


@pytest.mark.parametrize(
    "capabilities",
    [
        [capability("Refill", "Refills every prescription by text.")],
        [capability("Medical advice", "Never gives medical advice", "boundary")],
    ],
    ids=["invented quote", "only refusals"],
)
async def test_nothing_is_written_when_the_plan_has_no_grounded_work(
    client: AsyncClient, generation_model: FakeJsonModel, capabilities: list[dict]
) -> None:
    agent = await create_agent(client, brief=BRIEF)
    generation_model.capabilities = capabilities

    events = await generate(client, agent["id"], count=3)

    assert [kind for kind, _ in events] == ["started", "finished"]
    assert events[-1][1]["error"] == "the agent's context shows nothing to test"
    assert not [name for name, _ in generation_model.calls if name == "scenario"]


async def test_repeats_of_one_area_and_open_refusals_are_each_asked_differently(
    client: AsyncClient, generation_model: FakeJsonModel
) -> None:
    agent = await create_agent(client, brief=BRIEF)
    generation_model.capabilities = [capability("Reschedule", "Reschedules missed clinic visits.")]

    events = await generate(client, agent["id"], count=20)

    prompts = [user for name, user in generation_model.calls if name == "scenario"]
    normal = [p for p in prompts if "## What to test\nA normal request" in p]
    changes = [line for p in normal for line in p.splitlines() if line.startswith("Vary it:")]
    refusals = [p for p in prompts if "must refuse, redirect or hand off." in p]
    asks = {p.split(OPEN_REQUEST, 1)[1].split("\n", 1)[0] for p in refusals}
    assert events[1] == ("planned", {"count": 14})
    assert len(prompts) == len(set(prompts)) == 14
    assert (len(normal), len(changes), len(set(changes))) == (5, 4, 4)
    assert len(refusals) == len(asks) == 4
    assert all("## What the agent handles\n- Reschedule" in p for p in prompts)


async def test_knowledge_base_mode_reads_only_the_chosen_documents(
    client: AsyncClient, generation_model: FakeJsonModel
) -> None:
    faq = (
        await client.post(
            "/api/v1/documents", json={"name": "faq.md", "text": "Open 9 to 5 daily."}
        )
    ).json()["id"]
    agent = await create_agent(
        client,
        config="x" * MAX_PLANNER_CHARS,
        knowledge_base=[{"document_id": faq, "name": "Hours"}],
    )

    events = await generate(client, agent["id"], mode="knowledge_base", document_ids=[faq])

    planner_prompt = next(user for name, user in generation_model.calls if name == "questions")
    assert "## Configuration" not in planner_prompt and "Open 9 to 5 daily." in planner_prompt
    assert events[-1][1]["error"] == "the agent's context shows nothing to test"


async def test_a_disconnect_during_planning_still_records_the_stop(
    client: AsyncClient, generation_model: FakeJsonModel, settings: Settings
) -> None:
    agent = await create_agent(client, brief=BRIEF)
    planning = asyncio.Event()

    async def slow_plan(**_: Any) -> ModelAnswer:
        planning.set()
        await asyncio.sleep(60)
        return ModelAnswer(data={"capabilities": []}, model="fake", input_tokens=0, output_tokens=0)

    generation_model.complete_json = slow_plan  # type: ignore[method-assign]
    engine = create_engine(settings.database_url.encoded_string())
    sessionmaker = create_sessionmaker(engine)
    async with sessionmaker() as session:
        prepared = await generation.prepare(
            session,
            generation_model,
            uuid.UUID(agent["id"]),
            GenerateScenarios(count=2, persona_ids=await persona_ids(client)),
        )
    seen: list[generation.Event] = []
    scope = anyio.CancelScope()

    async def console() -> None:
        with scope:
            events = generation.generate(sessionmaker, generation_model, prepared)
            async with aclosing(events):
                async for event in events:
                    seen.append(event)

    listening = asyncio.create_task(console())
    await asyncio.wait_for(planning.wait(), 5)
    scope.cancel()
    await asyncio.wait_for(listening, 5)
    started = seen[0]
    assert isinstance(started, generation.Started)
    async with sessionmaker() as session:
        row = await session.get_one(ScenarioGeneration, started.generation_id)
    await engine.dispose()

    assert (row.status, row.ended_at is not None) == (GenerationStatus.STOPPED, True)


async def test_a_disconnect_while_an_event_waits_to_be_sent_still_records_the_stop(
    client: AsyncClient,
    generation_model: FakeJsonModel,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = await create_agent(client, brief=BRIEF)
    generation_model.capabilities = [capability("Reschedule", "Reschedules missed clinic visits.")]
    app = create_app(settings)
    app.state.generation_model = generation_model
    first_chunk, gone = asyncio.Event(), asyncio.Event()
    body = json.dumps({"count": 4, "persona_ids": await persona_ids(client)}).encode()
    requested = False

    async def receive() -> dict[str, Any]:
        nonlocal requested
        if not requested:
            requested = True
            return {"type": "http.request", "body": body, "more_body": False}
        await first_chunk.wait()
        gone.set()
        return {"type": "http.disconnect"}

    async def send(message: MutableMapping[str, Any]) -> None:
        if message["type"] == "http.response.body" and message.get("body"):
            first_chunk.set()
            await gone.wait()
            raise OSError("the console closed the connection")

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": f"/api/v1/agents/{agent['id']}/scenarios/generate",
        "raw_path": b"",
        "query_string": b"",
        "headers": [
            (b"authorization", f"Bearer {TOKEN}".encode()),
            (b"content-type", b"application/json"),
        ],
        "client": ("127.0.0.1", 1),
        "server": ("test", 80),
    }
    ended: list[GenerationStatus] = []
    record_end = generation.record_end

    async def recorded(*args: Any) -> int:
        saved = await record_end(*args)
        ended.append(args[2])
        return saved

    monkeypatch.setattr(generation, "record_end", recorded)
    with pytest.RaisesGroup(OSError):
        await asyncio.wait_for(app(scope, receive, send), 5)
    ended_with_the_request = list(ended)
    await app.state.engine.dispose()

    assert ended_with_the_request == [GenerationStatus.STOPPED]


async def test_a_batch_is_listed_filtered_and_deleted_together(
    client: AsyncClient, generation_model: FakeJsonModel
) -> None:
    agent = await create_agent(client, brief=BRIEF)
    by_hand = await create_scenario(client, agent["id"])
    generation_model.capabilities = [capability("Reschedule", "Reschedules missed clinic visits.")]
    events = await generate(client, agent["id"], count=3)
    generation_id = events[0][1]["generation_id"]
    base = f"/api/v1/agents/{agent['id']}"

    listed = (await client.get(f"{base}/scenario-generations")).json()["items"]
    batch = (await client.get(f"{base}/scenarios", params={"generation_id": generation_id})).json()
    ids = [item["id"] for item in batch["items"]]
    refused = await client.post(
        f"{base}/scenarios/delete", json={"scenario_ids": [*ids, str(uuid.uuid4())]}
    )
    kept_after_refusal = (await client.get(f"{base}/scenarios")).json()["total"]
    deleted = await client.post(f"{base}/scenarios/delete", json={"scenario_ids": ids})
    remaining = (await client.get(f"{base}/scenarios")).json()["items"]
    listed_after = (await client.get(f"{base}/scenario-generations")).json()["items"]

    assert [(item["id"], item["scenarios"]) for item in listed] == [(generation_id, 3)]
    assert {item["generation_id"] for item in batch["items"]} == {generation_id}
    assert refused.status_code == 404 and kept_after_refusal == 4
    assert deleted.status_code == 204
    assert [item["id"] for item in remaining] == [by_hand["id"]]
    assert listed_after == []


async def test_scenarios_of_another_agent_cannot_be_deleted_through_this_one(
    client: AsyncClient,
) -> None:
    mine = await create_agent(client, name="Mine")
    other = await create_agent(client, name="Other")
    theirs = await create_scenario(client, other["id"])

    response = await client.post(
        f"/api/v1/agents/{mine['id']}/scenarios/delete", json={"scenario_ids": [theirs["id"]]}
    )

    assert response.status_code == 404
    assert (await client.get(f"/api/v1/scenarios/{theirs['id']}")).status_code == 200


async def test_new_scenarios_spread_the_chosen_personas(
    client: AsyncClient, generation_model: FakeJsonModel
) -> None:
    agent = await create_agent(client, brief=BRIEF)
    generation_model.capabilities = [capability("Reschedule", "Reschedules missed clinic visits.")]
    first, second = await persona_ids(client, 2)

    events = await generate(client, agent["id"], count=3, persona_ids=[first, second])

    saved = {data["category"]: data["persona_id"] for kind, data in events if kind == "scenario"}
    assert saved == {"happy_path": first, "messy_input": second, "edge_case": first}


async def test_a_generation_needs_live_personas_each_picked_once(client: AsyncClient) -> None:
    agent = await create_agent(client, brief=BRIEF)
    [persona] = await persona_ids(client)
    url = f"/api/v1/agents/{agent['id']}/scenarios/generate"

    unknown = await client.post(url, json={"persona_ids": [str(uuid.uuid4())]})
    twice = await client.post(url, json={"persona_ids": [persona, persona]})
    none = await client.post(url, json={"persona_ids": []})

    assert unknown.status_code == 404
    assert twice.status_code == 422 and "pick each persona once" in twice.text
    assert none.status_code == 422


async def test_a_persona_deleted_during_a_generation_ends_it_with_the_reason(
    client: AsyncClient, generation_model: FakeJsonModel, settings: Settings
) -> None:
    agent = await create_agent(client, brief=BRIEF)
    generation_model.capabilities = [capability("Reschedule", "Reschedules missed clinic visits.")]
    [persona] = await persona_ids(client)
    engine = create_engine(settings.database_url.encoded_string())
    sessionmaker = create_sessionmaker(engine)
    async with sessionmaker() as session:
        prepared = await generation.prepare(
            session,
            generation_model,
            uuid.UUID(agent["id"]),
            GenerateScenarios(count=2, persona_ids=[uuid.UUID(persona)]),
        )
    await client.delete(f"/api/v1/personas/{persona}")

    events = [
        event async for event in generation.generate(sessionmaker, generation_model, prepared)
    ]
    await engine.dispose()

    finished = events[-1]
    assert isinstance(finished, generation.Finished)
    assert (finished.status, finished.error, finished.saved) == (
        GenerationStatus.FAILED,
        "persona not found",
        0,
    )
