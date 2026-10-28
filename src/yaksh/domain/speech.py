"""The speech-to-text providers Yaksh runs through Pipecat: the one that hears the agent on every
call, the languages each can hear, and whether it gives the agent's words while the agent
speaks."""

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
    words_while_speaking: bool
    """The service, as Yaksh runs it, gives the agent's words while the agent still speaks, in
    partial transcripts or in finals at short pauses, not only after the agent stops. An
    interruption that waits for a phrase needs them."""


STT = {
    SttProvider.DEEPGRAM: SttTraits(
        "Deepgram", INDIAN_ENGLISH_AND_SPANISH, words_while_speaking=True
    ),
    SttProvider.SARVAM: SttTraits("Sarvam", INDIAN_AND_ENGLISH, words_while_speaking=False),
    SttProvider.ASSEMBLYAI: SttTraits(
        "AssemblyAI",
        frozenset({Language.EN, Language.HI, Language.MR, Language.ES}),
        words_while_speaking=True,
    ),
    SttProvider.SONIOX: SttTraits("Soniox", INDIAN_ENGLISH_AND_SPANISH, words_while_speaking=True),
    SttProvider.GLADIA: SttTraits("Gladia", INDIAN_ENGLISH_AND_SPANISH, words_while_speaking=True),
}
"""Deepgram nova-3, Sarvam saaras:v4, AssemblyAI universal-3-6-pro, Soniox stt-rt-v5, Gladia
solaria-1. Deepgram, AssemblyAI and Soniox send partial transcripts. Gladia sends no partials
as Yaksh runs it, but it sends a final at each short pause, at most 5 s apart. Sarvam's service
sends one final for each utterance, when Yaksh's VAD has heard the agent stop."""
