"""What Yaksh needs from each speech provider's module: its model in the settings and its
Pipecat service. stt.py and tts.py hold one of these for each provider."""

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from pipecat.services.stt_service import STTService
from pipecat.services.tts_service import TTSService

from yaksh.domain.languages import AgentLanguage, Language, answer_language
from yaksh.domain.settings import AppSettings
from yaksh.domain.voices import ProviderVoice, VoiceSettings


def answer_code(agent: Sequence[AgentLanguage], caller: Language) -> str:
    """The language the agent should answer in, as the provider's setting."""
    return answer_language(agent, caller).language.value


class TtsBuilder(Protocol):
    def __call__(
        self,
        settings: AppSettings,
        voice: VoiceSettings,
        language: Language,
        key: str,
        *,
        one_shot: bool,
    ) -> TTSService: ...


@dataclass(frozen=True)
class SttVendor:
    model: Callable[[AppSettings], str]
    service: Callable[[AppSettings, str, str], STTService]
    """The service at the call's sample rate, from the settings, the key and the language."""
    language: Callable[[Sequence[AgentLanguage], Language], str] = answer_code
    """The language setting that hears the agent on a call."""


@dataclass(frozen=True)
class TtsVendor:
    service: TtsBuilder
    """A one-shot service, for speech outside a call, fails a reply that stalls or loses its
    socket instead of ending it short as finished."""
    check_voice: Callable[[AppSettings, str], Awaitable[str]] | None
    """A voice the account has, found with the settings and the key, for the key check; None
    for a provider whose check uses one of Yaksh's built-in voices."""
    lookup: Callable[[AppSettings, str, str], Awaitable[ProviderVoice | None]] | None = None
    """The provider's description of a voice, by the settings, the key and the voice's ID; None
    when the account does not have it. None for a provider without lookup."""
