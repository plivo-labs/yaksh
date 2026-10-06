"""What the caller's services consumed in one call, from the usage records Pipecat reports."""

from typing import Any

from pipecat.observers.service_metrics_observer import (
    ServiceMetricsObserver,
    ServiceUsageKind,
    ServiceUsageRecord,
)

from yaksha.domain.conversations import CallerUsage


class UsageMeter:
    """Adds up the usage records of one call. Pipecat sends one record per piece of work: an
    LLM inference, a stretch of transcribed audio, a synthesized text."""

    def __init__(self, observer: ServiceMetricsObserver) -> None:
        self._totals: dict[str, float] = {}

        @observer.event_handler("on_service_usage")
        async def on_usage(_observer: Any, record: ServiceUsageRecord) -> None:
            self.add(record)

    def add(self, record: ServiceUsageRecord) -> None:
        match record.kind:
            case ServiceUsageKind.LLM:
                self._count("llm_prompt_tokens", record.prompt_tokens)
                self._count("llm_completion_tokens", record.completion_tokens)
                self._count("llm_reasoning_tokens", record.reasoning_tokens or 0)
                self._count("llm_cache_read_tokens", record.cache_read_input_tokens or 0)
                self._count("llm_cache_creation_tokens", record.cache_creation_input_tokens or 0)
            case ServiceUsageKind.STT:
                self._count("stt_audio_seconds", record.audio_seconds)
            case ServiceUsageKind.TTS:
                self._count("tts_characters", record.characters)

    def _count(self, field: str, value: float | None) -> None:
        if value is not None:
            self._totals[field] = self._totals.get(field, 0) + value

    def usage(self) -> CallerUsage:
        return CallerUsage.model_validate(self._totals)
