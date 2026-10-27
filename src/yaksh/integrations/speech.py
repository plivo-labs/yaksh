"""The speech providers of a call, built for Pipecat from the settings: the speech-to-text that
hears the agent, in the language the agent should answer in."""

from collections.abc import Sequence

from pipecat.services.assemblyai.stt import AssemblyAISTTService
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.gladia.config import LanguageConfig
from pipecat.services.gladia.stt import GladiaSTTService
from pipecat.services.sarvam.stt import SarvamSTTService
from pipecat.services.soniox.stt import SonioxSTTService
from pipecat.services.stt_service import STTService
from pipecat.transcriptions.language import Language as PipecatLanguage

from yaksh.domain.languages import AgentLanguage, Language, answer_language
from yaksh.domain.settings import AppSettings
from yaksh.domain.speech import SttProvider

SAMPLE_RATE = 8000
"""The phone audio every provider hears and speaks."""

WIDE_SETTINGS: tuple[tuple[str, frozenset[Language]], ...] = (
    # The Hindi model also writes the English words that Hindi speakers mix in.
    ("hi", frozenset({Language.HI, Language.EN})),
    # The Hindi model writes Marathi as Hindi. The Marathi model hears both, which share a
    # script, but not English: on a real call it wrote an English agent as "Bubeet Herastaurant".
    ("mr", frozenset({Language.MR, Language.HI})),
    ("multi", frozenset({Language.EN, Language.HI, Language.ES})),
)
"""Deepgram settings that hear more than one language, with the languages of Yaksh's that each
hears, in the order a tie takes them. `multi` switches between ten languages; only these are
Yaksh's."""


def deepgram_language(agent: Sequence[AgentLanguage], caller: Language) -> str:
    """Of the Deepgram settings that hear the language the agent should answer in, the one that
    hears the most of the call's languages wins, and on a tie the one-language model."""
    own = answer_language(agent, caller)
    answer = own.language
    call = {*(language.language for language in agent), caller}
    options = [(own.value, frozenset({answer})), *WIDE_SETTINGS]
    code, _ = max(
        (option for option in options if answer in option[1]),
        key=lambda option: len(option[1] & call),
    )
    return code


def stt_language(provider: SttProvider, agent: Sequence[AgentLanguage], caller: Language) -> str:
    """The language setting the provider hears the agent with. Deepgram has settings that hear
    several languages; the others hear the language the agent should answer in."""
    if provider is SttProvider.DEEPGRAM:
        return deepgram_language(agent, caller)
    return answer_language(agent, caller).language.value


def stt_model(settings: AppSettings, provider: SttProvider) -> str:
    match provider:
        case SttProvider.DEEPGRAM:
            return settings.deepgram.model
        case SttProvider.SARVAM:
            return settings.sarvam_stt.model
        case SttProvider.ASSEMBLYAI:
            return settings.assemblyai.model
        case SttProvider.SONIOX:
            return settings.soniox.model
        case SttProvider.GLADIA:
            return settings.gladia.model


def stt_service(
    settings: AppSettings, provider: SttProvider, key: str, language: str
) -> STTService:
    """The provider's speech-to-text at the call's sample rate. Pipecat's turn settings stay as
    they are, so Yaksh's voice detector and turn model decide when the agent's turn ends.
    AssemblyAI and Gladia ignore Pipecat's `language` setting; each gets its own."""
    model = stt_model(settings, provider)
    match provider:
        case SttProvider.DEEPGRAM:
            return DeepgramSTTService(
                api_key=key,
                base_url=settings.deepgram.base_url,
                sample_rate=SAMPLE_RATE,
                settings=DeepgramSTTService.Settings(model=model, language=language),
            )
        case SttProvider.SARVAM:
            return SarvamSTTService(
                api_key=key,
                sample_rate=SAMPLE_RATE,
                settings=SarvamSTTService.Settings(model=model, language=PipecatLanguage(language)),
            )
        case SttProvider.ASSEMBLYAI:
            return AssemblyAISTTService(
                api_key=key,
                api_endpoint_base_url=settings.assemblyai.url,
                sample_rate=SAMPLE_RATE,
                settings=AssemblyAISTTService.Settings(
                    model=model, language_codes=[PipecatLanguage(language)]
                ),
            )
        case SttProvider.SONIOX:
            return SonioxSTTService(
                api_key=key,
                url=settings.soniox.url,
                sample_rate=SAMPLE_RATE,
                settings=SonioxSTTService.Settings(
                    model=model, language_hints=[PipecatLanguage(language)]
                ),
            )
        case SttProvider.GLADIA:
            return GladiaSTTService(
                api_key=key,
                url=settings.gladia.url,
                sample_rate=SAMPLE_RATE,
                settings=GladiaSTTService.Settings(
                    model=model, language_config=LanguageConfig(languages=[language])
                ),
            )
