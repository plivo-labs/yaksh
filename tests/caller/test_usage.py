from pipecat.frames.frames import Frame, TextFrame
from pipecat.metrics.metrics import LLMTokenUsage, STTUsage
from pipecat.observers.service_metrics_observer import ServiceMetricsObserver
from pipecat.pipeline.worker import PipelineParams
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.tests.utils import run_test

from truman.caller.usage import UsageMeter
from truman.domain.conversations import CallerUsage


class Spender(FrameProcessor):
    """Reports what two inferences, some transcribed audio and one spoken line used."""

    def can_generate_metrics(self) -> bool:
        return True

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, TextFrame):
            await self.start_llm_usage_metrics(
                LLMTokenUsage(
                    prompt_tokens=100,
                    completion_tokens=20,
                    total_tokens=120,
                    cache_read_input_tokens=40,
                )
            )
            await self.start_llm_usage_metrics(
                LLMTokenUsage(
                    prompt_tokens=50, completion_tokens=5, total_tokens=55, reasoning_tokens=3
                )
            )
            await self.start_stt_usage_metrics(STTUsage(audio_seconds=1.5))
            await self.start_tts_usage_metrics("Hello there.")
        await self.push_frame(frame, direction)


async def test_a_calls_usage_adds_up_what_its_services_reported() -> None:
    metrics = ServiceMetricsObserver()
    meter = UsageMeter(metrics)

    await run_test(
        Spender(),
        frames_to_send=[TextFrame("go")],
        observers=[metrics],
        pipeline_params=PipelineParams(enable_usage_metrics=True),
    )

    assert meter.usage() == CallerUsage(
        llm_prompt_tokens=150,
        llm_completion_tokens=25,
        llm_reasoning_tokens=3,
        llm_cache_read_tokens=40,
        llm_cache_creation_tokens=0,
        stt_audio_seconds=1.5,
        tts_characters=12,
    )


def test_a_service_that_reported_nothing_has_unknown_usage() -> None:
    assert UsageMeter(ServiceMetricsObserver()).usage() == CallerUsage()
