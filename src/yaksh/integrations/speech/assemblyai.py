"""AssemblyAI speech-to-text: Universal-3 Pro streaming (v3). Its streaming API takes the
language as `language_codes`; Pipecat's `language` setting is not sent."""

from pipecat.services.assemblyai.stt import AssemblyAISTTService
from pipecat.transcriptions.language import Language as PipecatLanguage

from yaksh.domain.settings import AppSettings
from yaksh.integrations.speech.audio import SAMPLE_RATE
from yaksh.integrations.speech.vendor import SttVendor


def stt(settings: AppSettings, key: str, language: str) -> AssemblyAISTTService:
    return AssemblyAISTTService(
        api_key=key,
        api_endpoint_base_url=settings.assemblyai.url,
        sample_rate=SAMPLE_RATE,
        settings=AssemblyAISTTService.Settings(
            model=settings.assemblyai.model, language_codes=[PipecatLanguage(language)]
        ),
    )


STT = SttVendor(model=lambda settings: settings.assemblyai.model, service=stt)
