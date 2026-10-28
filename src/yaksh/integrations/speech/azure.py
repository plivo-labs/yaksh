"""Azure AI Speech, with word boundaries for timing, at 8 kHz with Azure's equalizer for
narrowband telephone audio."""

from pipecat.services.azure.tts import AzureTTSService
from pipecat.transcriptions.language import Language as PipecatLanguage

from yaksh.domain.languages import Language
from yaksh.domain.settings import AppSettings
from yaksh.domain.voices import VoiceSettings
from yaksh.integrations.speech.audio import SAMPLE_RATE, quiet_s
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


TTS = TtsVendor(service=tts, check_voice=check_voice)
