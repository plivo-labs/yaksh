"""The ElevenLabs voices on the account, for picking and checking persona voices."""

import json
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import quote

import aiohttp
import pydantic

from truman.domain.errors import UnavailableError
from truman.domain.voices import VoiceInfo

ELEVENLABS_API = "https://api.elevenlabs.io"
TIMEOUT = aiohttp.ClientTimeout(total=10)
PAGE_SIZE = 100
MAX_PAGES = 50
LIST_TTL_S = 300.0


class ElevenLabsCatalog:
    """Lists the account's voices through the paged v2 endpoint, cached for five minutes, and
    looks one up through v1, which has the only single-voice endpoint."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = ELEVENLABS_API,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._headers = {"xi-api-key": api_key}
        self._clock = clock
        self._listed: tuple[float, list[VoiceInfo]] | None = None

    async def list_voices(self) -> list[VoiceInfo]:
        if self._listed is not None and self._clock() - self._listed[0] < LIST_TTL_S:
            return self._listed[1]
        voices = await self._list_all()
        self._listed = (self._clock(), voices)
        return voices

    async def get_voice(self, voice_id: str) -> VoiceInfo | None:
        url = f"{self.base_url}/v1/voices/{quote(voice_id, safe='')}"
        try:
            async with (
                aiohttp.ClientSession(headers=self._headers, timeout=TIMEOUT) as session,
                session.get(url) as response,
            ):
                status, text = response.status, await response.text()
        except (aiohttp.ClientError, TimeoutError, UnicodeDecodeError) as error:
            raise UnavailableError(
                f"the ElevenLabs voice lookup failed: {failure(error)}"
            ) from error
        if status >= 400:
            if voice_not_found(text):
                return None
            raise UnavailableError(
                f"ElevenLabs refused the voice lookup with {status}: {excerpt(text)}"
            )
        return voice_info(parsed(text))

    async def _list_all(self) -> list[VoiceInfo]:
        voices: list[VoiceInfo] = []
        params: dict[str, Any] = {"page_size": PAGE_SIZE}
        try:
            async with aiohttp.ClientSession(headers=self._headers, timeout=TIMEOUT) as session:
                for _ in range(MAX_PAGES):
                    async with session.get(f"{self.base_url}/v2/voices", params=params) as response:
                        status, text = response.status, await response.text()
                    if status >= 400:
                        raise UnavailableError(
                            f"ElevenLabs refused the voice list with {status}: {excerpt(text)}"
                        )
                    page = parsed(text)
                    entries = page.get("voices")
                    if not isinstance(entries, list):
                        raise UnavailableError(
                            f"ElevenLabs sent a voice list without voices: {excerpt(text)}"
                        )
                    voices.extend(voice_info(entry) for entry in entries)
                    if not page.get("has_more"):
                        return voices
                    token = page.get("next_page_token")
                    if not isinstance(token, str) or not token:
                        raise UnavailableError(
                            f"ElevenLabs said more voices follow but sent no page token: "
                            f"{excerpt(text)}"
                        )
                    params = {"page_size": PAGE_SIZE, "next_page_token": token}
        except (aiohttp.ClientError, TimeoutError, UnicodeDecodeError) as error:
            raise UnavailableError(f"the ElevenLabs voice list failed: {failure(error)}") from error
        raise UnavailableError(f"the ElevenLabs voice list did not end after {MAX_PAGES} pages")


def failure(error: Exception) -> str:
    """The error without its repr: aiohttp's repr carries the request headers, and so the key."""
    return f"{type(error).__name__}: {error}"


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


def voice_info(entry: Any) -> VoiceInfo:
    try:
        labels = entry.get("labels") or {}
        return VoiceInfo(
            id=entry["voice_id"],
            name=entry["name"],
            category=entry.get("category"),
            gender=labels.get("gender"),
            accent=labels.get("accent"),
            preview_url=entry.get("preview_url"),
            languages=frozenset(
                verified["language"] for verified in entry.get("verified_languages") or []
            ),
        )
    except (AttributeError, KeyError, TypeError, pydantic.ValidationError) as error:
        raise UnavailableError(
            f"ElevenLabs described a voice in an unknown shape: {excerpt(repr(entry))}"
        ) from error
