"""The speech-to-text providers Yaksh runs through Pipecat: the one that hears the agent on every
call, and the languages each can hear."""

from dataclasses import dataclass
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
        return STT[self].label

    @property
    def traits(self) -> SttTraits:
        return STT[self]


@dataclass(frozen=True)
class SttTraits:
    label: str
    languages: frozenset[Language]
    """The languages of Yaksh's that the provider's streaming model hears, from its
    documentation (2026-10-27). A phone run refuses an agent that should answer in another."""


STT = {
    SttProvider.DEEPGRAM: SttTraits("Deepgram", frozenset(Language)),
    SttProvider.SARVAM: SttTraits("Sarvam", frozenset(Language) - {Language.ES}),
    SttProvider.ASSEMBLYAI: SttTraits(
        "AssemblyAI", frozenset({Language.EN, Language.HI, Language.MR, Language.ES})
    ),
    SttProvider.SONIOX: SttTraits("Soniox", frozenset(Language)),
    SttProvider.GLADIA: SttTraits("Gladia", frozenset(Language)),
}
"""Deepgram nova-3, Sarvam saaras:v4, AssemblyAI universal-3-6-pro, Soniox stt-rt-v5, Gladia
solaria-1."""
