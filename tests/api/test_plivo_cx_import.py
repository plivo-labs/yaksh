import base64
from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi import FastAPI, Request, Response
from httpx import AsyncClient

from tests.conftest import FakeProviders
from yaksha.caller.plivo_server import PlivoServer

AUTH_ID = "MAXXXXXXXXXXXXXXXXXX"
AUTH_TOKEN = "secret-token"
INBOUND = "0b9e0c4a-0000-4000-8000-000000000001"
OUTBOUND = "0b9e0c4a-0000-4000-8000-000000000002"
CHAT = "0b9e0c4a-0000-4000-8000-000000000003"
OTHER = "0b9e0c4a-0000-4000-8000-000000000004"
MISSING = "0b9e0c4a-0000-4000-8000-000000000005"
DRAFT = "0b9e0c4a-0000-4000-8000-000000000006"
LONELY = "0b9e0c4a-0000-4000-8000-000000000007"
BLOCKED: dict[str, str] = {}
"""Path parts the stand-in refuses with 403, and the reply it sends for each."""
WHITELIST_REFUSAL = (
    '{"api_id": "x", "error": "Access denied. The request originated from IP 203.0.113.9, which '
    'is not in the IP whitelist for this account. Update your IP whitelist in the console."}'
)

FLOWS: dict[str, dict[str, Any]] = {
    INBOUND: {
        "agent_uuid": INBOUND,
        "flow_type": "incoming_call",
        "name": "Front desk",
        "state": "ACTIVE",
        "nodes": [{"id": "start-1", "type": "start", "config": {"model": {"triggers": ["call"]}}}],
    },
    OUTBOUND: {
        "agent_uuid": OUTBOUND,
        "flow_type": "api_request",
        "name": "Lead callback",
        "state": "ACTIVE",
        "nodes": [
            {
                "id": "start-1",
                "type": "start",
                "config": {
                    "model": {
                        "triggers": ["http"],
                        "require_http_auth": True,
                        "payload_format": {
                            "company_name": "string",
                            "phone_number": "string",
                            "lead": {"source": "string"},
                        },
                    }
                },
            }
        ],
    },
    DRAFT: {
        "agent_uuid": DRAFT,
        "flow_type": "incoming_call",
        "name": "Front desk v2",
        "state": "DRAFT",
        "nodes": [{"id": "start-1", "type": "start", "config": {"model": {"triggers": ["call"]}}}],
    },
    LONELY: {
        "agent_uuid": LONELY,
        "flow_type": "incoming_call",
        "name": "Night line",
        "state": "ACTIVE",
        "nodes": [{"id": "start-1", "type": "start", "config": {"model": {"triggers": ["call"]}}}],
    },
    CHAT: {
        "agent_uuid": CHAT,
        "flow_type": "incoming_chat",
        "name": "Chat help",
        "state": "ACTIVE",
        "nodes": [{"id": "start-1", "type": "start", "config": {"model": {"triggers": ["chat"]}}}],
    },
}


def runner_url(flow_id: str) -> str:
    return f"https://ap-south-1-runner-svc-pvt.contacto.com/v1/account/{AUTH_ID}/phlo/{flow_id}#er=mumbai"


