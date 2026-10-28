"""ElevenLabs speech over its websocket, with word timestamps; a data residency address keeps
the speech in its region."""

from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
from pipecat.transcriptions.language import Language as PipecatLanguage

from yaksh.domain.languages import Language
from yaksh.domain.settings import AppSettings
from yaksh.domain.voices import ProviderVoice, VoiceSettings
from yaksh.integrations.elevenlabs import ElevenLabsClient
from yaksh.integrations.speech.audio import SAMPLE_RATE, quiet_s
from yaksh.integrations.speech.vendor import TtsVendor


def tts(
    settings: AppSettings, voice: VoiceSettings, language: Language, key: str, *, one_shot: bool
) -> ElevenLabsTTSService:
    """A one-shot service does not reconnect: a dropped socket fails the speech instead of
    ending it short as finished. Pipecat sends the language only to a model that takes it;
    any other reads the language from the text."""
    return ElevenLabsTTSService(
        api_key=key,
        url=settings.elevenlabs.url,
        sample_rate=SAMPLE_RATE,
        settings=ElevenLabsTTSService.Settings(
            model=voice.model_in_use.id,
            voice=voice.id,
            speed=voice.speed,
            stability=voice.stability,
            language=PipecatLanguage(language.value),
        ),
        stop_frame_timeout_s=quiet_s(one_shot),
        reconnect_on_error=not one_shot,
    )


def https_of(url: str) -> str:
    """The HTTP address of a websocket address, for the REST API at the same host."""
    return "https://" + url.split("://", 1)[1].split("/", 1)[0]


async def lookup(settings: AppSettings, key: str, voice_id: str) -> ProviderVoice | None:
    """At the host of the checked address, so a residency key stays in its region."""
    return await ElevenLabsClient(key, base_url=https_of(settings.elevenlabs.url)).get_voice(
        voice_id
    )


TTS = TtsVendor(service=tts, check_voice=None, lookup=lookup)
