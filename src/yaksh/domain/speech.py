"""The speech providers Yaksh runs through Pipecat: the one that hears the agent on every call,
and the languages each can hear."""

from enum import StrEnum

from yaksh.domain.languages import Language


class SttProvider(StrEnum):
    DEEPGRAM = "deepgram"
    SARVAM = "sarvam"
    ASSEMBLYAI = "assemblyai"
    SONIOX = "soniox"
    GLADIA = "gladia"

    @property
    def label(self) -> str:
        return STT_LABELS[self]


STT_LABELS = {
    SttProvider.DEEPGRAM: "Deepgram",
    SttProvider.SARVAM: "Sarvam",
    SttProvider.ASSEMBLYAI: "AssemblyAI",
    SttProvider.SONIOX: "Soniox",
    SttProvider.GLADIA: "Gladia",
}

STT_LANGUAGES: dict[SttProvider, frozenset[Language]] = {
    SttProvider.DEEPGRAM: frozenset(Language),
    SttProvider.SARVAM: frozenset(Language) - {Language.ES},
    SttProvider.ASSEMBLYAI: frozenset({Language.EN, Language.HI, Language.MR, Language.ES}),
    SttProvider.SONIOX: frozenset(Language),
    SttProvider.GLADIA: frozenset(Language),
}
"""The languages of Yaksh's that each provider's streaming model hears, from its documentation
(2026-10-27): Deepgram nova-3, Sarvam saaras:v4, AssemblyAI universal-3-6-pro, Soniox stt-rt-v5,
Gladia solaria-1. A phone run refuses an agent that should answer in a language not listed."""
