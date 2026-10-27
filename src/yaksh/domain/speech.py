"""The speech-to-text providers Yaksh runs through Pipecat: the one that hears the agent on every
call, and the languages each can hear."""

from dataclasses import dataclass
from enum import StrEnum

from yaksh.domain.languages import INDIAN_AND_ENGLISH, INDIAN_ENGLISH_AND_SPANISH, Language


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
    SttProvider.DEEPGRAM: SttTraits("Deepgram", INDIAN_ENGLISH_AND_SPANISH),
    SttProvider.SARVAM: SttTraits("Sarvam", INDIAN_AND_ENGLISH),
    SttProvider.ASSEMBLYAI: SttTraits(
        "AssemblyAI", frozenset({Language.EN, Language.HI, Language.MR, Language.ES})
    ),
    SttProvider.SONIOX: SttTraits("Soniox", INDIAN_ENGLISH_AND_SPANISH),
    SttProvider.GLADIA: SttTraits("Gladia", INDIAN_ENGLISH_AND_SPANISH),
}
"""Deepgram nova-3, Sarvam saaras:v4, AssemblyAI universal-3-6-pro, Soniox stt-rt-v5, Gladia
solaria-1."""
