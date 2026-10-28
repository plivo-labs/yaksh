"""Deepgram speech-to-text: nova-3 streaming, with a language setting that can hear more than
one language."""

from collections.abc import Sequence

from pipecat.services.deepgram.stt import DeepgramSTTService

from yaksh.domain.languages import AgentLanguage, Language, answer_language
from yaksh.domain.settings import AppSettings
from yaksh.integrations.speech.audio import SAMPLE_RATE
from yaksh.integrations.speech.vendor import SttVendor

WIDE_SETTINGS: tuple[tuple[str, frozenset[Language]], ...] = (
    # The Hindi model also writes the English words that Hindi speakers mix in.
    ("hi", frozenset({Language.HI, Language.EN})),
    # The Hindi model writes Marathi as Hindi. The Marathi model hears both, which share a
    # script, but not English: on a real call it wrote an English agent as "Bubeet Herastaurant".
    ("mr", frozenset({Language.MR, Language.HI})),
    ("multi", frozenset({Language.EN, Language.HI, Language.ES})),
)
"""Settings that hear more than one language, with the languages of Yaksh's that each hears, in
the order a tie takes them. `multi` switches between ten languages; only these are Yaksh's."""


def deepgram_language(agent: Sequence[AgentLanguage], caller: Language) -> str:
    """Of the settings that hear the language the agent should answer in, the one that hears
    the most of the call's languages wins, and on a tie the one-language model."""
    own = answer_language(agent, caller)
    answer = own.language
    call = {*(language.language for language in agent), caller}
    options = [(own.value, frozenset({answer})), *WIDE_SETTINGS]
    code, _ = max(
        (option for option in options if answer in option[1]),
        key=lambda option: len(option[1] & call),
    )
    return code


def stt(settings: AppSettings, key: str, language: str) -> DeepgramSTTService:
    return DeepgramSTTService(
        api_key=key,
        base_url=settings.deepgram.base_url,
        sample_rate=SAMPLE_RATE,
        settings=DeepgramSTTService.Settings(model=settings.deepgram.model, language=language),
    )


STT = SttVendor(
    model=lambda settings: settings.deepgram.model, service=stt, language=deepgram_language
)
