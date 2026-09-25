"""The ElevenLabs voices on the account, for picking and checking persona voices."""

import io
import json
import time
import wave
from collections.abc import Callable
from typing import Any
from urllib.parse import quote

import aiohttp
import pydantic

from truman.diagnostics import describe_exception
from truman.domain.errors import UnavailableError
from truman.domain.personas import Language, Voice
from truman.domain.voices import VoiceInfo

ELEVENLABS_API = "https://api.elevenlabs.io"
TIMEOUT = aiohttp.ClientTimeout(total=10)
PAGE_SIZE = 100
MAX_PAGES = 50
LIST_TTL_S = 300.0
SPEECH_TIMEOUT = aiohttp.ClientTimeout(total=20)
MODEL = "eleven_flash_v2_5"
CALL_AUDIO = "pcm_8000"

LANGUAGE_PINS: dict[Language, str] = {
    Language.EN: "en",
    Language.HINGLISH: "hi",
}


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

    async def list_voices(self, language: Language | None = None) -> list[VoiceInfo]:
        """The account's voices; with a language, only those ElevenLabs verified for it.
        Hinglish counts as Hindi."""
        if self._listed is None or self._clock() - self._listed[0] >= LIST_TTL_S:
            self._listed = (self._clock(), await self._list_all())
        voices = self._listed[1]
        if language is None:
            return voices
        code = LANGUAGE_PINS[language]
        return [voice for voice in voices if code in voice.languages]

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
                f"the ElevenLabs voice lookup failed: {describe_exception(error)}"
            ) from error
        if status >= 400:
            if voice_not_found(text):
                return None
            raise UnavailableError(
                f"ElevenLabs refused the voice lookup with {status}: {excerpt(text)}"
            )
        return voice_info(parsed(text))

    async def speak(self, voice: Voice, language: Language, text: str) -> bytes | None:
        body: dict[str, Any] = {
            "text": text,
            "model_id": MODEL,
            "voice_settings": {"speed": voice.speed, "stability": voice.stability},
            "language_code": LANGUAGE_PINS[language],
        }
        url = f"{self.base_url}/v1/text-to-speech/{quote(voice.id, safe='')}"
        try:
            async with (
                aiohttp.ClientSession(headers=self._headers, timeout=SPEECH_TIMEOUT) as session,
                session.post(url, params={"output_format": CALL_AUDIO}, json=body) as response,
            ):
                if response.status < 400:
                    return as_wav(await response.read())
                status, text_body = response.status, await response.text()
        except (aiohttp.ClientError, TimeoutError, UnicodeDecodeError) as error:
            raise UnavailableError(
                f"the ElevenLabs speech request failed: {describe_exception(error)}"
            ) from error
        if voice_not_found(text_body):
            return None
        raise UnavailableError(
            f"ElevenLabs refused the speech request with {status}: {excerpt(text_body)}"
        )

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
            raise UnavailableError(
                f"the ElevenLabs voice list failed: {describe_exception(error)}"
            ) from error
        raise UnavailableError(f"the ElevenLabs voice list did not end after {MAX_PAGES} pages")


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


def as_wav(pcm: bytes) -> bytes:
    """8 kHz 16-bit mono PCM, the audio a call gets, in a WAV container a browser can play."""
    out = io.BytesIO()
    with wave.open(out, "wb") as file:
        file.setnchannels(1)
        file.setsampwidth(2)
        file.setframerate(8000)
        file.writeframes(pcm)
    return out.getvalue()


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
