import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI, Request, Response
from httpx import AsyncClient

from tests.conftest import FakeProviders
from yaksh.caller.plivo_server import PlivoServer

API_KEY = "vapi-test-key"
INBOUND = "0c7a2a4e-1d0b-4c43-9a51-2f3c8d8f0001"
OUTBOUND = "0c7a2a4e-1d0b-4c43-9a51-2f3c8d8f0002"
SILENT = "0c7a2a4e-1d0b-4c43-9a51-2f3c8d8f0003"
SCHEMA = {
    "type": "object",
    "properties": {"date": {"type": "string"}, "headers": {"type": "string"}},
    "required": ["headers"],
}
START = datetime(2026, 1, 1, tzinfo=UTC)

ASSISTANTS: dict[str, dict[str, Any]] = {
    INBOUND: {
        "id": INBOUND,
        "name": "Front desk",
        "firstMessage": "Namaste — welcome",
        "firstMessageMode": "assistant-waits-for-user",
        "transcriber": {"provider": "deepgram", "language": "hi"},
        "voice": {"provider": "vapi", "voiceId": "Elliot"},
        "model": {
            "provider": "openai",
            "model": "gpt-4.1",
            "messages": [{"role": "system", "content": "Book the caller a table."}],
            "toolIds": ["tool_book", "tool_deleted"],
            "tools": [
                {
                    "type": "apiRequest",
                    "name": "notify",
                    "headers": {"X-Key": "inline-secret"},
                    "server": {"url": "https://example.com", "secret": "server-secret"},
                }
            ],
        },
        "analysisPlan": {"successEvaluationPlan": {"enabled": True, "rubric": "PassFail"}},
    },
    OUTBOUND: {
        "id": OUTBOUND,
        "name": "Lead callback",
        "firstMessage": "Hi {{customer.name}}, it is {{now}}; call {{call.id}}.",
        "model": {
            "messages": [
                {
                    "role": "system",
                    "content": "Call {{ customer_name }} back about {{product | upcase}} "
                    "from {{customer.number}}.",
                }
            ]
        },
    },
    SILENT: {"id": SILENT, "name": "Survey", "model": {"messages": []}},
}


@pytest.fixture
async def vapi(providers: FakeProviders) -> AsyncIterator[dict[str, Any]]:
    """A stand-in for api.vapi.ai: three assistants with 98 older ones behind them, one tool,
    and two pages of numbers: a free one, 99 that call out, and the front desk's own."""
    older = [
        {"id": f"old-{at}", "name": "Lead nurture" if at == 97 else f"Old {at}"} for at in range(98)
    ]
    listed = [*ASSISTANTS.values(), *older]
    numbers = [
        {"id": "phone_free", "number": "+14155550100", "provider": "vapi"},
        {
            "id": "phone_blocked",
            "number": "+14155550103",
            "assistantId": OUTBOUND,
            "status": "blocked",
        },
        *({"id": f"phone_{at}", "provider": "byo-phone-number"} for at in range(99)),
        {"id": "phone_front", "number": "+14155550101", "assistantId": INBOUND},
    ]
    for at, item in [*enumerate(listed), *enumerate(numbers)]:
        item["createdAt"] = (START - timedelta(minutes=at)).isoformat()
    state: dict[str, Any] = {"seen": [], "numbers": numbers}
    app = FastAPI()

    @app.middleware("http")
    async def check_key(request: Request, call_next: Any) -> Response:
        state["seen"].append({"path": request.url.path, "query": dict(request.query_params)})
        if request.headers.get("authorization") != f"Bearer {API_KEY}":
            return Response('{"message": "Invalid Key"}', status_code=401)
        return await call_next(request)

    def page(items: list[dict[str, Any]], limit: int, before: str | None) -> list[dict[str, Any]]:
        start = datetime.fromisoformat(before) if before else None
        older = [
            item for item in items if not start or datetime.fromisoformat(item["createdAt"]) < start
        ]
        return older[:limit]

    @app.get("/assistant")
    async def assistants(limit: int, createdAtLt: str | None = None) -> list[dict[str, Any]]:
        return page(listed, limit, createdAtLt)

    @app.get("/assistant/{assistant_id}")
    async def assistant(assistant_id: str) -> Any:
        if assistant_id not in ASSISTANTS:
            return Response('{"message": "Not Found"}', status_code=404)
        return ASSISTANTS[assistant_id]

    @app.get("/tool/{tool_id}")
    async def tool(tool_id: str) -> Any:
        if tool_id == "tool_deleted":
            return Response('{"message": "Not Found"}', status_code=404)
        return {
            "id": tool_id,
            "type": "function",
            "function": {"name": "book", "parameters": SCHEMA},
            "server": {"url": "https://example.com/book", "headers": {"Authorization": "x"}},
        }

    @app.get("/phone-number")
    async def phone_numbers(limit: int, createdAtLt: str | None = None) -> list[dict[str, Any]]:
        return page(state["numbers"], limit, createdAtLt)

    server = PlivoServer(app, port=0)
    await server.start()
    providers.vapi_api_url = f"http://127.0.0.1:{server.port}"
    yield state
    await server.stop(2.0)


def organization(**more: Any) -> dict[str, Any]:
    return {"api_key": API_KEY, **more}


