import asyncio
import hashlib
import hmac
import socket
from collections.abc import AsyncIterator

import aiohttp
import pytest
from aiohttp.abc import AbstractResolver, ResolveResult
from fastapi import FastAPI, Request, Response
from fastapi.responses import RedirectResponse, StreamingResponse

from yaksh.caller.plivo_server import PlivoServer
from yaksh.domain.scenarios import Fact
from yaksh.domain.triggers import RenderedTrigger, Trigger, TriggerMethod, render
from yaksh.integrations.trigger import (
    PublicOnlyResolver,
    TriggerResult,
    is_public,
    mask,
    send_trigger,
)

BODY = b'{"to": "+15716535187"}'


@pytest.fixture
async def agent_system() -> AsyncIterator[tuple[str, list[Request]]]:
    """A stand-in for the system that starts the agent's call."""
    app = FastAPI()
    seen: list[Request] = []

    @app.post("/calls")
    async def calls(request: Request) -> Response:
        seen.append(request)
        await request.body()
        return Response(f'{{"id": "call-9", "echo": "{request.headers["authorization"]}"}}')

    @app.get("/start")
    async def start(request: Request) -> Response:
        seen.append(request)
        return Response('{"id": "call-10"}')

    @app.post("/refused")
    async def refused() -> Response:
        return Response('{"error": "phone is required"}', status_code=422)

    @app.post("/broken")
    async def broken() -> Response:
        return Response("upstream down", status_code=503)

    @app.post("/moved")
    async def moved() -> Response:
        return RedirectResponse("/calls", status_code=307)

    @app.post("/long")
    async def long() -> StreamingResponse:
        async def parts() -> AsyncIterator[bytes]:
            yield b"x" * 490
            await asyncio.sleep(0.05)
            yield b"abcdef and abc"

        return StreamingResponse(parts())

    @app.post("/slow")
    async def slow() -> Response:
        await asyncio.sleep(2)
        return Response("late")

    @app.post("/slow-refusal")
    async def slow_refusal() -> StreamingResponse:
        async def parts() -> AsyncIterator[bytes]:
            yield b'{"error": '
            await asyncio.sleep(2)
            yield b'"phone is required"}'

        return StreamingResponse(parts(), status_code=422)

    server = PlivoServer(app, port=0)
    await server.start()
    yield f"http://127.0.0.1:{server.port}", seen
    await server.stop(2.0)


def request(url: str) -> RenderedTrigger:
    return RenderedTrigger(
        TriggerMethod.POST, url, {"Authorization": "Bearer sk_live"}, BODY, ("sk_live",)
    )


async def test_a_delivered_trigger_carries_its_delivery_id_and_signature(
    agent_system: tuple[str, list[Request]],
) -> None:
    base, seen = agent_system

    outcome = await send_trigger(
        request(f"{base}/calls"), "conv-1", signing_key="signing", allow_private=True
    )

    headers = seen[0].headers
    timestamp = headers["x-yaksh-timestamp"]
    expected = hmac.new(b"signing", f"conv-1.{timestamp}.".encode() + BODY, hashlib.sha256)
    assert outcome.result is TriggerResult.DELIVERED
    assert outcome.detail == 'HTTP 200: {"id": "call-9", "echo": "Bearer [secret]"}'
    assert headers["x-yaksh-delivery"] == "conv-1"
    assert headers["content-type"] == "application/json"
    assert headers["x-yaksh-signature"] == f"v1={expected.hexdigest()}"


async def test_a_get_trigger_is_sent_as_rendered_and_signed_over_its_url(
    agent_system: tuple[str, list[Request]],
) -> None:
    base, seen = agent_system
    url = f"{base}/start?source=yaksh&to=%2B15716535187&customer=Priya+%22PR%22+Raman"

    outcome = await send_trigger(
        RenderedTrigger(TriggerMethod.GET, url, {}, b"", ()),
        "conv-2",
        signing_key="signing",
        allow_private=True,
    )

    received = seen[0]
    timestamp = received.headers["x-yaksh-timestamp"]
    expected = hmac.new(b"signing", f"conv-2.{timestamp}.{url}".encode(), hashlib.sha256)
    assert outcome.result is TriggerResult.DELIVERED
    assert (received.method, str(received.url)) == ("GET", url)
    assert "content-type" not in received.headers
    assert received.headers["x-yaksh-signature"] == f"v1={expected.hexdigest()}"


async def test_a_rendered_url_is_signed_in_the_form_the_agent_receives(
    agent_system: tuple[str, list[Request]],
) -> None:
    base, seen = agent_system
    trigger = Trigger.model_validate({"method": "GET", "url": f"{base}/start?"})
    rendered = render(
        trigger, number="+15716535187", conversation_id="c-1", agent_data=list[Fact](), secrets={}
    )

    await send_trigger(rendered, "conv-4", signing_key="signing", allow_private=True)

    received = seen[0]
    timestamp = received.headers["x-yaksh-timestamp"]
    signed = f"conv-4.{timestamp}.{received.url}".encode()
    expected = hmac.new(b"signing", signed, hashlib.sha256)
    assert received.headers["x-yaksh-signature"] == f"v1={expected.hexdigest()}"


