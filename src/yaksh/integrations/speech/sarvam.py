"""Sarvam: saaras speech-to-text over its streaming websocket, and bulbul speech over HTTP.
Speech goes over HTTP because that service sends each sentence's text after its audio, as
Yaksh's transcript needs; Sarvam's websocket service sends the text first. The speech-to-text
service sends no partials, and one final for each utterance, when Yaksh's VAD has heard the
agent stop: so `SttTraits.words_while_speaking` is false."""

from typing import Any

import aiohttp
from pipecat.services.sarvam.stt import SarvamSTTService
from pipecat.services.sarvam.tts import TTS_MODEL_CONFIGS, SarvamHttpTTSService
from pipecat.transcriptions.language import Language as PipecatLanguage

from yaksh.domain.languages import Language
from yaksh.domain.settings import AppSettings
from yaksh.domain.voices import VoiceSettings
from yaksh.integrations.speech.audio import SAMPLE_RATE, quiet_s
from yaksh.integrations.speech.vendor import SttVendor, TtsVendor


def stt(settings: AppSettings, key: str, language: str) -> SarvamSTTService:
    return SarvamSTTService(
        api_key=key,
        sample_rate=SAMPLE_RATE,
        settings=SarvamSTTService.Settings(
            model=settings.sarvam_stt.model, language=PipecatLanguage(language)
        ),
    )


class SarvamHttpTts(SarvamHttpTTSService):
    """Sarvam's speech over HTTP with its own session, closed with the service. The model is
    checked before the session opens, so a model Sarvam does not have leaves no session open."""

    def __init__(self, *, settings: SarvamHttpTTSService.Settings, **kwargs: Any) -> None:
        if settings.model not in TTS_MODEL_CONFIGS:
            raise ValueError(f"Sarvam has no speech model {settings.model}")
        self._own_session = aiohttp.ClientSession()
        super().__init__(aiohttp_session=self._own_session, settings=settings, **kwargs)

    async def cleanup(self) -> None:
        await super().cleanup()
        await self._own_session.close()


def tts(
    settings: AppSettings, voice: VoiceSettings, language: Language, key: str, *, one_shot: bool
) -> SarvamHttpTts:
    """At 8 kHz, which the service must be told: left out, Sarvam answers at 24 kHz."""
    return SarvamHttpTts(
        api_key=key,
        base_url=settings.sarvam_tts.base_url,
        sample_rate=SAMPLE_RATE,
        settings=SarvamHttpTTSService.Settings(
            model=settings.sarvam_tts.model,
            voice=voice.id,
            language=PipecatLanguage(language.value),
            pace=voice.speed,
        ),
        stop_frame_timeout_s=quiet_s(one_shot),
    )


async def check_voice(settings: AppSettings, _key: str) -> str:
    """The speaker Pipecat uses for the model: bulbul:v3 and bulbul:v4-flash name their
    speakers differently."""
    model = settings.sarvam_tts.model
    return TTS_MODEL_CONFIGS.get(model, TTS_MODEL_CONFIGS["bulbul:v4-flash"]).default_speaker


STT = SttVendor(model=lambda settings: settings.sarvam_stt.model, service=stt)
TTS = TtsVendor(
    model=lambda settings: settings.sarvam_tts.model, service=tts, check_voice=check_voice
)
