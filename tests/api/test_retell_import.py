import json
from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi import FastAPI, Request, Response
from httpx import AsyncClient

from tests.conftest import FakeProviders
from yaksha.caller.plivo_server import PlivoServer

API_KEY = "retell-test-key"
INBOUND = "agent_inbound"
OUTBOUND = "agent_outbound"
SCHEMA = {
    "type": "object",
    "properties": {"date": {"type": "string"}, "headers": {"type": "string"}},
    "required": ["headers"],
}

LLM = {
    "llm_id": "llm_front",
    "version": 1,
    "start_speaker": "user",
    "begin_message": "Namaste — welcome",
    "general_prompt": "Greet {{customer_name}}. It is {{current_time}}. Ask for the {{budget}}.",
    "general_tools": [
        {
            "type": "custom",
            "name": "book",
            "url": "https://example.com/book",
            "headers": {"Authorization": "Bearer tool-secret"},
            "parameters": SCHEMA,
        },
        {"type": "extract_dynamic_variable", "variables": [{"name": "budget"}]},
    ],
}
FLOW = {
    "conversation_flow_id": "flow_lead",
    "version": 3,
    "start_speaker": "agent",
    "start_node_id": "start",
    "global_prompt": "You call leads for South Bay.",
    "nodes": [
        {
            "id": "start",
            "type": "conversation",
            "display_position": {"x": 1, "y": 2},
            "instruction": {
                "type": "prompt",
                "text": "Ask {{first_name}} about {{current_plan}} from {{user_number}} at "
                "{{current_time_Australia/Sydney}}.",
            },
        }
    ],
    "tools": [{"type": "check_availability_cal", "name": "slots", "cal_api_key": "cal_live_1"}],
}
AGENTS: dict[str, dict[int, dict[str, Any]]] = {
    INBOUND: {
        1: {
            "agent_id": INBOUND,
            "agent_name": "Front desk",
            "language": "hi-IN",
            "voice_id": "11labs-Cimo",
            "response_engine": {"type": "retell-llm", "llm_id": "llm_front", "version": 1},
            "post_call_analysis_data": [{"name": "booked", "type": "boolean"}],
        },
        2: {"agent_id": INBOUND, "agent_name": "Front desk, newer"},
    },
    OUTBOUND: {
        0: {
            "agent_id": OUTBOUND,
            "agent_name": "Lead callback",
            "language": "en-US",
            "response_engine": {
                "type": "conversation-flow",
                "conversation_flow_id": "flow_lead",
                "version": 3,
            },
        }
    },
}
LISTED = [
    {"agent_id": INBOUND, "agent_name": "Front desk", "user_modified_timestamp": 1755698851079},
    {"agent_id": OUTBOUND, "agent_name": "Lead callback"},
    {"agent_id": "agent_old", "agent_name": "Lead nurture"},
]


@pytest.fixture
async def retell(providers: FakeProviders) -> AsyncIterator[dict[str, Any]]:
    """A stand-in for api.retellai.com: three agents on two pages, two engines, and two pages of
    numbers, the second with the front desk's own."""
    state: dict[str, Any] = {
        "seen": [],
        "numbers": [
            [
                {"phone_number": "+14155550103"},
                {
                    "phone_number": "+14155550104",
                    "inbound_agents": [
                        {"agent_id": INBOUND, "weight": 0.5},
                        {"agent_id": "agent_other", "weight": 0.5},
                    ],
                },
                {"phone_number": "+14155550102", "outbound_agents": [{"agent_id": OUTBOUND}]},
            ],
            [
                {
                    "phone_number": "+14155550101",
                    "inbound_agents": [{"agent_id": INBOUND, "agent_version": 1, "weight": 1}],
                }
            ],
        ],
    }
    app = FastAPI()

    @app.middleware("http")
    async def check_key(request: Request, call_next: Any) -> Response:
        state["seen"].append({"path": request.url.path, "query": dict(request.query_params)})
        if request.headers.get("authorization") != f"Bearer {API_KEY}":
            return Response('{"message": "Invalid API key"}', status_code=401)
        return await call_next(request)

    @app.post("/v2/list-agents")
    async def agents(request: Request) -> dict[str, Any]:
        body = await request.json()
        state["listed"] = body
        if body.get("pagination_key") == "p2":
            return {"items": LISTED[2:], "has_more": False}
        return {"items": LISTED[:2], "has_more": True, "pagination_key": "p2"}

    @app.get("/list-agent-versions/{agent_id}")
    async def versions(agent_id: str) -> Any:
        if agent_id not in AGENTS:
            return Response('{"message": "Not Found"}', status_code=404)
        listed = [{"version": version, "is_published": True} for version in AGENTS[agent_id]]
        return {"items": sorted(listed, key=lambda v: -v["version"]), "has_more": False}

    @app.get("/get-agent/{agent_id}")
    async def agent(agent_id: str, version: int) -> dict[str, Any]:
        return AGENTS[agent_id][version]

    @app.get("/get-retell-llm/{llm_id}")
    async def llm(llm_id: str, version: int) -> dict[str, Any]:
        assert (llm_id, version) == ("llm_front", 1)
        return LLM

    @app.get("/get-conversation-flow/{flow_id}")
    async def flow(flow_id: str, version: int) -> dict[str, Any]:
        assert (flow_id, version) == ("flow_lead", 3)
        return FLOW

    @app.get("/v2/list-phone-numbers")
    async def numbers(pagination_key: str | None = None) -> dict[str, Any]:
        pages = state["numbers"]
        if pagination_key == "n2":
            return {"items": pages[1], "has_more": False}
        return {"items": pages[0], "has_more": len(pages) > 1, "pagination_key": "n2"}

    server = PlivoServer(app, port=0)
    await server.start()
    providers.retell_api_url = f"http://127.0.0.1:{server.port}"
    yield state
    await server.stop(2.0)


