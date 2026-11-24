"""Koyal, Plivo's text to speech: Pipecat's Plivo service over its Realtime API, and the
account's voices."""

from collections.abc import Sequence
from typing import Any

import aiohttp
from pipecat.services.plivo.tts import PlivoTTSService
from pipecat.transcriptions.language import Language as PipecatLanguage

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
from yaksh.integrations.speech.catalog import get_json, page_of
from yaksh.integrations.speech.vendor import TtsVendor

LANGUAGES = VoiceProvider.PLIVO.traits.languages
"""The languages Koyal speaks; it speaks no other of Yaksh's."""
NAMED = LANGUAGES - {Language.EN}
"""The languages sent by name. Koyal takes English only with its region, which Yaksh's English
does not have, so English goes with no language: Koyal reads it in the voice's own region."""


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
    Koyal finds the language of each sentence."""
    auth_id, _, auth_token = key.partition(":")
    spoken = PipecatLanguage(language.value) if language in NAMED and not also else None
    return PlivoTTSService(
        auth_id=auth_id,
        auth_token=auth_token,
        # https://host is wss://host.
        url=settings.plivo_tts.base_url.rstrip("/").replace("http", "ws", 1),
        sample_rate=SAMPLE_RATE,
        settings=PlivoTTSService.Settings(
            model=voice.model_in_use.id, voice=voice.id, language=spoken, speed=voice.speed
        ),
        stop_frame_timeout_s=quiet_s(one_shot),
        reconnect_on_error=not one_shot,
    )


async def voices(settings: AppSettings, key: str) -> list[ProviderVoice]:
    """The voices the account can use; this also proves the Auth ID, the token and that this
    server's IP is allowed."""
    auth_id, _, auth_token = key.partition(":")
    url = f"{settings.plivo_tts.base_url.rstrip('/')}/v1/Account/{auth_id}/TTS/Voices"
    headers = {"Authorization": aiohttp.encode_basic_auth(auth_id, auth_token)}
    body = await get_json("Plivo", url, {}, headers)
    try:
        return [provider_voice(entry) for entry in body["objects"]]
    except (KeyError, TypeError, ValueError) as error:
        raise UnavailableError(f"Plivo sent a voice list in an unknown shape: {error}") from None


def provider_voice(entry: dict[str, Any]) -> ProviderVoice:
    """English is listed with its region, such as `en-IN`: it is Yaksh's English."""
    codes = {code.split("-")[0] for code in entry["languages"]}
    return ProviderVoice(
        id=entry["voice_id"],
        name=entry["name"],
        gender=VoiceGender(entry["gender"]),
        accent=entry["accent_type"],
        listed_languages=tuple(
            language for language in Language if language in LANGUAGES and language in codes
        ),
    )


async def lookup(settings: AppSettings, key: str, voice_id: str) -> ProviderVoice | None:
    return next((voice for voice in await voices(settings, key) if voice.id == voice_id), None)


async def check_voice(settings: AppSettings, key: str) -> str:
    """The first voice the account lists: the roster differs between addresses."""
    listed = await voices(settings, key)
    if not listed:
        raise UnavailableError("the Plivo account lists no voices")
    return listed[0].id


async def catalog(settings: AppSettings, key: str, query: CatalogQuery) -> CatalogPage:
    return page_of(await voices(settings, key), query)


TTS = TtsVendor(service=tts, check_voice=check_voice, catalog=catalog, lookup=lookup)
