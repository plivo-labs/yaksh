"""Sends an outbound agent's trigger: one POST, never repeated, only to public addresses unless
private ones are allowed, with its result classified by what it proves about the call."""

import errno
import hashlib
import hmac
import ipaddress
import socket
import time
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlsplit

import aiohttp
from aiohttp.abc import AbstractResolver, ResolveResult
from aiohttp.resolver import DefaultResolver

from yaksha.diagnostics import describe_exception
from yaksha.domain.triggers import SEND_TIMEOUT_S, RenderedTrigger

TIMEOUT = aiohttp.ClientTimeout(total=SEND_TIMEOUT_S, sock_connect=5)
EXCERPT_CHARS = 500
READ_LIMIT = 64 * 1024


class TriggerResult(StrEnum):
    DELIVERED = "delivered"
    """2xx: the agent's system took the request."""
    REJECTED = "rejected"
    """4xx: the agent's system refused it, so no call is coming."""
    NOT_SENT = "not_sent"
    """The request never left: no connection, or a refused address."""
    UNKNOWN = "unknown"
    """3xx, 5xx, a timeout or a dropped connection: a call may still come."""


@dataclass(frozen=True)
class TriggerOutcome:
    result: TriggerResult
    detail: str
    """The status and the start of the response body, secrets masked; or what went wrong."""


EMBEDS_IPV4 = (
    ipaddress.IPv6Network("::ffff:0:0/96"),
    ipaddress.IPv6Network("64:ff9b::/96"),
    ipaddress.IPv6Network("::/96"),
)
"""IPv4-mapped, NAT64 and IPv4-compatible addresses: each reaches the IPv4 address in its last
32 bits, so that address decides."""


def is_public(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    if isinstance(ip, ipaddress.IPv6Address) and any(ip in net for net in EMBEDS_IPV4):
        return ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF).is_global
    return ip.is_global


class PublicOnlyResolver(AbstractResolver):
    """Resolves like the default resolver and refuses the host if any address is not public.
    The connection then uses these checked addresses, so a DNS change between the check and
    the request cannot reach a private one."""

    def __init__(self, resolver: AbstractResolver | None = None) -> None:
        self._resolver = resolver or DefaultResolver()

    async def resolve(
        self, host: str, port: int = 0, family: socket.AddressFamily = socket.AF_INET
    ) -> list[ResolveResult]:
        results = await self._resolver.resolve(host, port, family)
        blocked = [result["host"] for result in results if not is_public(result["host"])]
        if blocked:
            message = f"{host} resolves to a private address ({', '.join(blocked)})"
            raise OSError(errno.EACCES, message)
        return results

    async def close(self) -> None:
        await self._resolver.close()


def signed_headers(key: str, delivery_id: str, body: bytes) -> dict[str, str]:
    timestamp = str(int(time.time()))
    message = f"{delivery_id}.{timestamp}.".encode() + body
    digest = hmac.new(key.encode(), message, hashlib.sha256).hexdigest()
    return {"X-Yaksha-Timestamp": timestamp, "X-Yaksha-Signature": f"v1={digest}"}


def mask(text: str, secrets: tuple[str, ...]) -> str:
    """Longest first, so a secret that contains another is hidden whole."""
    for secret in sorted({s for s in secrets if s}, key=len, reverse=True):
        text = text.replace(secret, "[secret]")
    return text


async def read_bounded(response: aiohttp.ClientResponse) -> str:
    body = b""
    async for chunk in response.content.iter_chunked(READ_LIMIT):
        body += chunk
        if len(body) >= READ_LIMIT:
            break
    return body[:READ_LIMIT].decode(errors="replace")


def address_problem(url: str, allow_private: bool) -> str | None:
    """Why the URL may not be called, before any connection; None when it may."""
    parts = urlsplit(url)
    if allow_private:
        return None
    if parts.scheme != "https":
        return "the trigger URL must use https"
    try:
        literal = ipaddress.ip_address(parts.hostname or "")
    except ValueError:
        return None
    return None if is_public(str(literal)) else f"{literal} is a private address"


async def send_trigger(
    request: RenderedTrigger,
    delivery_id: str,
    *,
    signing_key: str | None,
    allow_private: bool,
    timeout: aiohttp.ClientTimeout = TIMEOUT,
) -> TriggerOutcome:
    problem = address_problem(request.url, allow_private)
    if problem is not None:
        return TriggerOutcome(TriggerResult.NOT_SENT, problem)
    headers = {
        **request.headers,
        "Content-Type": "application/json",
        "X-Yaksha-Delivery": delivery_id,
    }
    if signing_key:
        headers |= signed_headers(signing_key, delivery_id, request.body)
    resolver = None if allow_private else PublicOnlyResolver()
    status: int | None = None
    try:
        async with (
            aiohttp.ClientSession(
                timeout=timeout, connector=aiohttp.TCPConnector(resolver=resolver)
            ) as session,
            session.post(
                request.url, data=request.body, headers=headers, allow_redirects=False
            ) as response,
        ):
            status = response.status
            text = await read_bounded(response)
    except (aiohttp.ClientConnectorError, aiohttp.ConnectionTimeoutError) as error:
        return TriggerOutcome(
            TriggerResult.NOT_SENT, mask(describe_exception(error), request.secrets)
        )
    except (aiohttp.ClientError, TimeoutError) as error:
        failure = mask(describe_exception(error), request.secrets)
        if status is None:
            return TriggerOutcome(TriggerResult.UNKNOWN, failure)
        return TriggerOutcome(result_of(status), f"HTTP {status}, body not read: {failure}")
    detail = f"HTTP {status}: {mask(text, request.secrets)[:EXCERPT_CHARS]}"
    return TriggerOutcome(result_of(status), detail)


def result_of(status: int) -> TriggerResult:
    if 200 <= status < 300:
        return TriggerResult.DELIVERED
    if 400 <= status < 500:
        return TriggerResult.REJECTED
    return TriggerResult.UNKNOWN
