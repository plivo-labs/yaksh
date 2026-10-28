"""ElevenLabs voice lookup, for adding voices; the language pin of its speech; and, to import
agents, reads of a workspace's ElevenLabs agents with its own key."""

import json
from typing import Any
from urllib.parse import quote

import aiohttp
import pydantic

from yaksh.diagnostics import describe_exception
from yaksh.domain.agent_import import ElevenLabsRegion
from yaksh.domain.errors import ProviderCallError, UnavailableError
from yaksh.domain.languages import Language
from yaksh.domain.voices import ProviderVoice, VoiceGender

ELEVENLABS_API = "https://api.elevenlabs.io"
REGION_APIS: dict[ElevenLabsRegion, str] = {
    ElevenLabsRegion.GLOBAL: ELEVENLABS_API,
    ElevenLabsRegion.EU: "https://api.eu.residency.elevenlabs.io",
    ElevenLabsRegion.IN: "https://api.in.residency.elevenlabs.io",
    ElevenLabsRegion.SG: "https://api.sg.residency.elevenlabs.io",
}
TIMEOUT = aiohttp.ClientTimeout(total=10)

LANGUAGE_CODES: dict[Language, str] = {
    Language.EN: "en",
    Language.HI: "hi",
    Language.BN: "bn",
    Language.GU: "gu",
    Language.KN: "kn",
    Language.MR: "mr",
    Language.TA: "ta",
    Language.TE: "te",
    Language.ES: "es",
}
"""ElevenLabs' code for each language, as a voice lists the languages it is verified in."""


class ElevenLabsClient:
    """Looks up one voice through v1, which has the only single-voice endpoint."""

    def __init__(self, api_key: str, *, base_url: str = ELEVENLABS_API) -> None:
        self.base_url = base_url.rstrip("/")
        self._headers = {"xi-api-key": api_key}

    async def get_voice(self, voice_id: str) -> ProviderVoice | None:
        """None when the account does not have the voice. A Voice Library voice counts only
        after it is added to the account."""
        url = f"{self.base_url}/v1/voices/{quote(voice_id, safe='')}"
        try:
            async with (
                aiohttp.ClientSession(headers=self._headers, timeout=TIMEOUT) as session,
                session.get(url) as response,
            ):
                status, text = response.status, await response.text()
        except (aiohttp.ClientError, TimeoutError, UnicodeDecodeError) as error:
            raise UnavailableError(
                f"the ElevenLabs voice lookup failed: {describe_exception(error)}"
            ) from error
        if status >= 400:
            if voice_not_found(text):
                return None
            raise UnavailableError(
                f"ElevenLabs refused the voice lookup with {status}: {excerpt(text)}"
            )
        return provider_voice(parsed(text))


class ElevenLabsError(ProviderCallError):
    pass


class ElevenLabsAgentsApi:
    def __init__(self, api_key: str, *, base_url: str = ELEVENLABS_API) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self._headers = {"xi-api-key": api_key}

    async def list_agents(self, *, name: str | None, cursor: str | None) -> dict[str, Any]:
        params = {"page_size": "50", "archived": "false"}
        if name:
            params["search"] = name
        if cursor:
            params["cursor"] = cursor
        return await self._get("/v1/convai/agents", params, "listing agents")

    async def get_agent(self, agent_id: str) -> dict[str, Any]:
        return await self._get(
            f"/v1/convai/agents/{quote(agent_id, safe='')}", {}, "reading the agent"
        )

    async def get_tool(self, tool_id: str) -> dict[str, Any]:
        return await self._get(f"/v1/convai/tools/{quote(tool_id, safe='')}", {}, "reading a tool")

    async def outbound_numbers(self) -> list[dict[str, Any]]:
        """The first page, up to 100 numbers: an import needs one."""
        page = await self._get(
            "/v1/convai/v2/phone-numbers",
            {"supports_outbound": "true", "page_size": "100"},
            "listing numbers",
        )
        return list(page.get("phone_numbers") or [])

    async def _get(self, path: str, params: dict[str, str], doing: str) -> dict[str, Any]:
        try:
            async with (
                aiohttp.ClientSession(headers=self._headers, timeout=TIMEOUT) as session,
                session.get(f"{self.base_url}{path}", params=params) as response,
            ):
                status, body = response.status, await response.text()
        except (aiohttp.ClientError, TimeoutError, UnicodeDecodeError) as error:
            raise ElevenLabsError(
                f"{doing} did not reach ElevenLabs: {describe_exception(error)}"
            ) from error
        if status >= 400:
            raise ElevenLabsError(f"{doing} failed with {status}: {excerpt(body)}", status=status)
        found = json.loads(body)
        if not isinstance(found, dict):
            raise ValueError(f"{doing} answered with a body that is not an object")
        return found


def excerpt(text: str) -> str:
    return text[:200]


def parsed(text: str) -> dict[str, Any]:
    try:
        body = json.loads(text)
    except ValueError as error:
        raise UnavailableError(
            f"ElevenLabs sent a body that is not JSON: {excerpt(text)}"
        ) from error
    if not isinstance(body, dict):
        raise UnavailableError(f"ElevenLabs sent a body that is not an object: {excerpt(text)}")
    return body


def voice_not_found(text: str) -> bool:
    try:
        detail = json.loads(text).get("detail")
    except ValueError, AttributeError:
        return False
    return isinstance(detail, dict) and detail.get("code") == "voice_not_found"


def provider_voice(entry: Any) -> ProviderVoice:
    try:
        labels = entry.get("labels") or {}
        gender = str(labels.get("gender") or "").lower()
        codes = {verified["language"] for verified in entry.get("verified_languages") or []}
        return ProviderVoice(
            id=entry["voice_id"],
            name=entry["name"],
            gender=VoiceGender(gender) if gender in VoiceGender else None,
            accent=labels.get("accent"),
            listed_languages=tuple(
                language for language, code in LANGUAGE_CODES.items() if code in codes
            ),
        )
    except (AttributeError, KeyError, TypeError, pydantic.ValidationError) as error:
        raise UnavailableError(
            f"ElevenLabs described a voice in an unknown shape: {excerpt(repr(entry))}"
        ) from error
