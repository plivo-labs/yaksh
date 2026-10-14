"""The Plivo REST calls Yaksh makes: list numbers and link them to an application, list, read,
make and change applications, place a call, cancel one still ringing, hang one up; and, to
import agents, read the account's Plivo CX agent flows."""

import json
import logging
from dataclasses import dataclass
from typing import Any

import aiohttp
from pydantic import ValidationError

from yaksh.diagnostics import describe_exception
from yaksh.domain.errors import ProviderCallError
from yaksh.domain.numbers import AccountNumber, PlivoApplication

log = logging.getLogger(__name__)

PLIVO_API = "https://api.plivo.com"
TIMEOUT = aiohttp.ClientTimeout(total=10)
MAX_PAGES = 100


class PlivoError(ProviderCallError):
    pass


def plivo_reason(body: str) -> str | None:
    """The text of the error field of Plivo's reply, when it is text."""
    try:
        reply = json.loads(body)
    except ValueError:
        return None
    reason = reply.get("error") if isinstance(reply, dict) else None
    if not isinstance(reason, str):
        return None
    return reason.strip() or None


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
            raise PlivoError(
                f"create call did not reach Plivo: {describe_exception(error)}"
            ) from error
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
                                f"listing numbers failed with {response.status}: {body}",
                                status=response.status,
                                reason=plivo_reason(body),
                            )
                    page = json.loads(body)
                    numbers.extend(account_numbers(page.get("objects") or []))
                    next_path = (page.get("meta") or {}).get("next")
                    url = f"{self.base_url}{next_path}" if next_path else None
        except (aiohttp.ClientError, TimeoutError, ValueError) as error:
            raise PlivoError(
                f"listing numbers did not reach Plivo: {describe_exception(error)}"
            ) from error
        if url is not None:
            raise PlivoError(f"listing numbers did not end after {MAX_PAGES} pages")
        return numbers

    async def list_agent_flows(self, *, name: str | None, offset: int) -> dict[str, Any]:
        """One page of the account's active Plivo CX agent flows, newest first, as Plivo returns
        it. A draft or paused flow takes no calls, so it is left out."""
        params: dict[str, str | int] = {"limit": 20, "offset": offset, "state": "ACTIVE"}
        if name:
            params["name"] = name
        return json.loads(await self._get(f"{self._account}/AgentFlow/", params, "listing flows"))

    async def get_agent_flow(self, flow_id: str) -> str:
        """One Plivo CX agent flow with its nodes, as the text Plivo returns."""
        return await self._get(f"{self._account}/AgentFlow/{flow_id}/", {}, "reading the flow")

    async def agent_flow_applications(self) -> dict[str, str]:
        """The answer URL of each application that sends a number's calls to a Plivo CX agent
        flow, by application id. Plivo CX makes them internal, and only internal=true lists
        them."""
        found: dict[str, str] = {}
        params: dict[str, str | int] = {"app_name": "agent_flow_", "internal": "true", "limit": 20}
        for page in range(MAX_PAGES):
            listed = json.loads(
                await self._get(
                    f"{self._account}/Application/",
                    {**params, "offset": page * 20},
                    "listing applications",
                )
            )
            for entry in listed.get("objects") or []:
                found[str(entry.get("app_id"))] = str(entry.get("answer_url") or "")
            if not (listed.get("meta") or {}).get("next"):
                return found
        raise PlivoError(f"listing applications did not end after {MAX_PAGES} pages")

    async def _get(self, url: str, params: dict[str, str | int], doing: str) -> str:
        try:
            async with (
                aiohttp.ClientSession(headers=self._headers, timeout=TIMEOUT) as session,
                session.get(url, params=params) as response,
            ):
                body = await response.text()
        except (aiohttp.ClientError, TimeoutError) as error:
            raise PlivoError(f"{doing} did not reach Plivo: {describe_exception(error)}") from error
        if response.status >= 400:
            raise PlivoError(
                f"{doing} failed with {response.status}: {body}",
                status=response.status,
                reason=plivo_reason(body),
            )
        return body

    async def get_application(self, app_id: str) -> PlivoApplication:
        url = f"{self._account}/Application/{app_id}/"
        try:
            async with (
                aiohttp.ClientSession(headers=self._headers, timeout=TIMEOUT) as session,
                session.get(url) as response,
            ):
                body = await response.text()
                if response.status >= 400:
                    raise PlivoError(
                        f"reading application {app_id} failed with {response.status}: {body}",
                        status=response.status,
                        reason=plivo_reason(body),
                    )
            return plivo_application(json.loads(body))
        except (aiohttp.ClientError, TimeoutError, ValueError, KeyError, TypeError) as error:
            raise PlivoError(
                f"reading application {app_id} did not work: {describe_exception(error)}"
            ) from error

    async def list_applications(self) -> list[PlivoApplication]:
        """The account's applications, following Plivo's pages."""
        found: list[PlivoApplication] = []
        for page_number in range(MAX_PAGES):
            body = await self._get(
                f"{self._account}/Application/",
                {"limit": 20, "offset": page_number * 20},
                "listing applications",
            )
            try:
                page = json.loads(body)
                found.extend(plivo_application(entry) for entry in page.get("objects") or [])
            except (ValueError, KeyError, TypeError, AttributeError) as error:
                raise PlivoError(
                    f"listing applications answered with an unreadable page: "
                    f"{describe_exception(error)}"
                ) from error
            if not (page.get("meta") or {}).get("next"):
                return found
        raise PlivoError(f"listing applications did not end after {MAX_PAGES} pages")

    async def create_application(self, name: str, answer_url: str, hangup_url: str) -> str:
        """Make an application that sends calls to the URLs; returns its id."""
        body = await self._post(
            f"{self._account}/Application/",
            {"app_name": name, **receiving_params(answer_url, hangup_url)},
            f"making application {name}",
        )
        try:
            return str(json.loads(body)["app_id"])
        except (ValueError, KeyError, TypeError) as error:
            raise PlivoError(f"making application {name} answered without an id: {body}") from error

    async def update_application(self, app_id: str, answer_url: str, hangup_url: str) -> None:
        await self._post(
            f"{self._account}/Application/{app_id}/",
            receiving_params(answer_url, hangup_url),
            f"changing application {app_id}",
        )

    async def link_number(self, number: str, app_id: str | None) -> None:
        """Link the number to the application; None removes its application. Plivo takes an
        empty app_id for that."""
        await self._post(
            f"{self._account}/Number/{number.lstrip('+')}/",
            {"app_id": app_id or ""},
            f"linking {number}",
        )

    async def _post(self, url: str, params: dict[str, str], doing: str) -> str:
        try:
            async with (
                aiohttp.ClientSession(headers=self._headers, timeout=TIMEOUT) as session,
                session.post(url, json=params) as response,
            ):
                body = await response.text()
        except (aiohttp.ClientError, TimeoutError) as error:
            raise PlivoError(f"{doing} did not reach Plivo: {describe_exception(error)}") from error
        if response.status >= 400:
            raise PlivoError(
                f"{doing} failed with {response.status}: {body}",
                status=response.status,
                reason=plivo_reason(body),
            )
        return body

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
            raise PlivoError(
                f"delete {url} did not reach Plivo: {describe_exception(error)}"
            ) from error


def receiving_params(answer_url: str, hangup_url: str) -> dict[str, str]:
    return {
        "answer_url": answer_url,
        "answer_method": "POST",
        "hangup_url": hangup_url,
        "hangup_method": "POST",
    }


def plivo_application(entry: dict[str, Any]) -> PlivoApplication:
    app_id = str(entry["app_id"])
    return PlivoApplication(
        app_id=app_id,
        name=str(entry.get("app_name") or app_id),
        answer_url=str(entry.get("answer_url") or ""),
        answer_method=str(entry.get("answer_method") or ""),
        hangup_url=str(entry.get("hangup_url") or ""),
        hangup_method=str(entry.get("hangup_method") or ""),
    )


def application_id(uri: object) -> str | None:
    """The id at the end of an application URI such as /v1/Account/MA../Application/123/."""
    if not isinstance(uri, str) or "/Application/" not in uri:
        return None
    return uri.rstrip("/").rsplit("/", 1)[-1] or None


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
                    application_id=application_id(entry.get("application")),
                )
            )
        except ValidationError:
            log.warning("skipping an account entry that is not a phone number: %r", digits)
    return numbers
