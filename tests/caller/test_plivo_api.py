import base64
from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi import FastAPI, Request, Response

from truman.caller.plivo_api import OutboundCall, PlivoApi, PlivoError
from truman.caller.plivo_server import PlivoServer

AUTH_ID = "MAXXXXXXXXXXXXXXXXXX"
AUTH_TOKEN = "secret-token"


@pytest.fixture
async def plivo() -> AsyncIterator[tuple[PlivoApi, list[dict[str, Any]]]]:
    """A stand-in for api.plivo.com that records what it was asked."""
    seen: list[dict[str, Any]] = []
    app = FastAPI()

    @app.post("/v1/Account/{auth_id}/Call/")
    async def create(auth_id: str, request: Request) -> Response:
        body = await request.json()
        seen.append({"auth_id": auth_id, "authorization": request.headers["authorization"], **body})
        if body["to"] == "+10000000000":
            return Response('{"error": "Unknown caller id"}', status_code=400)
        if body["to"] == "+10000000001":
            return Response("<html>bad gateway</html>", status_code=502)
        return Response('{"request_uuid": "req-1", "message": "call queued"}', status_code=201)

    @app.delete("/v1/Account/{auth_id}/Request/{request_uuid}/")
    async def cancel(auth_id: str, request_uuid: str) -> Response:
        seen.append({"cancelled": request_uuid})
        return Response(status_code=204)

    @app.delete("/v1/Account/{auth_id}/Call/{call_uuid}/")
    async def hang_up(auth_id: str, call_uuid: str) -> Response:
        seen.append({"hung_up": call_uuid})
        return Response(status_code=404 if call_uuid == "gone" else 204)

    server = PlivoServer(app, port=0)
    await server.start()
    yield PlivoApi(AUTH_ID, AUTH_TOKEN, base_url=f"http://127.0.0.1:{server.port}"), seen
    await server.stop(2.0)


def call(to_number: str = "+14155550100") -> OutboundCall:
    return OutboundCall(
        from_number="+17862242321",
        to_number=to_number,
        answer_url="https://truman.example.com/answer/c1",
        hangup_url="https://truman.example.com/callbacks/c1",
        ring_url="https://truman.example.com/callbacks/c1",
        ring_timeout_s=30,
        time_limit_s=120,
    )


async def test_a_call_is_placed_with_the_parameters_plivo_needs(
    plivo: tuple[PlivoApi, list[dict[str, Any]]],
) -> None:
    api, seen = plivo

    request_uuid = await api.create_call(call())

    assert request_uuid == "req-1"
    basic = base64.b64encode(f"{AUTH_ID}:{AUTH_TOKEN}".encode()).decode()
    assert seen == [
        {
            "auth_id": AUTH_ID,
            "authorization": f"Basic {basic}",
            "from": "+17862242321",
            "to": "+14155550100",
            "answer_url": "https://truman.example.com/answer/c1",
            "answer_method": "POST",
            "hangup_url": "https://truman.example.com/callbacks/c1",
            "hangup_method": "POST",
            "ring_url": "https://truman.example.com/callbacks/c1",
            "ring_method": "POST",
            "ring_timeout": 30,
            "time_limit": 120,
        }
    ]


async def test_refusals_are_errors_and_a_gone_call_is_not(
    plivo: tuple[PlivoApi, list[dict[str, Any]]],
) -> None:
    api, seen = plivo

    with pytest.raises(PlivoError, match="400"):
        await api.create_call(call(to_number="+10000000000"))
    with pytest.raises(PlivoError, match=r"502.*bad gateway"):
        await api.create_call(call(to_number="+10000000001"))
    await api.cancel_request("req-1")
    await api.hang_up("gone")

    assert seen[-2:] == [{"cancelled": "req-1"}, {"hung_up": "gone"}]
