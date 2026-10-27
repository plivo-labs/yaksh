"""Cartesia speech over its websocket, with word timestamps."""

from pipecat.services.cartesia.tts import CartesiaTTSService, GenerationConfig
from pipecat.transcriptions.language import Language as PipecatLanguage

from yaksh.domain.languages import Language
from yaksh.domain.settings import AppSettings
from yaksh.domain.voices import VoiceSettings
from yaksh.integrations.speech.audio import SAMPLE_RATE, quiet_s
from yaksh.integrations.speech.vendor import TtsVendor

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
            model=settings.cartesia.model,
            voice=voice.id,
            language=PipecatLanguage(language.value),
            generation_config=GenerationConfig(speed=voice.speed),
        ),
        stop_frame_timeout_s=quiet_s(one_shot),
        reconnect_on_error=not one_shot,
    )


TTS = TtsVendor(
    model=lambda settings: settings.cartesia.model,
    service=tts,
    check_voice=lambda _settings: CHECK_VOICE,
)
