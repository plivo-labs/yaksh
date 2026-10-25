import pytest
from httpx import AsyncClient

from tests.api.test_conversations import call_request_of
from tests.conftest import APP_SETTINGS, create_agent_id, create_scenario, start
from yaksh.config import Settings
from yaksh.integrations.provider_checks import ProviderCheckError

ASTRA = {"model": "gpt-6-astra", "reasoning_effort": "low"}


@pytest.fixture
def asked(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str | None]]:
    """The caller models checked at run start; the provider refuses any named "gone-…"."""
    seen: list[tuple[str, str | None]] = []

    async def check_llm(base_url: str, api_key: str, model: str, effort: str | None) -> None:
        seen.append((model, effort))
        if model.startswith("gone-"):
            raise ProviderCheckError(f"model {model}: The model does not exist")

    monkeypatch.setattr("yaksh.integrations.provider_checks.check_llm", check_llm)
    return seen


async def test_a_scenario_caller_model_replaces_the_settings_one_until_cleared(
    client: AsyncClient, settings: Settings, asked: list[tuple[str, str | None]]
) -> None:
    agent_id = await create_agent_id(client)
    scenario = await create_scenario(client, agent_id, caller=ASTRA)

    first = await start(client, agent_id, scenario_id=scenario["id"])
    chosen = await call_request_of(settings, first["id"])
    cleared = await client.patch(f"/api/v1/scenarios/{scenario['id']}", json={"caller": None})
    second = await start(client, agent_id, scenario_id=scenario["id"])
    default = await call_request_of(settings, second["id"])

    assert (chosen.caller.model, chosen.caller.reasoning_effort, chosen.scenario_model) == (
        "gpt-6-astra",
        "low",
        True,
    )
    assert asked == [("gpt-6-astra", "low")], "only a chosen model is checked"
    assert cleared.json()["caller"] is None and cleared.json()["current_version"] == 2
    assert (default.caller, default.scenario_model) == (APP_SETTINGS.caller, False)


async def test_a_run_is_refused_when_the_provider_refuses_a_scenario_caller_model(
    client: AsyncClient, asked: list[tuple[str, str | None]]
) -> None:
    agent_id = await create_agent_id(client)
    gone = await create_scenario(
        client, agent_id, name="Late booking", caller={"model": "gone-model"}
    )
    fine = await create_scenario(
        client, agent_id, name="Menu question", caller={"model": "gpt-6-luna"}
    )

    response = await client.post(
        "/api/v1/runs",
        json={
            "agent_id": agent_id,
            "scenarios": [{"scenario_id": gone["id"]}, {"scenario_id": fine["id"]}],
        },
    )
    runs = (await client.get("/api/v1/runs", params={"agent_id": agent_id})).json()["items"]

    assert response.status_code == 422, response.text
    message = response.json()["error"]["message"]
    assert '"Late booking"' in message and "gone-model" in message
    assert "Menu question" not in message
    assert runs == []
    assert sorted(asked) == [("gone-model", None), ("gpt-6-luna", "low")], "the effort sent"


async def test_a_repeated_request_returns_its_run_without_checking_again(
    client: AsyncClient, asked: list[tuple[str, str | None]]
) -> None:
    agent_id = await create_agent_id(client)
    scenario = await create_scenario(client, agent_id, caller=ASTRA)
    body = {"agent_id": agent_id, "scenarios": [{"scenario_id": scenario["id"]}]}
    headers = {"Idempotency-Key": "caller-model-retry"}

    first = await client.post("/api/v1/runs", json=body, headers=headers)
    await client.patch(f"/api/v1/scenarios/{scenario['id']}", json={"caller": {"model": "gone-x"}})
    again = await client.post("/api/v1/runs", json=body, headers=headers)

    assert first.status_code == again.status_code == 202, again.text
    assert again.json()["id"] == first.json()["id"]
    assert asked == [("gpt-6-astra", "low")]


async def test_a_run_over_the_limits_is_refused_before_any_model_is_asked(
    client: AsyncClient, asked: list[tuple[str, str | None]]
) -> None:
    agent_id = await create_agent_id(client)
    scenario = await create_scenario(client, agent_id, caller=ASTRA)

    response = await client.post(
        "/api/v1/runs",
        json={
            "agent_id": agent_id,
            "scenarios": [{"scenario_id": scenario["id"]}],
            "repeats": 10_000,
        },
    )

    assert response.status_code == 422, response.text
    assert asked == []
