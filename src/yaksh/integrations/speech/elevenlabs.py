"""ElevenLabs speech over its websocket, with word timestamps; a data residency address keeps
the speech in its region."""

from pipecat.services.elevenlabs.tts import ElevenLabsTTSService

from yaksh.domain.languages import Language
from yaksh.domain.settings import AppSettings
from yaksh.domain.voices import VoiceSettings
from yaksh.integrations.elevenlabs import language_pin
from yaksh.integrations.speech.audio import SAMPLE_RATE, quiet_s
from yaksh.integrations.speech.vendor import TtsVendor


def tts(
    settings: AppSettings, voice: VoiceSettings, language: Language, key: str, *, one_shot: bool
) -> ElevenLabsTTSService:
    """A one-shot service does not reconnect: a dropped socket fails the speech instead of
    ending it short as finished."""
    return ElevenLabsTTSService(
        api_key=key,
        url=settings.elevenlabs.url,
        sample_rate=SAMPLE_RATE,
        settings=ElevenLabsTTSService.Settings(
            model=settings.elevenlabs.model,
            voice=voice.id,
            speed=voice.speed,
            stability=voice.stability,
            language=language_pin(language),
        ),
        stop_frame_timeout_s=quiet_s(one_shot),
        reconnect_on_error=not one_shot,
    )


TTS = TtsVendor(model=lambda settings: settings.elevenlabs.model, service=tts, check_voice=None)