async def test_a_get_trigger_is_not_sent_again_after_a_dropped_connection() -> None:
    attempts = 0

    async def drop(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        nonlocal attempts
        attempts += 1
        await reader.readuntil(b"\r\n\r\n")
        writer.close()

    server = await asyncio.start_server(drop, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    async with server:
        outcome = await send_trigger(
            RenderedTrigger(TriggerMethod.GET, f"http://127.0.0.1:{port}/start", {}, b"", ()),
            "conv-3",
            signing_key=None,
            allow_private=True,
        )

    assert (attempts, outcome.result) == (1, TriggerResult.UNKNOWN)


def test_a_secret_sent_in_a_query_value_is_masked_in_its_encoded_form() -> None:
    trigger = Trigger.model_validate(
        {
            "method": "GET",
            "url": "https://agents.example.com/calls",
            "query": [{"name": "key", "value": "{{secrets.KEY}}"}],
        }
    )
    rendered = render(
        trigger,
        number="+15716535187",
        conversation_id="c-1",
        agent_data=list[Fact](),
        secrets={"KEY": "abc+def/ghi="},
    )

    assert mask(f"echo: {rendered.url}", rendered.secrets) == (
        "echo: https://agents.example.com/calls?key=[secret]"
    )


@pytest.mark.parametrize(
    ("path", "result", "detail"),
    [
        ("/refused", TriggerResult.REJECTED, 'HTTP 422: {"error": "phone is required"}'),
        ("/broken", TriggerResult.UNKNOWN, "HTTP 503: upstream down"),
        ("/moved", TriggerResult.UNKNOWN, "HTTP 307: "),
    ],
)
async def test_the_status_decides_whether_a_call_may_still_come(
    agent_system: tuple[str, list[Request]], path: str, result: TriggerResult, detail: str
) -> None:
    base, seen = agent_system

    outcome = await send_trigger(
        request(f"{base}{path}"), "conv-2", signing_key=None, allow_private=True
    )

    assert (outcome.result, outcome.detail) == (result, detail)
    assert seen == [], "a redirect is never followed"


async def test_a_timeout_leaves_the_call_possible_unless_the_status_refused_it(
    agent_system: tuple[str, list[Request]],
) -> None:
    base, _ = agent_system
    with socket.socket() as spare:
        spare.bind(("127.0.0.1", 0))
        closed_port = spare.getsockname()[1]

    slow = await send_trigger(
        request(f"{base}/slow"),
        "conv-3",
        signing_key=None,
        allow_private=True,
        timeout=aiohttp.ClientTimeout(total=0.5),
    )
    slow_refusal = await send_trigger(
        request(f"{base}/slow-refusal"),
        "conv-3",
        signing_key=None,
        allow_private=True,
        timeout=aiohttp.ClientTimeout(total=0.5),
    )
    refused = await send_trigger(
        request(f"http://127.0.0.1:{closed_port}/calls"),
        "conv-3",
        signing_key=None,
        allow_private=True,
    )

    assert slow.result is TriggerResult.UNKNOWN
    assert slow_refusal.result is TriggerResult.REJECTED
    assert slow_refusal.detail.startswith("HTTP 422, body not read: ")
    assert refused.result is TriggerResult.NOT_SENT


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        ("http://agents.example.com/calls", "must use https"),
        ("https://169.254.169.254/latest", "private address"),
        ("https://[::ffff:10.0.0.1]/calls", "private address"),
        ("https://localhost/calls", "private address"),
    ],
)
async def test_private_addresses_are_refused_unless_allowed(url: str, reason: str) -> None:
    outcome = await send_trigger(request(url), "conv-4", signing_key=None, allow_private=False)

    assert outcome.result is TriggerResult.NOT_SENT
    assert reason in outcome.detail


class FixedResolver(AbstractResolver):
    def __init__(self, *addresses: str) -> None:
        self.addresses = addresses

    async def resolve(
        self, host: str, port: int = 0, family: socket.AddressFamily = socket.AF_INET
    ) -> list[ResolveResult]:
        return [
            ResolveResult(hostname=host, host=address, port=port, family=family, proto=0, flags=0)
            for address in self.addresses
        ]

    async def close(self) -> None:
        pass


@pytest.mark.parametrize("addresses", [("8.8.8.8", "10.0.0.5"), ("10.0.0.5", "8.8.8.8")])
async def test_a_name_with_any_private_address_is_refused(addresses: tuple[str, str]) -> None:
    public = await PublicOnlyResolver(FixedResolver("8.8.8.8")).resolve("agents.example.com")

    with pytest.raises(OSError, match=r"10\.0\.0\.5"):
        await PublicOnlyResolver(FixedResolver(*addresses)).resolve("agents.example.com")
    assert [result["host"] for result in public] == ["8.8.8.8"]


async def test_the_excerpt_masks_secrets_before_it_is_cut(
    agent_system: tuple[str, list[Request]],
) -> None:
    base, _ = agent_system
    secrets = ("abcdef", "abc")
    long = RenderedTrigger(TriggerMethod.POST, f"{base}/long", {}, b"{}", secrets)

    outcome = await send_trigger(long, "conv-5", signing_key=None, allow_private=True)

    assert "abc" not in outcome.detail and "def" not in outcome.detail
    assert outcome.detail.startswith("HTTP 200: " + "x" * 490 + "[secret]")


def test_only_global_addresses_count_as_public() -> None:
    assert is_public("8.8.8.8")
    assert not any(
        is_public(address)
        for address in (
            "10.1.2.3",
            "127.0.0.1",
            "169.254.169.254",
            "100.64.0.1",
            "::1",
            "fd00::1",
            "::ffff:10.0.0.1",
            "64:ff9b::a9fe:a9fe",
            "::7f00:1",
        )
    )
    assert is_public("64:ff9b::808:808")
