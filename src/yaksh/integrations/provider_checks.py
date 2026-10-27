"""Short, real requests that show whether a provider accepts a key and the settings around it:
for Check and save before a key is stored, and for the Test buttons. Each one raises
ProviderCheckError with a reason that never holds the key."""

import asyncio

import openai
from openai import AsyncOpenAI
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.classifiers.base_classifier import ChoiceQuestion
from pipecat.classifiers.typesafe.jev.classifier import JevClassifier
from pipecat.frames.frames import ErrorFrame, Frame, InputAudioRawFrame, TranscriptionFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.audio.vad_processor import VADProcessor
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.workers.runner import WorkerRunner

from yaksh.diagnostics import describe_exception
from yaksh.domain.errors import UnavailableError
from yaksh.domain.languages import Language
from yaksh.domain.latency import VAD_CONFIDENCE, VAD_START_S, VAD_STOP_S
from yaksh.domain.settings import AppSettings
from yaksh.domain.speech import SttProvider
from yaksh.domain.voices import VoiceProvider, VoiceSettings
from yaksh.integrations.elevenlabs import ElevenLabsClient
from yaksh.integrations.openai_models import failure, takes_reasoning_effort
from yaksh.integrations.plivo import PlivoApi, PlivoError
from yaksh.integrations.speech import SAMPLE_RATE, stt_service

TIMEOUT_S = 20.0
REASONING_EFFORTS = ("none", "minimal", "low", "medium", "high", "xhigh", "max")
STT_CHECK_S = 10.0
"""How long a speech-to-text check waits for the transcript of its clip."""
FRAME_BYTES = SAMPLE_RATE * 2 // 50
"""20 ms of 16-bit audio, the size of a phone frame."""
TRAILING_SILENCE = bytes(SAMPLE_RATE * 2)
"""One second after the clip, so the voice detector ends the turn and providers that finalize
only then send the transcript."""
VAD = VADParams(confidence=VAD_CONFIDENCE, start_secs=VAD_START_S, stop_secs=VAD_STOP_S)


class ProviderCheckError(Exception):
    pass


def llm_client(base_url: str, api_key: str) -> AsyncOpenAI:
    return AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=TIMEOUT_S, max_retries=0)


async def llm_models(base_url: str, api_key: str) -> list[str]:
    """The model ids the provider lists; this also proves the key and the base URL."""
    client = llm_client(base_url, api_key)
    try:
        return sorted({model.id async for model in client.models.list()})
    except openai.OpenAIError as error:
        raise ProviderCheckError(f"the LLM provider refused the key: {failure(error)}") from None
    finally:
        await client.close()


async def check_llm(base_url: str, api_key: str, model: str, effort: str | None) -> None:
    """One short answer from the model, with the reasoning effort the caller sends."""
    client = llm_client(base_url, api_key)
    extra = {} if effort is None else {"reasoning": {"effort": effort}}
    try:
        await client.responses.create(model=model, input="Say ok.", store=False, extra_body=extra)
    except openai.OpenAIError as error:
        raise ProviderCheckError(f"model {model}: {failure(error)}") from None
    finally:
        await client.close()


async def reasoning_efforts(base_url: str, api_key: str, model: str) -> list[str]:
    """The reasoning efforts the model takes; empty for a model without reasoning. A plain
    request goes first, so a model the provider cannot serve, such as an Azure model with no
    deployment, fails with the provider's reason instead of as an effort the model refuses.
    Raises when any answer stays open, so a timeout never reads as a refusal."""
    await check_llm(base_url, api_key, model, None)
    client = llm_client(base_url, api_key)
    try:
        answers = await asyncio.gather(
            *(takes_reasoning_effort(client, model, effort) for effort in REASONING_EFFORTS)
        )
    finally:
        await client.close()
    if any(answer is None for answer in answers):
        raise ProviderCheckError(f"could not check the reasoning efforts of {model}; try again")
    return [effort for effort, takes in zip(REASONING_EFFORTS, answers, strict=True) if takes]


class Heard(FrameProcessor):
    """The end of a check pipeline: done at the first final transcript with words."""

    def __init__(self) -> None:
        super().__init__()
        self.text: str | None = None
        self.done = asyncio.Event()

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, TranscriptionFrame) and frame.text.strip():
            self.text = frame.text
            self.done.set()
        await self.push_frame(frame, direction)


async def check_stt(settings: AppSettings, provider: SttProvider, key: str, clip: bytes) -> None:
    """The provider transcribes a short English line, sent as a call sends it: in 20 ms frames
    through the call's voice detector, then a second of silence. Only a transcript with words
    passes; silence alone would pass a provider that accepts the connection and refuses the
    key later."""
    heard = Heard()
    worker = PipelineWorker(
        Pipeline(
            [
                VADProcessor(vad_analyzer=SileroVADAnalyzer(params=VAD)),
                stt_service(settings, provider, key, Language.EN.value),
                heard,
            ]
        ),
        params=PipelineParams(audio_in_sample_rate=SAMPLE_RATE),
        idle_timeout_secs=None,
        enable_rtvi=False,
    )
    errors: list[str] = []

    @worker.event_handler("on_pipeline_error")
    async def on_error(_worker: object, frame: ErrorFrame) -> None:
        errors.append(frame.error)
        heard.done.set()

    runner = WorkerRunner(handle_sigint=False)
    await runner.add_workers(worker)
    running = asyncio.create_task(runner.run())
    audio = clip + TRAILING_SILENCE
    try:
        async with asyncio.timeout(STT_CHECK_S):
            for at in range(0, len(audio), FRAME_BYTES):
                if heard.done.is_set():
                    break
                frame = InputAudioRawFrame(audio[at : at + FRAME_BYTES], SAMPLE_RATE, 1)
                await worker.queue_frame(frame)
                await asyncio.sleep(0.02)
            await heard.done.wait()
    except TimeoutError:
        errors.append(f"no transcript of a test clip in {STT_CHECK_S:.0f} s")
    finally:
        await worker.cancel()
        await asyncio.gather(running, return_exceptions=True)
    if errors:
        raise ProviderCheckError(f"{provider.label}: {errors[0]}")


async def check_elevenlabs(api_key: str, voice_id: str) -> None:
    """One short word of speech, so a key limited to speech passes."""
    voice = VoiceSettings(provider=VoiceProvider.ELEVENLABS, id=voice_id)
    try:
        spoken = await ElevenLabsClient(api_key).speak(voice, Language.EN, "OK")
    except UnavailableError as error:
        raise ProviderCheckError(str(error)) from None
    if spoken is None:
        raise ProviderCheckError(f"the ElevenLabs account cannot use voice {voice_id}")


async def check_typesafe(api_key: str, model: str) -> None:
    """One question to Jev."""
    classifier = JevClassifier(api_key=api_key, model=model)
    question = ChoiceQuestion(instructions="Is the sky blue?", options={"yes": "Yes", "no": "No"})
    try:
        await asyncio.wait_for(classifier.choice("The sky is blue.", {"q": question}), TIMEOUT_S)
    except Exception as error:
        raise ProviderCheckError(f"TypeSafe: {describe_exception(error)}") from None
    finally:
        await classifier.cleanup()


async def check_plivo(auth_id: str, auth_token: str) -> int:
    """How many numbers the account lists; this proves the Auth ID and Auth token."""
    try:
        return len(await PlivoApi(auth_id, auth_token).list_numbers())
    except PlivoError as error:
        raise ProviderCheckError(f"Plivo: {error}") from None
