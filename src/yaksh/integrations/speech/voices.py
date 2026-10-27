"""A provider's voices for the console: lookup where the provider has it, and speech through
the same Pipecat service a call uses."""

from yaksh.domain.errors import UnavailableError
from yaksh.domain.languages import Language
from yaksh.domain.settings import AppSettings
from yaksh.domain.voices import ProviderVoice, VoiceProvider, VoiceSettings
from yaksh.integrations.elevenlabs import ElevenLabsClient
from yaksh.integrations.speech.audio import as_wav, speak_once
from yaksh.integrations.speech.tts import tts_service


def https_of(url: str) -> str:
    """The HTTP address of a provider's websocket address, for its REST API."""
    return "https://" + url.split("://", 1)[1].split("/", 1)[0]


class SpeechVoiceClient:
    """Built per request from the current settings, so a new model, address or key applies to
    the next request."""

    def __init__(self, settings: AppSettings, provider: VoiceProvider, key: str) -> None:
        self._settings = settings
        self._provider = provider
        self._key = key

    async def get_voice(self, voice_id: str) -> ProviderVoice | None:
        """Only ElevenLabs looks voices up; the caller asks only a provider with lookup."""
        assert self._provider is VoiceProvider.ELEVENLABS
        lookup = ElevenLabsClient(self._key, base_url=https_of(self._settings.elevenlabs.url))
        return await lookup.get_voice(voice_id)

    async def speak(self, voice: VoiceSettings, language: Language, text: str) -> bytes:
        service = tts_service(self._settings, voice, language, self._key, one_shot=True)
        try:
            return as_wav(await speak_once(service, text))
        except UnavailableError as error:
            raise UnavailableError(
                f"{voice.provider.label} could not speak with voice {voice.id}: {error}"
            ) from None
