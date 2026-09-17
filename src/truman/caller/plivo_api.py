"""The Plivo REST calls Truman makes: place a call, cancel one still ringing, hang one up."""

import json
import logging
from dataclasses import dataclass
from typing import Any

import aiohttp
from pydantic import ValidationError

from truman.domain.numbers import AccountNumber

log = logging.getLogger(__name__)

PLIVO_API = "https://api.plivo.com"
TIMEOUT = aiohttp.ClientTimeout(total=10)
MAX_PAGES = 100


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
        self.base_url = base_url.rstrip("/")
        self._account = f"{self.base_url}/v1/Account/{auth_id}"
        self._headers = {"Authorization": aiohttp.encode_basic_auth(auth_id, auth_token)}

    async def create_call(self, call: OutboundCall) -> str:
        """Ask Plivo to dial; returns the request uuid that identifies the call until it answers."""
        try:
            async with (
                aiohttp.ClientSession(headers=self._headers, timeout=TIMEOUT) as session,
                session.post(f"{self._account}/Call/", json=call.params()) as response,
            ):
                body = await response.text()
                if response.status >= 400:
                    raise PlivoError(f"create call failed with {response.status}: {body}")
        except (aiohttp.ClientError, TimeoutError) as error:
            raise PlivoError(f"create call did not reach Plivo: {error!r}") from error
        try:
            return str(json.loads(body)["request_uuid"])
        except (ValueError, KeyError, TypeError) as error:
            raise PlivoError(f"create call answered without a request uuid: {body}") from error

    async def list_numbers(self) -> list[AccountNumber]:
        """Every number on the account, following Plivo's pages; entries that are not phone
        numbers are skipped."""
        numbers: list[AccountNumber] = []
        url: str | None = f"{self._account}/Number/?limit=20"
        try:
            async with aiohttp.ClientSession(headers=self._headers, timeout=TIMEOUT) as session:
                for _ in range(MAX_PAGES):
                    if url is None:
                        break
                    async with session.get(url) as response:
                        body = await response.text()
                        if response.status >= 400:
                            raise PlivoError(
                                f"listing numbers failed with {response.status}: {body}"
                            )
                    page = json.loads(body)
                    numbers.extend(account_numbers(page.get("objects") or []))
                    next_path = (page.get("meta") or {}).get("next")
                    url = f"{self.base_url}{next_path}" if next_path else None
        except (aiohttp.ClientError, TimeoutError, ValueError) as error:
            raise PlivoError(f"listing numbers did not reach Plivo: {error!r}") from error
        if url is not None:
            raise PlivoError(f"listing numbers did not end after {MAX_PAGES} pages")
        return numbers

    async def cancel_request(self, request_uuid: str) -> None:
        """Stop a call that has not been answered; gone already is fine."""
        await self._delete(f"{self._account}/Request/{request_uuid}/")

    async def hang_up(self, call_uuid: str) -> None:
        await self._delete(f"{self._account}/Call/{call_uuid}/")

    async def _delete(self, url: str) -> None:
        try:
            async with (
                aiohttp.ClientSession(headers=self._headers, timeout=TIMEOUT) as session,
                session.delete(url) as response,
            ):
                if response.status >= 400 and response.status != 404:
                    body = await response.text()
                    raise PlivoError(f"delete {url} failed with {response.status}: {body}")
        except (aiohttp.ClientError, TimeoutError) as error:
            raise PlivoError(f"delete {url} did not reach Plivo: {error!r}") from error


def account_numbers(entries: list[dict[str, Any]]) -> list[AccountNumber]:
    numbers: list[AccountNumber] = []
    for entry in entries:
        digits = str(entry.get("number") or "").lstrip("+")
        try:
            numbers.append(
                AccountNumber(
                    number=f"+{digits}",
                    alias=entry.get("alias") or None,
                    region=entry.get("region") or None,
                    voice=bool(entry.get("voice_enabled")) and bool(entry.get("active", True)),
                )
            )
        except ValidationError:
            log.warning("skipping an account entry that is not a phone number: %r", digits)
    return numbers