def workspace(**more: Any) -> dict[str, Any]:
    return {"api_key": API_KEY, **more}


async def test_the_voice_agents_are_listed_with_their_numbers_and_searched(
    client: AsyncClient, retell: dict[str, Any]
) -> None:
    first = (await client.post("/api/v1/agents/import/retell/agents", json=workspace())).json()
    second = (
        await client.post(
            "/api/v1/agents/import/retell/agents", json=workspace(cursor=first["next_cursor"])
        )
    ).json()
    searched = (
        await client.post("/api/v1/agents/import/retell/agents", json=workspace(name="NURTURE"))
    ).json()

    assert [(a["name"], a["numbers"]) for a in first["items"]] == [
        ("Front desk", ["+14155550101"]),
        ("Lead callback", []),
    ]
    assert first["items"][0]["updated_at"].startswith("2025-08-20")
    assert first["next_cursor"] == "p2" and second["next_cursor"] is None
    assert [a["name"] for a in second["items"]] == ["Lead nurture"]
    assert [a["name"] for a in searched["items"]] == ["Lead nurture"]
    assert retell["listed"]["filter_criteria"]["channel"]["value"] == "voice"


async def test_an_agent_with_its_own_number_is_inbound_at_the_version_the_number_calls(
    client: AsyncClient, retell: dict[str, Any]
) -> None:
    imported = await client.post(
        "/api/v1/agents/import/retell/agent", json=workspace(agent_id=INBOUND)
    )

    draft = imported.json()
    assert (draft["name"], draft["direction"], draft["language"], draft["agent_speaks_first"]) == (
        "Front desk",
        "inbound",
        "hi",
        False,
    )
    assert draft["agent_numbers"] == ["+14155550101"] and draft["start_request"] is None
    assert "Namaste — welcome" in draft["config"] and "secret" not in draft["config"]
    assert json.loads(draft["config"]) == {
        "name": "Front desk",
        "language": "hi-IN",
        "engine": {
            "start_speaker": "user",
            "begin_message": "Namaste — welcome",
            "general_prompt": LLM["general_prompt"],
            "general_tools": [
                {
                    "type": "custom",
                    "name": "book",
                    "url": "https://example.com/book",
                    "parameters": SCHEMA,
                },
                {"type": "extract_dynamic_variable", "variables": [{"name": "budget"}]},
            ],
        },
        "post_call_analysis": [{"name": "booked", "type": "boolean"}],
    }


async def test_an_agent_without_a_number_calls_out_with_its_variables(
    client: AsyncClient, retell: dict[str, Any], providers: FakeProviders
) -> None:
    imported = await client.post(
        "/api/v1/agents/import/retell/agent", json=workspace(agent_id=OUTBOUND)
    )

    draft = imported.json()
    request = draft["start_request"]
    config = json.loads(draft["config"])
    assert (draft["direction"], draft["agent_numbers"], draft["agent_speaks_first"]) == (
        "outbound",
        [],
        True,
    )
    assert "display_position" not in draft["config"] and "cal_live" not in draft["config"]
    assert config["engine"]["start_node_id"] == "start"
    assert request["url"] == f"{providers.retell_api_url}/v2/create-phone-call"
    assert request["headers"] == [{"name": "Authorization", "value": f"Bearer {API_KEY}"}]
    assert request["body"] == {
        "from_number": "+14155550102",
        "to_number": "{{yaksha.number}}",
        "override_agent_id": OUTBOUND,
        "override_agent_version": 0,
        "retell_llm_dynamic_variables": {
            "first_name": "{{agent_data.first_name}}",
            "current_plan": "{{agent_data.current_plan}}",
        },
    }


async def test_an_agent_that_cannot_place_or_take_a_call_says_why(
    client: AsyncClient, retell: dict[str, Any]
) -> None:
    retell["numbers"] = [[]]

    refused = await client.post(
        "/api/v1/agents/import/retell/agent", json=workspace(agent_id=OUTBOUND)
    )

    assert refused.status_code == 422
    assert "no number to call from" in refused.json()["error"]["message"]


@pytest.mark.parametrize(
    ("body", "status", "message"),
    [
        (workspace(agent_id="agent_missing"), 404, "no agent"),
        ({**workspace(agent_id=INBOUND), "api_key": "wrong"}, 422, "refused the API key"),
        (workspace(agent_id="../voices"), 422, "agent_id"),
    ],
    ids=["missing agent", "wrong key", "agent id that is not retell's"],
)
async def test_an_agent_that_cannot_be_imported_says_why(
    client: AsyncClient,
    retell: dict[str, Any],
    body: dict[str, Any],
    status: int,
    message: str,
) -> None:
    refused = await client.post("/api/v1/agents/import/retell/agent", json=body)

    assert refused.status_code == status and message in refused.json()["error"]["message"]
