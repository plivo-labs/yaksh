"""ElevenLabs speech over its websockets, with word timestamps; a data residency address keeps
the speech in its region. The v3 and v4 models work only on its dialogue socket."""

from pipecat.services.elevenlabs.dialogue.tts import ElevenLabsDialogueTTSService
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
from pipecat.transcriptions.language import Language as PipecatLanguage

from yaksh.domain.languages import Language
from yaksh.domain.settings import AppSettings
from yaksh.domain.voices import ProviderVoice, VoiceSettings
from yaksh.integrations.elevenlabs import ElevenLabsClient
from yaksh.integrations.speech.audio import SAMPLE_RATE, quiet_s
from yaksh.integrations.speech.vendor import TtsVendor

DIALOGUE_MODELS = ("eleven_v3", "eleven_v4")
"""The model families that only the dialogue socket takes."""


class SentenceDialogue(ElevenLabsDialogueTTSService):
    """The dialogue socket holds text until about 40 characters, and Pipecat ends a reply that
    stays quiet for REPLY_QUIET_S, so a short reply would never be heard. Each sentence is
    flushed as it is sent."""

    async def _send_text(self, text: str, context_id: str) -> None:
        await super()._send_text(text, context_id)
        await self.flush_audio(context_id)


def tts(
    settings: AppSettings, voice: VoiceSettings, language: Language, key: str, *, one_shot: bool
) -> ElevenLabsTTSService | SentenceDialogue:
    """A one-shot service does not reconnect: a dropped socket fails the speech instead of
    ending it short as finished. Pipecat sends the language only to a model that takes it;
    any other reads the language from the text."""
    model = voice.model_in_use.id
    if model is not None and model.startswith(DIALOGUE_MODELS):
        return SentenceDialogue(
            api_key=key,
            url=settings.elevenlabs.url,
            sample_rate=SAMPLE_RATE,
            settings=ElevenLabsDialogueTTSService.Settings(
                model=model,
                voice=voice.id,
                stability=voice.stability,
                language=PipecatLanguage(language.value),
            ),
            stop_frame_timeout_s=quiet_s(one_shot),
            reconnect_on_error=not one_shot,
        )
    return ElevenLabsTTSService(
        api_key=key,
        url=settings.elevenlabs.url,
        sample_rate=SAMPLE_RATE,
        settings=ElevenLabsTTSService.Settings(
            model=model,
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
