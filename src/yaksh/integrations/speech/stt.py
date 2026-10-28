"""The speech-to-text that hears the agent on a call, in the language the agent should answer
in. Pipecat's turn settings stay as they are, so Yaksh's voice detector and turn model decide
when the agent's turn ends."""

from collections.abc import Sequence

from pipecat.services.stt_service import STTService

from yaksh.domain.languages import AgentLanguage, Language
from yaksh.domain.settings import AppSettings
from yaksh.domain.speech import SttProvider
from yaksh.integrations.speech import assemblyai, deepgram, gladia, sarvam, soniox
from yaksh.integrations.speech.vendor import SttVendor

VENDORS: dict[SttProvider, SttVendor] = {
    SttProvider.DEEPGRAM: deepgram.STT,
    SttProvider.SARVAM: sarvam.STT,
    SttProvider.ASSEMBLYAI: assemblyai.STT,
    SttProvider.SONIOX: soniox.STT,
    SttProvider.GLADIA: gladia.STT,
}


def stt_language(provider: SttProvider, agent: Sequence[AgentLanguage], caller: Language) -> str:
    return VENDORS[provider].language(agent, caller)


def stt_model(settings: AppSettings, provider: SttProvider) -> str:
    return VENDORS[provider].model(settings)


def stt_service(
    settings: AppSettings, provider: SttProvider, key: str, language: str
) -> STTService:
    return VENDORS[provider].service(settings, key, language)
