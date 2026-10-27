"""A provider's voices for the console: lookup where the provider has it, and speech through
the same Pipecat service a call uses."""

from yaksh.domain.errors import UnavailableError
from yaksh.domain.languages import Language
from yaksh.domain.settings import AppSettings
from yaksh.domain.voices import ProviderVoice, VoiceProvider, VoiceSettings
from yaksh.integrations.speech.audio import as_wav, speak_once
from yaksh.integrations.speech.tts import VENDORS, tts_service


class SpeechVoiceClient:
    """Built per request from the current settings, so a new model, address or key applies to
    the next request."""

    def __init__(self, settings: AppSettings, provider: VoiceProvider, credential: str) -> None:
        self._settings = settings
        self._provider = provider
        self._credential = credential

    async def get_voice(self, voice_id: str) -> ProviderVoice | None:
        """Only for a provider with lookup; the caller checks."""
        lookup = VENDORS[self._provider].lookup
        assert lookup is not None
        return await lookup(self._settings, self._credential, voice_id)

    async def speak(self, voice: VoiceSettings, language: Language, text: str) -> bytes:
        """A setting the provider's service refuses, such as an unknown model, fails the speech
        as the provider's own refusal does."""
        try:
            service = tts_service(self._settings, voice, language, self._credential, one_shot=True)
            return as_wav(await speak_once(service, text))
        except (ValueError, UnavailableError) as error:
            raise UnavailableError(
                f"{voice.provider.label} could not speak with voice {voice.id}: {error}"
            ) from None
