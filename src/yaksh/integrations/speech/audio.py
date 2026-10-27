"""The phone audio every speech provider hears and speaks, and speech outside a call: a short
Pipecat pipeline that turns one text into 8 kHz PCM through the same service a call uses."""

import asyncio
import io
import wave

from pipecat.audio.utils import create_stream_resampler
from pipecat.frames.frames import (
    EndFrame,
    ErrorFrame,
    Frame,
    TTSAudioRawFrame,
    TTSSpeakFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.tts_service import TTSService
from pipecat.workers.runner import WorkerRunner

from yaksh.domain.errors import UnavailableError

SAMPLE_RATE = 8000
"""The phone audio every provider hears and speaks."""
SPEAK_ONCE_S = 20.0
"""The longest one piece of speech outside a call may take."""
REPLY_QUIET_S = 3.0
"""Pipecat's default: on a call, a reply whose audio stops this long is finished."""


def quiet_s(one_shot: bool) -> float:
    """How long a reply's audio may stop before Pipecat ends it as finished. Speech outside a
    call waits past its own deadline, so a reply that stalls fails instead of passing short."""
    return SPEAK_ONCE_S + 1 if one_shot else REPLY_QUIET_S


class Resample8k(FrameProcessor):
    """Right after the text-to-speech: speech at another rate becomes the call's 8 kHz, before
    anything counts its bytes as time. Each reply gets a fresh resampler: the few milliseconds
    it holds back at a reply's end are dropped rather than played at the start of the next."""

    def __init__(self) -> None:
        super().__init__()
        self._resampler = create_stream_resampler()

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, TTSStartedFrame):
            self._resampler = create_stream_resampler()
        elif isinstance(frame, TTSAudioRawFrame) and frame.sample_rate != SAMPLE_RATE:
            frame.audio = await self._resampler.resample(
                frame.audio, frame.sample_rate, SAMPLE_RATE
            )
            frame.sample_rate = SAMPLE_RATE
            frame.num_frames = len(frame.audio) // (2 * frame.num_channels)
        await self.push_frame(frame, direction)


class Spoken(FrameProcessor):
    """The end of a one-shot pipeline: the reply's audio, and whether the reply has stopped."""

    def __init__(self) -> None:
        super().__init__()
        self.audio = bytearray()
        self.stopped = asyncio.Event()

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, TTSAudioRawFrame):
            self.audio += frame.audio
        elif isinstance(frame, TTSStoppedFrame):
            self.stopped.set()
        await self.push_frame(frame, direction)


async def speak_once(service: TTSService, text: str) -> bytes:
    """The text spoken by a one-shot service, as 8 kHz 16-bit PCM. Any error, no audio, or no
    end of the reply within SPEAK_ONCE_S raises UnavailableError with the provider's reason.

    The pipeline gets its EndFrame only once the reply has stopped: Pipecat queues a cancel
    behind a waiting EndFrame, so a provider that stalls with the EndFrame queued could not be
    cancelled. An error the provider sends right after the stop, as Cartesia does, still comes
    in before the pipeline ends."""
    spoken = Spoken()
    worker = PipelineWorker(
        Pipeline([service, Resample8k(), spoken]),
        params=PipelineParams(audio_out_sample_rate=SAMPLE_RATE),
        idle_timeout_secs=None,
        enable_rtvi=False,
    )
    errors: list[str] = []

    @worker.event_handler("on_pipeline_error")
    async def on_error(_worker: object, frame: ErrorFrame) -> None:
        errors.append(frame.error)
        spoken.stopped.set()

    runner = WorkerRunner(handle_sigint=False)
    await runner.add_workers(worker)
    running = asyncio.create_task(runner.run())
    await worker.queue_frame(TTSSpeakFrame(text))
    try:
        async with asyncio.timeout(SPEAK_ONCE_S):
            await spoken.stopped.wait()
            await worker.queue_frame(EndFrame())
            await asyncio.shield(running)
    except TimeoutError:
        errors.append(f"no speech in {SPEAK_ONCE_S:.0f} s")
    finally:
        await runner.cancel()
        await asyncio.gather(running, return_exceptions=True)
    if errors:
        raise UnavailableError(errors[0])
    if not spoken.audio:
        raise UnavailableError("no audio came back")
    return bytes(spoken.audio)


def as_wav(pcm: bytes) -> bytes:
    """8 kHz 16-bit mono PCM, the audio a call gets, in a WAV container a browser can play."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as file:
        file.setnchannels(1)
        file.setsampwidth(2)
        file.setframerate(SAMPLE_RATE)
        file.writeframes(pcm)
    return buffer.getvalue()
