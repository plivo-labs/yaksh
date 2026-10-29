"""Soniox speech-to-text: real-time stt-rt-v5. The language goes as a hint; under Pipecat's
turn detection Soniox sends its final transcript when the voice detector ends the turn. Until
then it sends the words so far as partials, so `SttTraits.words_while_speaking` is true."""

from pipecat.services.soniox.stt import SonioxSTTService
from pipecat.transcriptions.language import Language as PipecatLanguage

from yaksh.domain.settings import AppSettings
from yaksh.integrations.speech.audio import SAMPLE_RATE
from yaksh.integrations.speech.vendor import SttVendor


def stt(settings: AppSettings, key: str, language: str) -> SonioxSTTService:
    return SonioxSTTService(
        api_key=key,
        url=settings.soniox.url,
        sample_rate=SAMPLE_RATE,
        settings=SonioxSTTService.Settings(
            model=settings.soniox.model, language_hints=[PipecatLanguage(language)]
        ),
    )


STT = SttVendor(model=lambda settings: settings.soniox.model, service=stt)
