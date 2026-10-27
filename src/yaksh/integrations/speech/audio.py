"""The phone audio every speech provider hears and speaks, and speech outside a call: a short
Pipecat pipeline that turns one text into 8 kHz PCM through the same service a call uses."""

import asyncio
import io
import wave
from collections.abc import AsyncGenerator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from pipecat.audio.utils import create_stream_resampler
from pipecat.frames.frames import (
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
TEARDOWN_S = 2.0
"""How long a cancelled pipeline outside a call waits for the cancel to pass through it. Each
processor's cleanup comes after, bounded by its own timeouts, such as a socket's close."""
STOP_GRACE_S = 0.5
"""How long speech outside a call waits after its reply stops, for an error that a provider
sends right after the stop, as Cartesia does."""


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


@dataclass
class OneShot:
    """A pipeline running outside a call, and the errors the pipeline has reported."""

    worker: PipelineWorker
    errors: list[str] = field(default_factory=list)


@asynccontextmanager
async def one_shot(
    processors: Sequence[FrameProcessor], params: PipelineParams, done: asyncio.Event
) -> AsyncGenerator[OneShot]:
    """Runs a pipeline outside a call until the block ends, then cancels it. An error sets
    `done`. The pipeline never gets an EndFrame: Pipecat queues a cancel behind a waiting
    EndFrame, so a provider that stalled its end could not be cancelled. The worker, not the
    runner, is cancelled: a runner cancelled before it starts running waits forever."""
    worker = PipelineWorker(
        Pipeline(list(processors)),
        params=params,
        idle_timeout_secs=None,
        cancel_timeout_secs=TEARDOWN_S,
        enable_rtvi=False,
    )
    run = OneShot(worker)

    @worker.event_handler("on_pipeline_error")
    async def on_error(_worker: object, frame: ErrorFrame) -> None:
        run.errors.append(frame.error)
        done.set()

    runner = WorkerRunner(handle_sigint=False)
    await runner.add_workers(worker)
    running = asyncio.create_task(runner.run())
    try:
        yield run
    finally:
        await worker.cancel()
        await asyncio.gather(running, return_exceptions=True)


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
    end of the reply within SPEAK_ONCE_S raises UnavailableError with the provider's reason."""
    spoken = Spoken()
    params = PipelineParams(audio_out_sample_rate=SAMPLE_RATE)
    async with one_shot([service, Resample8k(), spoken], params, spoken.stopped) as run:
        await run.worker.queue_frame(TTSSpeakFrame(text))
        try:
            async with asyncio.timeout(SPEAK_ONCE_S):
                await spoken.stopped.wait()
        except TimeoutError:
            raise UnavailableError(f"no speech in {SPEAK_ONCE_S:.0f} s") from None
        if not run.errors:
            await asyncio.sleep(STOP_GRACE_S)
    if run.errors:
        raise UnavailableError(run.errors[0])
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
