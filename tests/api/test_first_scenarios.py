import asyncio
import uuid
from typing import Any

import pytest
from httpx import AsyncClient

from tests.conftest import AGENT, FakeJsonModel, FakeProviders, new_persona_id
from yaksha.config import Settings
from yaksha.db.models import ScenarioGeneration
from yaksha.db.session import create_engine, create_sessionmaker
from yaksha.domain.generation import GenerationStatus
from yaksha.domain.language_models import ModelAnswer
from yaksha.simulation import generation

BRIEF = "Reschedules missed clinic visits. Never gives medical advice; transfers to a nurse."


async def add_agent(client: AsyncClient) -> str:
    response = await client.post("/api/v1/agents", json={**AGENT, "brief": BRIEF})
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def generations(client: AsyncClient, agent_id: str) -> list[dict[str, Any]]:
    response = await client.get(f"/api/v1/agents/{agent_id}/scenario-generations")
    return response.json()["items"]


async def ended(client: AsyncClient, agent_id: str) -> dict[str, Any]:
    async with asyncio.timeout(5):
        while True:
            listed = await generations(client, agent_id)
            if listed and listed[0]["status"] != "running":
                return listed[0]
            await asyncio.sleep(0.02)


def blocked(model: FakeJsonModel) -> asyncio.Event:
    """Makes the model wait for ever; the event is set once it is asked."""
    asked = asyncio.Event()

    async def wait(**_: Any) -> ModelAnswer:
        asked.set()
        await asyncio.sleep(60)
        raise AssertionError("unreachable")

    model.complete_json = wait  # type: ignore[method-assign]
    return asked


async def test_a_new_agent_gets_its_first_scenarios_after_the_response(
    client: AsyncClient, generation_model: FakeJsonModel
) -> None:
    await new_persona_id(client)
    generation_model.capabilities = [
        {
            "name": "Reschedule",
            "what_it_does": "Reschedule for the caller.",
            "priority": "core",
            "quotes": ["Reschedules missed clinic visits."],
            "already_tested": False,
        }
    ]

    agent_id = await add_agent(client)
    done = await ended(client, agent_id)
    scenarios = (await client.get(f"/api/v1/agents/{agent_id}/scenarios")).json()["items"]

    assert (done["status"], done["count"], done["scenarios"]) == ("done", 5, len(scenarios))
    assert len(scenarios) >= 1
    assert {s["generation_id"] for s in scenarios} == {done["id"]}


async def test_no_generation_starts_without_a_model(
    client: AsyncClient, providers: FakeProviders
) -> None:
    await new_persona_id(client)
    providers.generation_model_ = None

    agent_id = await add_agent(client)

    assert await generations(client, agent_id) == []


async def test_a_running_generation_is_listed_and_can_be_stopped(
    client: AsyncClient, generation_model: FakeJsonModel
) -> None:
    await new_persona_id(client)
    asked = blocked(generation_model)

    agent_id = await add_agent(client)
    await asyncio.wait_for(asked.wait(), 5)
    running = await generations(client, agent_id)
    stop = await client.post(f"/api/v1/scenario-generations/{running[0]['id']}/stop")
    stopped = await ended(client, agent_id)
    again = await client.post(f"/api/v1/scenario-generations/{running[0]['id']}/stop")

    assert (running[0]["status"], running[0]["scenarios"]) == ("running", 0)
    assert stop.status_code == 204
    assert stopped["status"] == "stopped"
    assert again.status_code == 404


async def test_a_generation_that_takes_too_long_fails(
    client: AsyncClient, generation_model: FakeJsonModel, monkeypatch: pytest.MonkeyPatch
) -> None:
    await new_persona_id(client)
    blocked(generation_model)
    monkeypatch.setattr(generation, "TIME_LIMIT_S", 0.2)

    agent_id = await add_agent(client)
    failed = await ended(client, agent_id)

    assert (failed["status"], failed["error"]) == ("failed", generation.TOO_LONG)


async def test_generations_left_running_are_stopped_at_start(
    client: AsyncClient, settings: Settings, generation_model: FakeJsonModel
) -> None:
    await new_persona_id(client)
    asked = blocked(generation_model)
    agent_id = await add_agent(client)
    await asyncio.wait_for(asked.wait(), 5)
    engine = create_engine(settings.database_url.encoded_string())

    async with create_sessionmaker(engine)() as session:
        await generation.stop_running(session)
        row = await session.get_one(
            ScenarioGeneration, uuid.UUID((await generations(client, agent_id))[0]["id"])
        )
    await engine.dispose()

    assert row.status is GenerationStatus.STOPPED
