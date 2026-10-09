import json
from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi import FastAPI, Request, Response
from httpx import AsyncClient

from tests.conftest import FakeProviders
from yaksha.caller.plivo_server import PlivoServer

API_KEY = "sk_test"
INBOUND = "agent_inbound"
OUTBOUND = "agent_outbound"
SCHEMA = {"type": "object", "properties": {"code_body": {"type": "string"}}, "required": []}

INLINE_TOOL = {
    "name": "notify",
    "api_schema": {"url": "https://example.com", "request_headers": {"X-Key": "inline-secret"}},
}
OVERRIDE = {"agent": {"prompt": {"tool_ids": ["tool_refund"]}}}

AGENTS: dict[str, dict[str, Any]] = {
    INBOUND: {
        "agent_id": INBOUND,
        "name": "Front desk",
        "conversation_config": {
            "agent": {
                "first_message": "Namaste — welcome",
                "language": "hi",
                "prompt": {
                    "prompt": "Book the caller a table.",
                    "tool_ids": ["tool_book"],
                    "tools": [INLINE_TOOL],
                },
            },
            "tts": {"voice_id": "voice-1"},
        },
        "platform_settings": {"widget": {"variant": "full"}, "evaluation": {"criteria": []}},
        "workflow": {
            "nodes": {
                "start_node": {"type": "start", "position": {"x": 0, "y": 0}},
                "lookup": {"type": "tool", "tools": [{"tool_id": "tool_lookup"}]},
                "billing": {"conversation_config": OVERRIDE},
                "handoff": {
                    "type": "override_agent",
                    "additional_tool_ids": ["tool_book", "tool_handoff", "tool_deleted"],
                },
            }
        },
        "phone_numbers": [{"phone_number": "+14155550101", "supports_inbound": True}],
        "access_info": {"creator_email": "someone@example.com"},
    },
    OUTBOUND: {
        "agent_id": OUTBOUND,
        "name": "Lead callback",
        "conversation_config": {
            "agent": {
                "language": "en",
                "prompt": {"prompt": "Call the lead back."},
                "dynamic_variables": {
                    "dynamic_variable_placeholders": {
                        "customer_name": "Asha",
                        "system__caller_id": "",
                    }
                },
            }
        },
        "phone_numbers": [],
    },
}


@pytest.fixture
async def elevenlabs(providers: FakeProviders) -> AsyncIterator[dict[str, Any]]:
    """A stand-in for api.elevenlabs.io: two agents, one tool and two numbers that place calls."""
    state: dict[str, Any] = {
        "seen": [],
        "numbers": [
            {"provider": "whatsapp", "phone_number_id": "phnum_whatsapp"},
            {"provider": "sip_trunk", "phone_number_id": "phnum_sip"},
        ],
    }
    app = FastAPI()

    @app.middleware("http")
    async def check_key(request: Request, call_next: Any) -> Response:
        state["seen"].append({"path": request.url.path, "query": dict(request.query_params)})
        if request.headers.get("xi-api-key") != API_KEY:
            return Response('{"detail": "invalid_api_key"}', status_code=401)
        return await call_next(request)

    @app.get("/v1/convai/agents")
    async def agents(search: str = "", cursor: str = "") -> dict[str, Any]:
        found = [agent for agent in AGENTS.values() if search.lower() in agent["name"].lower()]
        rows = [
            {"agent_id": agent["agent_id"], "name": agent["name"], "last_call_time_unix_secs": 0}
            for agent in found
        ]
        return {"agents": rows, "has_more": not cursor, "next_cursor": "page-2"}

    @app.get("/v1/convai/agents/{agent_id}")
    async def agent(agent_id: str) -> Any:
        if agent_id not in AGENTS:
            return Response('{"detail": "not found"}', status_code=404)
        return AGENTS[agent_id]

    @app.get("/v1/convai/tools/{tool_id}")
    async def tool(tool_id: str) -> Any:
        if tool_id == "tool_deleted":
            return Response('{"detail": "not found"}', status_code=404)
        schema = {
            "request_body_schema": SCHEMA,
            "request_headers": {"Authorization": "Bearer tool-secret"},
        }
        config = {"name": tool_id, "api_schema": schema, "description": ""}
        return {"id": tool_id, "tool_config": config, "usage_stats": {"avg_latency_secs": 1}}

    @app.get("/v1/convai/v2/phone-numbers")
    async def numbers() -> dict[str, Any]:
        return {"phone_numbers": state["numbers"], "has_more": False}

    server = PlivoServer(app, port=0)
    await server.start()
    providers.elevenlabs_api_url = f"http://127.0.0.1:{server.port}"
    yield state
    await server.stop(2.0)


def workspace(**more: Any) -> dict[str, Any]:
    return {"api_key": API_KEY, **more}


