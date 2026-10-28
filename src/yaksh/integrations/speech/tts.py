"""The text-to-speech of a persona's voice, speaking the caller's language."""

from pipecat.services.tts_service import TTSService

from yaksh.domain.languages import Language
from yaksh.domain.settings import AppSettings
from yaksh.domain.voices import VoiceProvider, VoiceSettings
from yaksh.integrations.speech import azure, cartesia, elevenlabs, nimble, sarvam
from yaksh.integrations.speech.vendor import TtsVendor

VENDORS: dict[VoiceProvider, TtsVendor] = {
    VoiceProvider.ELEVENLABS: elevenlabs.TTS,
    VoiceProvider.CARTESIA: cartesia.TTS,
    VoiceProvider.SARVAM: sarvam.TTS,
    VoiceProvider.AZURE: azure.TTS,
    VoiceProvider.NIMBLE: nimble.TTS,
}


def tts_service(
    settings: AppSettings,
    voice: VoiceSettings,
    language: Language,
    key: str,
    *,
    one_shot: bool = False,
) -> TTSService:
    return VENDORS[voice.provider].service(settings, voice, language, key, one_shot=one_shot)


async def check_voice(
    settings: AppSettings, provider: VoiceProvider, key: str, builtin: str
) -> str:
    """A voice the account has, for its key check; `builtin` is the voice of Yaksh's own that
    a provider without one uses."""
    voice = VENDORS[provider].check_voice
    return builtin if voice is None else await voice(settings, key)
