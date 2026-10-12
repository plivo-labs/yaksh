import base64
from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse

from yaksh.caller.plivo_server import PlivoServer
from yaksh.integrations.plivo import OutboundCall, PlivoApi, PlivoError

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
        if body["to"] == "+10000000002":
            return RedirectResponse(request.url.path)
        return Response('{"request_uuid": "req-1", "message": "call queued"}', status_code=201)

    @app.get("/v1/Account/{auth_id}/Number/")
    async def numbers(auth_id: str, offset: int = 0) -> dict[str, Any]:
        if auth_id == "LOOPING":
            next_page = f"/v1/Account/{auth_id}/Number/?limit=20&offset={offset + 20}"
            return {"meta": {"next": next_page}, "objects": [{"number": "12025550100"}]}
        pages = {
            0: {
                "meta": {"next": f"/v1/Account/{auth_id}/Number/?limit=20&offset=20"},
                "objects": [
                    {
                        "number": "17862242321",
                        "alias": "",
                        "region": "Florida, UNITED STATES",
                        "voice_enabled": True,
                        "active": True,
                        "application": f"/v1/Account/{auth_id}/Application/24330520250244652/",
                    },
                    {
                        "number": "18005550100",
                        "alias": "SMS only",
                        "voice_enabled": False,
                        "active": True,
                    },
                ],
            },
            20: {
                "meta": {"next": None},
                "objects": [
                    {"number": "919999999999", "voice_enabled": True},
                    {"number": "short", "voice_enabled": True},
                ],
            },
        }
        return pages[offset]

    @app.get("/v1/Account/{auth_id}/Application/{app_id}/")
    async def application(auth_id: str, app_id: str) -> Response:
        if app_id == "2":
            return Response(content="null", media_type="application/json")
        if app_id != "24330520250244652":
            return Response(status_code=404, content='{"error": "not found"}')
        return JSONResponse(
            {
                "app_id": app_id,
                "app_name": "yaksh",
                "answer_url": "https://yaksh.example/incoming",
                "answer_method": "POST",
                "hangup_url": "https://yaksh.example/incoming/hangup",
                "hangup_method": "POST",
            }
        )

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
        answer_url="https://yaksh.example.com/answer/c1",
        hangup_url="https://yaksh.example.com/callbacks/c1",
        ring_url="https://yaksh.example.com/callbacks/c1",
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
            "answer_url": "https://yaksh.example.com/answer/c1",
            "answer_method": "POST",
            "hangup_url": "https://yaksh.example.com/callbacks/c1",
            "hangup_method": "POST",
            "ring_url": "https://yaksh.example.com/callbacks/c1",
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


async def test_account_numbers_are_listed_across_pages_in_e164(
    plivo: tuple[PlivoApi, list[dict[str, Any]]],
) -> None:
    api, _ = plivo

    numbers = await api.list_numbers()

    assert [(n.number, n.alias, n.region, n.voice, n.application_id) for n in numbers] == [
        ("+17862242321", None, "Florida, UNITED STATES", True, "24330520250244652"),
        ("+18005550100", "SMS only", None, False, None),
        ("+919999999999", None, None, True, None),
    ]


async def test_an_application_is_read_and_a_missing_one_is_an_error(
    plivo: tuple[PlivoApi, list[dict[str, Any]]],
) -> None:
    api, _ = plivo

    application = await api.get_application("24330520250244652")

    assert application.problems("https://yaksh.example") == []
    assert application.problems("https://elsewhere.example") == [
        "Plivo application yaksh has answer URL 'https://yaksh.example/incoming'; "
        "set it to 'https://elsewhere.example/incoming'",
        "Plivo application yaksh has hangup URL 'https://yaksh.example/incoming/hangup'; "
        "set it to 'https://elsewhere.example/incoming/hangup'",
    ]
    with pytest.raises(PlivoError, match="404"):
        await api.get_application("1")
    with pytest.raises(PlivoError, match="did not work"):
        await api.get_application("2")


async def test_a_listing_that_never_ends_is_an_error(
    plivo: tuple[PlivoApi, list[dict[str, Any]]], monkeypatch: pytest.MonkeyPatch
) -> None:
    api, _ = plivo
    monkeypatch.setattr("yaksh.integrations.plivo.MAX_PAGES", 3)
    looping = PlivoApi("LOOPING", "token", base_url=api.base_url)

    with pytest.raises(PlivoError, match="3 pages"):
        await looping.list_numbers()


async def test_a_failed_request_never_reports_the_credentials(
    plivo: tuple[PlivoApi, list[dict[str, Any]]],
) -> None:
    api, _ = plivo
    basic = base64.b64encode(f"{AUTH_ID}:{AUTH_TOKEN}".encode()).decode()

    with pytest.raises(PlivoError, match="TooManyRedirects") as failed:
        await api.create_call(call("+10000000002"))

    assert AUTH_TOKEN not in str(failed.value) and basic not in str(failed.value)