@pytest.fixture
async def plivo(providers: FakeProviders) -> AsyncIterator[list[dict[str, Any]]]:
    """A stand-in for api.plivo.com: an account with one inbound, one outbound and one chat flow,
    and numbers whose applications send calls to them."""
    seen: list[dict[str, Any]] = []
    app = FastAPI()

    @app.middleware("http")
    async def check_auth(request: Request, call_next: Any) -> Response:
        expected = "Basic " + base64.b64encode(f"{AUTH_ID}:{AUTH_TOKEN}".encode()).decode()
        seen.append({"path": request.url.path, "query": dict(request.query_params)})
        if request.headers.get("authorization") != expected:
            return Response('{"error": "authentication failed"}', status_code=401)
        for part, reply in BLOCKED.items():
            if part in request.url.path:
                return Response(reply, status_code=403)
        return await call_next(request)

    @app.get("/v1/Account/{auth_id}/AgentFlow/")
    async def flows(
        auth_id: str, offset: int = 0, name: str = "", state: str = ""
    ) -> dict[str, Any]:
        found = [
            flow
            for flow in FLOWS.values()
            if name.lower() in flow["name"].lower() and state in ("", flow["state"])
        ]
        return {
            "meta": {"total_count": len(found), "offset": offset},
            "objects": [{k: v for k, v in flow.items() if k != "nodes"} for flow in found],
        }

    @app.get("/v1/Account/{auth_id}/AgentFlow/{flow_id}/")
    async def flow(auth_id: str, flow_id: str) -> Any:
        if flow_id not in FLOWS:
            return Response('{"error": "not found"}', status_code=404)
        return FLOWS[flow_id]

    @app.get("/v1/Account/{auth_id}/Application/")
    async def applications(
        auth_id: str, internal: str = "", offset: int = 0, limit: int = 20
    ) -> dict[str, Any]:
        # Plivo CX's applications are internal: a plain list leaves them out. 21 of them, so the
        # one that matters is on the second page.
        objects = [
            {
                "app_id": f"9{i}",
                "app_name": f"agent_flow_1415555{i:04}",
                "answer_url": runner_url(OTHER),
            }
            for i in range(18)
        ] + [
            {
                "app_id": "12",
                "app_name": "agent_flow_14155550102",
                "answer_url": runner_url(INBOUND),
            },
            {"app_id": "13", "app_name": "agent_flow_14155550103", "answer_url": runner_url(OTHER)},
            {
                "app_id": "11",
                "app_name": "agent_flow_14155550101",
                "answer_url": runner_url(INBOUND),
            },
        ]
        listed = objects if internal == "true" else []
        more = offset + limit < len(listed)
        return {
            "meta": {"next": "/next" if more else None},
            "objects": listed[offset : offset + limit],
        }

    @app.get("/v1/Account/{auth_id}/Number/")
    async def numbers(auth_id: str) -> dict[str, Any]:
        def number(digits: str, app_id: str, voice: bool = True) -> dict[str, Any]:
            return {
                "number": digits,
                "voice_enabled": voice,
                "application": f"/v1/Account/{auth_id}/Application/{app_id}/",
            }

        return {
            "meta": {"next": None},
            "objects": [
                number("14155550101", "11"),
                # Its own agent_flow application is stale: the number now goes to another flow.
                number("14155550102", "13"),
                number("14155550104", "12", voice=False),
            ],
        }

    server = PlivoServer(app, port=0)
    await server.start()
    providers.plivo_api_url = f"http://127.0.0.1:{server.port}"
    yield seen
    BLOCKED.clear()
    await server.stop(2.0)


def account(**more: Any) -> dict[str, Any]:
    return {"auth_id": AUTH_ID, "auth_token": AUTH_TOKEN, **more}


async def test_the_flows_of_an_account_are_listed_and_searched(
    client: AsyncClient, plivo: list[dict[str, Any]]
) -> None:
    listed = await client.post("/api/v1/agents/import/plivo-cx/flows", json=account())
    searched = await client.post(
        "/api/v1/agents/import/plivo-cx/flows", json=account(name="lead", offset=20)
    )

    assert [flow["name"] for flow in listed.json()["items"]] == [
        "Front desk",
        "Lead callback",
        "Night line",
    ]
    assert listed.json()["next_offset"] is None
    assert [flow["name"] for flow in searched.json()["items"]] == ["Lead callback"]
    assert plivo[-1]["query"] == {"limit": "20", "offset": "20", "state": "ACTIVE", "name": "lead"}


async def test_a_flow_a_call_starts_gets_the_voice_numbers_that_still_reach_it(
    client: AsyncClient, plivo: list[dict[str, Any]]
) -> None:
    imported = await client.post(
        "/api/v1/agents/import/plivo-cx/flow", json=account(flow_id=INBOUND)
    )

    draft = imported.json()
    assert (draft["name"], draft["external_id"], draft["direction"]) == (
        "Front desk",
        INBOUND,
        "inbound",
    )
    assert draft["agent_numbers"] == ["+14155550101"] and draft["start_request"] is None
    assert draft["language"] == "en" and '"Front desk"' in draft["config"]


