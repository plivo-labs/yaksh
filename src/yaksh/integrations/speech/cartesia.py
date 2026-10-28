"""Cartesia speech over its websocket, with word timestamps, and its voice list."""

from typing import Any

import pydantic
from pipecat.services.cartesia.tts import CartesiaTTSService, GenerationConfig
from pipecat.transcriptions.language import Language as PipecatLanguage

from yaksh.domain.errors import UnavailableError
from yaksh.domain.languages import Language
from yaksh.domain.settings import AppSettings
from yaksh.domain.voices import (
    CatalogPage,
    CatalogQuery,
    ProviderVoice,
    VoiceGender,
    VoiceSettings,
)
from yaksh.integrations.speech.audio import SAMPLE_RATE, quiet_s
from yaksh.integrations.speech.catalog import PAGE_SIZE, get_json, rest_address
from yaksh.integrations.speech.vendor import TtsVendor

API_VERSION = "2026-08-14"
"""The Cartesia-Version that its voice list takes."""
GENDERS = {
    VoiceGender.MALE: "masculine",
    VoiceGender.FEMALE: "feminine",
    VoiceGender.NEUTRAL: "gender_neutral",
}

CHECK_VOICE = "86e30c1d-714b-4074-a1f2-1cb6b552fb49"
"""A voice every Cartesia account has: the one Pipecat's project template uses."""


def tts(
    settings: AppSettings, voice: VoiceSettings, language: Language, key: str, *, one_shot: bool
) -> CartesiaTTSService:
    """A one-shot service does not reconnect: a dropped socket fails the speech instead of
    ending it short as finished."""
    return CartesiaTTSService(
        api_key=key,
        url=settings.cartesia.url,
        sample_rate=SAMPLE_RATE,
        settings=CartesiaTTSService.Settings(
            model=voice.model_in_use.id,
            voice=voice.id,
            language=PipecatLanguage(language.value),
            generation_config=GenerationConfig(speed=voice.speed),
        ),
        stop_frame_timeout_s=quiet_s(one_shot),
        reconnect_on_error=not one_shot,
    )


async def check_voice(_settings: AppSettings, _key: str) -> str:
    return CHECK_VOICE


async def catalog(settings: AppSettings, key: str, query: CatalogQuery) -> CatalogPage:
    """At the host of the checked address; each page starts after the last voice of the one
    before."""
    params = {"limit": str(PAGE_SIZE)}
    if query.search:
        params["q"] = query.search
    if query.gender:
        params["gender"] = GENDERS[query.gender]
    if query.language:
        params["language"] = query.language.value
    if query.cursor:
        params["starting_after"] = query.cursor
    headers = {"Authorization": f"Bearer {key}", "Cartesia-Version": API_VERSION}
    url = f"{rest_address(settings.cartesia.url)}/voices"
    body = await get_json("Cartesia", url, params, headers)
    if not isinstance(body, dict):
        raise UnavailableError("Cartesia sent a voice list in an unknown shape")
    items = [cartesia_voice(entry) for entry in body.get("data") or []]
    more = bool(body.get("has_more")) and bool(items)
    return CatalogPage(items=items, next_cursor=items[-1].id if more else None)


def cartesia_voice(entry: Any) -> ProviderVoice:
    try:
        accents = entry.get("accents") or []
        locales = [accent.get("locale") for accent in accents] + [entry.get("language")]
        codes = {str(locale).split("-")[0].lower() for locale in locales if locale}
        native = next((accent.get("accent") for accent in accents if accent.get("is_native")), None)
        return ProviderVoice(
            id=entry["id"],
            name=entry["name"],
            gender=next((g for g, value in GENDERS.items() if value == entry.get("gender")), None),
            accent=native,
            listed_languages=tuple(language for language in Language if language.value in codes),
        )
    except (AttributeError, KeyError, TypeError, pydantic.ValidationError) as error:
        raise UnavailableError(f"Cartesia described a voice in an unknown shape: {error}") from None


TTS = TtsVendor(service=tts, check_voice=check_voice, catalog=catalog)
