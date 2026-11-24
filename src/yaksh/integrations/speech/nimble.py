"""Nimble, Plivo's text-to-speech: Pipecat's Plivo service over its Realtime API, and the
account's voices."""

import base64
import json
from collections.abc import Sequence
from typing import Any

import aiohttp
from pipecat.services.plivo.tts import PlivoTTSService
from pipecat.transcriptions.language import Language as PipecatLanguage

from yaksh.diagnostics import describe_exception
from yaksh.domain.errors import UnavailableError
from yaksh.domain.languages import Language
from yaksh.domain.settings import AppSettings
from yaksh.domain.voices import (
    CatalogPage,
    CatalogQuery,
    ProviderVoice,
    VoiceGender,
    VoiceProvider,
    VoiceSettings,
)
from yaksh.integrations.speech.audio import SAMPLE_RATE, quiet_s
from yaksh.integrations.speech.catalog import page_of
from yaksh.integrations.speech.vendor import TtsVendor

LANGUAGES = VoiceProvider.NIMBLE.traits.languages
"""The languages Nimble pins; it speaks no other of Yaksh's."""
NAMED = LANGUAGES - {Language.EN}
"""The languages sent by name. Nimble takes English only with its region, which Yaksh's English
does not have, so English goes with no language: Nimble reads it in the voice's own region."""
TIMEOUT = aiohttp.ClientTimeout(total=10)


def websocket_of(base_url: str) -> str:
    """The gateway's websocket address: wss for https, ws for http."""
    scheme, rest = base_url.rstrip("/").split("://", 1)
    return f"{'wss' if scheme == 'https' else 'ws'}://{rest}"


def basic_auth(credential: str) -> str:
    """`credential` is the Auth ID and Auth token as `id:token`, as Basic auth sends them."""
    return "Basic " + base64.b64encode(credential.encode()).decode()


def tts(
    settings: AppSettings,
    voice: VoiceSettings,
    language: Language,
    key: str,
    *,
    one_shot: bool,
    also: Sequence[Language] = (),
) -> PlivoTTSService:
    """A one-shot service does not reconnect: a dropped socket fails the speech instead of
    ending it short as finished. A caller that can switch languages sends no language, so
    Nimble finds the language of each sentence."""
    auth_id, _, auth_token = key.partition(":")
    spoken = PipecatLanguage(language.value) if language in NAMED and not also else None
    return PlivoTTSService(
        auth_id=auth_id,
        auth_token=auth_token,
        url=websocket_of(settings.nimble.base_url),
        sample_rate=SAMPLE_RATE,
        settings=PlivoTTSService.Settings(voice=voice.id, language=spoken, speed=voice.speed),
        stop_frame_timeout_s=quiet_s(one_shot),
        reconnect_on_error=not one_shot,
    )


async def voices(settings: AppSettings, key: str) -> list[ProviderVoice]:
    """The voices the account can use; this also proves the Auth ID, the token and that this
    server's IP is allowed."""
    auth_id = key.partition(":")[0]
    url = f"{settings.nimble.base_url.rstrip('/')}/v1/Account/{auth_id}/TTS/Voices"
    try:
        async with (
            aiohttp.ClientSession(timeout=TIMEOUT) as session,
            session.get(url, headers={"Authorization": basic_auth(key)}) as response,
        ):
            status, body = response.status, await response.text()
    except (aiohttp.ClientError, TimeoutError) as error:
        raise UnavailableError(f"Nimble did not answer: {describe_exception(error)}") from None
    if status == 401:
        raise UnavailableError(
            "Nimble refused the Auth ID and token (401); check them, and this server's IP on the "
            "account's IP allow list"
        )
    if status >= 400:
        raise UnavailableError(f"Nimble answered {status}")
    try:
        listed = json.loads(body)["objects"]
    except ValueError, KeyError, TypeError:
        raise UnavailableError("Nimble sent a voice list that is not JSON") from None
    return [provider_voice(entry) for entry in listed]


def provider_voice(entry: dict[str, Any]) -> ProviderVoice:
    """English is listed with its region, such as `en-IN`: it is Yaksh's English."""
    gender = entry.get("gender")
    codes = {code.split("-")[0] for code in entry.get("languages", [])}
    return ProviderVoice(
        id=entry["voice_id"],
        name=entry.get("name") or entry["voice_id"],
        gender=VoiceGender(gender) if gender in {"male", "female"} else None,
        accent=entry.get("accent_type"),
        listed_languages=tuple(
            language for language in Language if language in LANGUAGES and language in codes
        ),
    )


async def lookup(settings: AppSettings, key: str, voice_id: str) -> ProviderVoice | None:
    return next((voice for voice in await voices(settings, key) if voice.id == voice_id), None)


async def check_voice(settings: AppSettings, key: str) -> str:
    """The first voice the account lists: the roster differs between gateways."""
    listed = await voices(settings, key)
    if not listed:
        raise UnavailableError("the Nimble account lists no voices")
    return listed[0].id


async def catalog(settings: AppSettings, key: str, query: CatalogQuery) -> CatalogPage:
    return page_of(await voices(settings, key), query)


TTS = TtsVendor(service=tts, check_voice=check_voice, catalog=catalog, lookup=lookup)