async def test_the_agents_of_a_workspace_are_listed_and_searched(
    client: AsyncClient, elevenlabs: dict[str, Any]
) -> None:
    listed = await client.post("/api/v1/agents/import/elevenlabs/agents", json=workspace())
    searched = await client.post(
        "/api/v1/agents/import/elevenlabs/agents", json=workspace(name="lead", cursor="page-2")
    )

    assert [agent["name"] for agent in listed.json()["items"]] == ["Front desk", "Lead callback"]
    assert listed.json()["next_cursor"] == "page-2"
    assert [agent["name"] for agent in searched.json()["items"]] == ["Lead callback"]
    assert searched.json()["next_cursor"] is None
    assert elevenlabs["seen"][-1]["query"] == {
        "page_size": "50",
        "archived": "false",
        "search": "lead",
        "cursor": "page-2",
    }


async def test_an_agent_with_a_number_is_inbound_with_its_behavior_as_the_config(
    client: AsyncClient, elevenlabs: dict[str, Any]
) -> None:
    imported = await client.post(
        "/api/v1/agents/import/elevenlabs/agent", json=workspace(agent_id=INBOUND)
    )

    draft = imported.json()
    config = json.loads(draft["config"])
    assert "Namaste — welcome" in draft["config"] and "secret" not in draft["config"]
    assert (draft["name"], draft["external_id"], draft["direction"], draft["language"]) == (
        "Front desk",
        INBOUND,
        "inbound",
        "hi",
    )
    assert draft["agent_numbers"] == ["+14155550101"] and draft["start_request"] is None
    assert config == {
        "name": "Front desk",
        "agent": {
            "first_message": "Namaste — welcome",
            "language": "hi",
            "prompt": {
                "prompt": "Book the caller a table.",
                "tool_ids": ["tool_book"],
                "tools": [{"name": "notify", "api_schema": {"url": "https://example.com"}}],
            },
        },
        "workflow": {
            "nodes": {
                "start_node": {"type": "start"},
                "lookup": {"type": "tool", "tools": [{"tool_id": "tool_lookup"}]},
                "billing": {"conversation_config": OVERRIDE},
                "handoff": {
                    "type": "override_agent",
                    "additional_tool_ids": ["tool_book", "tool_handoff", "tool_deleted"],
                },
            }
        },
        "tools": [
            {"name": "tool_book", "api_schema": {"request_body_schema": SCHEMA}},
            {"name": "tool_refund", "api_schema": {"request_body_schema": SCHEMA}},
            {"name": "tool_handoff", "api_schema": {"request_body_schema": SCHEMA}},
            {"name": "tool_lookup", "api_schema": {"request_body_schema": SCHEMA}},
        ],
    }


async def test_an_agent_without_a_number_calls_out_from_a_workspace_number(
    client: AsyncClient, elevenlabs: dict[str, Any], providers: FakeProviders
) -> None:
    imported = await client.post(
        "/api/v1/agents/import/elevenlabs/agent", json=workspace(agent_id=OUTBOUND)
    )

    draft = imported.json()
    request = draft["start_request"]
    assert draft["direction"] == "outbound" and draft["agent_numbers"] == []
    assert request["url"] == f"{providers.elevenlabs_api_url}/v1/convai/sip-trunk/outbound-call"
    assert request["headers"] == [{"name": "xi-api-key", "value": API_KEY}]
    assert request["number_field"] == "to_number"
    assert request["body"] == {
        "agent_id": OUTBOUND,
        "agent_phone_number_id": "phnum_sip",
        "to_number": "{{yaksha.number}}",
        "conversation_initiation_client_data": {
            "dynamic_variables": {"customer_name": "{{agent_data.customer_name}}"}
        },
    }


async def test_an_agent_that_cannot_place_or_take_a_call_says_why(
    client: AsyncClient, elevenlabs: dict[str, Any]
) -> None:
    elevenlabs["numbers"] = [{"provider": "whatsapp", "phone_number_id": "phnum_whatsapp"}]

    refused = await client.post(
        "/api/v1/agents/import/elevenlabs/agent", json=workspace(agent_id=OUTBOUND)
    )

    assert refused.status_code == 422
    assert "no number that places calls" in refused.json()["error"]["message"]


@pytest.mark.parametrize(
    ("body", "status", "message"),
    [
        (workspace(agent_id="agent_missing"), 404, "no agent"),
        ({**workspace(agent_id=INBOUND), "api_key": "wrong"}, 422, "refused the API key"),
        (workspace(agent_id="../voices"), 422, "agent_id"),
    ],
    ids=["missing agent", "wrong key", "agent id that is not elevenlabs'"],
)
async def test_an_agent_that_cannot_be_imported_says_why(
    client: AsyncClient,
    elevenlabs: dict[str, Any],
    body: dict[str, Any],
    status: int,
    message: str,
) -> None:
    refused = await client.post("/api/v1/agents/import/elevenlabs/agent", json=body)

    assert refused.status_code == status and message in refused.json()["error"]["message"]
