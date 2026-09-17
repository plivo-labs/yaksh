"""The Plivo REST calls Truman makes: place a call, cancel one still ringing, hang one up."""

import json
from dataclasses import dataclass
from typing import Any

import aiohttp

PLIVO_API = "https://api.plivo.com"
TIMEOUT = aiohttp.ClientTimeout(total=10)


class PlivoError(Exception):
    pass


@dataclass(frozen=True)
class OutboundCall:
    from_number: str
    to_number: str
    answer_url: str
    hangup_url: str
    ring_url: str
    ring_timeout_s: int
    time_limit_s: int

    def params(self) -> dict[str, Any]:
        return {
            "from": self.from_number,
            "to": self.to_number,
            "answer_url": self.answer_url,
            "answer_method": "POST",
            "hangup_url": self.hangup_url,
            "hangup_method": "POST",
            "ring_url": self.ring_url,
            "ring_method": "POST",
            "ring_timeout": self.ring_timeout_s,
            "time_limit": self.time_limit_s,
        }


class PlivoApi:
    def __init__(self, auth_id: str, auth_token: str, *, base_url: str = PLIVO_API) -> None:
        self.auth_id = auth_id
        self.auth_token = auth_token
        self._account = f"{base_url.rstrip('/')}/v1/Account/{auth_id}"
        self._auth = aiohttp.BasicAuth(auth_id, auth_token)

    async def create_call(self, call: OutboundCall) -> str:
        """Ask Plivo to dial; returns the request uuid that identifies the call until it answers."""
        async with (
            aiohttp.ClientSession(auth=self._auth, timeout=TIMEOUT) as session,
            session.post(f"{self._account}/Call/", json=call.params()) as response,
        ):
            body = await response.text()
            if response.status >= 400:
                raise PlivoError(f"create call failed with {response.status}: {body}")
        try:
            return str(json.loads(body)["request_uuid"])
        except (ValueError, KeyError, TypeError) as error:
            raise PlivoError(f"create call answered without a request uuid: {body}") from error

    async def cancel_request(self, request_uuid: str) -> None:
        """Stop a call that has not been answered; gone already is fine."""
        await self._delete(f"{self._account}/Request/{request_uuid}/")

    async def hang_up(self, call_uuid: str) -> None:
        await self._delete(f"{self._account}/Call/{call_uuid}/")

    async def _delete(self, url: str) -> None:
        async with (
            aiohttp.ClientSession(auth=self._auth, timeout=TIMEOUT) as session,
            session.delete(url) as response,
        ):
            if response.status >= 400 and response.status != 404:
                body = await response.text()
                raise PlivoError(f"delete {url} failed with {response.status}: {body}")