async def test_the_assistants_are_listed_newest_first_and_searched_by_name(
    client: AsyncClient, vapi: dict[str, Any]
) -> None:
    first = (await client.post("/api/v1/agents/import/vapi/assistants", json=organization())).json()
    second = (
        await client.post(
            "/api/v1/agents/import/vapi/assistants",
            json=organization(cursor=first["next_cursor"]),
        )
    ).json()
    searched = (
        await client.post("/api/v1/agents/import/vapi/assistants", json=organization(name="lead"))
    ).json()

    assert [(a["name"], a["numbers"]) for a in first["items"][:2]] == [
        ("Front desk", ["+14155550101"]),
        ("Lead callback", []),
    ]
    assert len(first["items"]) == 100 and first["next_cursor"] is not None
    assert [a["name"] for a in second["items"]] == ["Lead nurture"]
    assert second["next_cursor"] is None
    assert [a["name"] for a in searched["items"]] == ["Lead callback"]


async def test_a_search_reads_on_until_a_page_has_a_match(
    client: AsyncClient, vapi: dict[str, Any]
) -> None:
    found = (
        await client.post(
            "/api/v1/agents/import/vapi/assistants", json=organization(name="NURTURE")
        )
    ).json()

    assert [a["name"] for a in found["items"]] == ["Lead nurture"]
    assert found["next_cursor"] is None
    assert len([seen for seen in vapi["seen"] if seen["path"] == "/assistant"]) == 2


async def test_an_assistant_with_a_number_is_inbound_without_its_credentials(
    client: AsyncClient, vapi: dict[str, Any]
) -> None:
    imported = await client.post(
        "/api/v1/agents/import/vapi/assistant", json=organization(assistant_id=INBOUND)
    )

    draft = imported.json()
    assert (draft["direction"], draft["languages"], draft["agent_speaks_first"]) == (
        "inbound",
        ["hi"],
        False,
    )
    assert draft["agent_numbers"] == ["+14155550101"] and draft["start_request"] is None
    assert "Namaste — welcome" in draft["config"] and "secret" not in draft["config"]
    assert json.loads(draft["config"]) == {
        "name": "Front desk",
        "first_message": "Namaste — welcome",
        "first_message_mode": "assistant-waits-for-user",
        "messages": [{"role": "system", "content": "Book the caller a table."}],
        "tools": [
            {"type": "apiRequest", "name": "notify", "server": {"url": "https://example.com"}},
            {
                "id": "tool_book",
                "type": "function",
                "function": {"name": "book", "parameters": SCHEMA},
                "server": {"url": "https://example.com/book"},
            },
        ],
        "analysis_plan": {"successEvaluationPlan": {"enabled": True, "rubric": "PassFail"}},
    }


async def test_an_assistant_without_a_number_calls_out_with_its_variables(
    client: AsyncClient, vapi: dict[str, Any], providers: FakeProviders
) -> None:
    imported = await client.post(
        "/api/v1/agents/import/vapi/assistant", json=organization(assistant_id=OUTBOUND)
    )

    draft = imported.json()
    request = draft["start_request"]
    assert (draft["direction"], draft["agent_numbers"], draft["agent_speaks_first"]) == (
        "outbound",
        [],
        True,
    )
    assert request["url"] == f"{providers.vapi_api_url}/call"
    assert request["headers"] == [{"name": "Authorization", "value": f"Bearer {API_KEY}"}]
    assert request["number_field"] == "customer.number"
    assert request["body"] == {
        "assistantId": OUTBOUND,
        "phoneNumberId": "phone_0",
        "customer": {"number": "{{yaksh.number}}", "name": "{{agent_data.customer_name}}"},
        "assistantOverrides": {
            "variableValues": {
                "customer_name": "{{agent_data.customer_name}}",
                "product": "{{agent_data.product}}",
            }
        },
    }


async def test_an_assistant_that_cannot_place_or_take_a_call_says_why(
    client: AsyncClient, vapi: dict[str, Any]
) -> None:
    vapi["numbers"] = vapi["numbers"][:1]

    refused = await client.post(
        "/api/v1/agents/import/vapi/assistant", json=organization(assistant_id=OUTBOUND)
    )

    assert refused.status_code == 422
    assert "no number to call from" in refused.json()["error"]["message"]


@pytest.mark.parametrize(
    ("body", "status", "message"),
    [
        (organization(assistant_id="0c7a2a4e-1d0b-4c43-9a51-2f3c8d8f0009"), 404, "no agent"),
        ({**organization(assistant_id=INBOUND), "api_key": "wrong"}, 422, "refused the API key"),
        (organization(assistant_id="../tool"), 422, "assistant_id"),
    ],
    ids=["missing assistant", "wrong key", "assistant id that is not vapi's"],
)
async def test_an_assistant_that_cannot_be_imported_says_why(
    client: AsyncClient,
    vapi: dict[str, Any],
    body: dict[str, Any],
    status: int,
    message: str,
) -> None:
    refused = await client.post("/api/v1/agents/import/vapi/assistant", json=body)

    assert refused.status_code == status and message in refused.json()["error"]["message"]


async def test_an_assistant_without_a_first_message_waits_for_the_caller(
    client: AsyncClient, vapi: dict[str, Any]
) -> None:
    imported = await client.post(
        "/api/v1/agents/import/vapi/assistant", json=organization(assistant_id=SILENT)
    )

    assert imported.json()["agent_speaks_first"] is False