async def test_a_flow_no_number_reaches_is_imported_and_says_so(
    client: AsyncClient, plivo: list[dict[str, Any]]
) -> None:
    imported = await client.post(
        "/api/v1/agents/import/plivo-cx/flow", json=account(flow_id=LONELY)
    )

    draft = imported.json()
    assert imported.status_code == 200 and draft["agent_numbers"] == []
    assert draft["number_note"].startswith("No Plivo number sends calls to this agent")


async def test_a_refused_number_lookup_still_imports_the_agent_with_plivos_reason(
    client: AsyncClient, plivo: list[dict[str, Any]]
) -> None:
    BLOCKED["/Application/"] = WHITELIST_REFUSAL

    imported = await client.post(
        "/api/v1/agents/import/plivo-cx/flow", json=account(flow_id=INBOUND)
    )

    draft = imported.json()
    assert imported.status_code == 200 and draft["name"] == "Front desk"
    assert draft["agent_numbers"] == []
    assert "IP 203.0.113.9 is not in this account's IP whitelist" in draft["number_note"]


async def test_a_flow_a_request_starts_gets_the_start_request_plivo_cx_shows(
    client: AsyncClient, plivo: list[dict[str, Any]]
) -> None:
    imported = await client.post(
        "/api/v1/agents/import/plivo-cx/flow", json=account(flow_id=OUTBOUND)
    )

    draft = imported.json()
    request = draft["start_request"]
    basic = base64.b64encode(f"{AUTH_ID}:{AUTH_TOKEN}".encode()).decode()
    assert draft["direction"] == "outbound" and draft["agent_numbers"] == []
    assert request["url"] == f"https://agentflow.plivo.com/v1/account/{AUTH_ID}/flow/{OUTBOUND}"
    assert request["headers"] == [{"name": "Authorization", "value": f"Basic {basic}"}]
    assert request["body"] == {
        "company_name": "{{agent_data.company_name}}",
        "phone_number": "{{yaksha.number}}",
        "lead": {"source": "{{agent_data.lead_source}}"},
    }


@pytest.mark.parametrize(
    ("reply", "message"),
    [
        (
            WHITELIST_REFUSAL,
            "Plivo blocked the request: IP 203.0.113.9 is not in this account's IP whitelist. "
            "Add it in the Plivo console, then try again",
        ),
        (
            '{"error": "This feature is not on your plan."}',
            "Plivo refused the request: This feature is not on your plan.",
        ),
        ("<html>Forbidden</html>", "Plivo refused the request"),
    ],
    ids=["ip whitelist", "other reason", "no reason"],
)
async def test_a_refused_flow_read_shows_plivos_reason(
    client: AsyncClient, plivo: list[dict[str, Any]], reply: str, message: str
) -> None:
    BLOCKED["/AgentFlow/"] = reply

    refused = await client.post(
        "/api/v1/agents/import/plivo-cx/flow", json=account(flow_id=INBOUND)
    )

    assert refused.status_code == 422 and refused.json()["error"]["message"] == message


@pytest.mark.parametrize(
    ("body", "status", "message"),
    [
        (account(flow_id=CHAT), 422, "starts from chat"),
        (account(flow_id=DRAFT), 422, "only an active flow"),
        (account(flow_id=MISSING), 404, "no agent flow"),
        ({**account(flow_id=INBOUND), "auth_token": "wrong"}, 422, "refused the Auth ID"),
        ({**account(flow_id=INBOUND), "auth_id": "MA../../Call"}, 422, "auth_id"),
    ],
    ids=["chat flow", "draft flow", "missing flow", "wrong token", "auth id that is not plivo's"],
)
async def test_a_flow_that_cannot_be_imported_says_why(
    client: AsyncClient,
    plivo: list[dict[str, Any]],
    body: dict[str, Any],
    status: int,
    message: str,
) -> None:
    refused = await client.post("/api/v1/agents/import/plivo-cx/flow", json=body)

    assert refused.status_code == status and message in refused.json()["error"]["message"]
