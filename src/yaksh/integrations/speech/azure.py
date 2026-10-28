"""Azure AI Speech, with word boundaries for timing, at 8 kHz with Azure's equalizer for
narrowband telephone audio."""

import time
from typing import Any

import pydantic
from pipecat.services.azure.tts import AzureTTSService
from pipecat.transcriptions.language import Language as PipecatLanguage

from yaksh.domain.errors import UnavailableError
from yaksh.domain.languages import Language
from yaksh.domain.settings import AppSettings
from yaksh.domain.voices import CatalogPage, CatalogQuery, ProviderVoice, VoiceGender, VoiceSettings
from yaksh.integrations.speech.audio import SAMPLE_RATE, quiet_s
from yaksh.integrations.speech.catalog import get_json, page_of
from yaksh.integrations.speech.vendor import TtsVendor

CHECK_VOICE = "en-US-SaraNeural"
"""A voice every Azure Speech resource has: Pipecat's default."""
TELEPHONE_EFFECT = "eq_telecomhp8k"


def tts(
    settings: AppSettings, voice: VoiceSettings, language: Language, key: str, *, one_shot: bool
) -> AzureTTSService:
    """The speed is SSML's prosody rate, a multiple of the voice's own pace."""
    return AzureTTSService(
        api_key=key,
        region=settings.azure.region,
        sample_rate=SAMPLE_RATE,
        settings=AzureTTSService.Settings(
            voice=voice.id,
            language=PipecatLanguage(language.value),
            rate=f"{voice.speed:g}",
            effect=TELEPHONE_EFFECT,
        ),
        stop_frame_timeout_s=quiet_s(one_shot),
    )


async def check_voice(_settings: AppSettings, _key: str) -> str:
    return CHECK_VOICE


VOICE_LISTS: dict[tuple[str, str], tuple[float, list[ProviderVoice]]] = {}
"""Each region's voices by key, with when they were listed: Azure sends its whole list, over
500 voices, and the dialog asks for a page at each search."""
LIST_FOR_S = 3600.0
VOICE_LIST_URL = "https://{region}.tts.speech.microsoft.com/cognitiveservices/voices/list"


async def catalog(settings: AppSettings, key: str, query: CatalogQuery) -> CatalogPage:
    return page_of(await region_voices(settings.azure.region, key), query)


async def region_voices(region: str, key: str) -> list[ProviderVoice]:
    """The region's voices that speak a language of Yaksh's."""
    listed = VOICE_LISTS.get((region, key))
    if listed is not None and time.monotonic() - listed[0] < LIST_FOR_S:
        return listed[1]
    url = VOICE_LIST_URL.format(region=region)
    body = await get_json("Azure", url, {}, {"Ocp-Apim-Subscription-Key": key})
    if not isinstance(body, list):
        raise UnavailableError("Azure sent a voice list in an unknown shape")
    voices = [voice for voice in map(azure_voice, body) if voice.listed_languages]
    VOICE_LISTS[(region, key)] = (time.monotonic(), voices)
    return voices


def azure_voice(entry: Any) -> ProviderVoice:
    """The voice's name holds its model, as in en-US-Ava:DragonHDLatestNeural."""
    try:
        locales = [entry.get("Locale"), *(entry.get("SecondaryLocaleList") or [])]
        codes = {str(locale).split("-")[0].lower() for locale in locales if locale}
        gender = str(entry.get("Gender") or "").lower()
        return ProviderVoice(
            id=entry["ShortName"],
            name=entry.get("LocalName") or entry.get("DisplayName") or entry["ShortName"],
            gender=VoiceGender(gender) if gender in VoiceGender else None,
            accent=entry.get("LocaleName"),
            listed_languages=tuple(language for language in Language if language.value in codes),
        )
    except (AttributeError, KeyError, TypeError, pydantic.ValidationError) as error:
        raise UnavailableError(f"Azure described a voice in an unknown shape: {error}") from None


TTS = TtsVendor(service=tts, check_voice=check_voice, catalog=catalog)
