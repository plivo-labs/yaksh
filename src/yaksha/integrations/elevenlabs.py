"""ElevenLabs voice lookup and speech, for adding voices and playing previews."""

import io
import json
import wave
from typing import Any
from urllib.parse import quote

import aiohttp
import pydantic

from yaksha.diagnostics import describe_exception
from yaksha.domain.errors import UnavailableError
from yaksha.domain.languages import Language
from yaksha.domain.voices import ProviderVoice, VoiceGender, VoiceSettings

ELEVENLABS_API = "https://api.elevenlabs.io"
TIMEOUT = aiohttp.ClientTimeout(total=10)
SPEECH_TIMEOUT = aiohttp.ClientTimeout(total=20)
MODEL = "eleven_flash_v2_5"
CALL_AUDIO = "pcm_8000"

LANGUAGE_PINS: dict[Language, str] = {
    Language.EN: "en",
    Language.HI: "hi",
}


class ElevenLabsClient:
    """Looks up one voice through v1, which has the only single-voice endpoint, and makes
    speech in the 8 kHz format a call uses."""

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

    async def speak(self, voice: VoiceSettings, language: Language, text: str) -> bytes | None:
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
                language for language, code in LANGUAGE_PINS.items() if code in codes
            ),
        )
    except (AttributeError, KeyError, TypeError, pydantic.ValidationError) as error:
        raise UnavailableError(
            f"ElevenLabs described a voice in an unknown shape: {excerpt(repr(entry))}"
        ) from error
