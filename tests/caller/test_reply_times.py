import asyncio
import json
import logging
import uuid
from types import SimpleNamespace
from typing import Any, cast

import pytest
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    ClientConnectedFrame,
    Frame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    MetricsFrame,
    TranscriptionFrame,
    TTSAudioRawFrame,
    TTSSpeakFrame,
    TTSStartedFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.metrics.metrics import TextAggregationMetricsData, TTFBMetricsData
from pipecat.observers.base_observer import FramePushed
from pipecat.observers.user_bot_latency_observer import LatencyContribution, LatencyOwnerKind
from pipecat.processors.frame_processor import FrameDirection

from yaksh.caller.audio import MACHINE
from yaksh.caller.reply_times import ReplyTimes, steps_within
from yaksh.domain.answering import MachineLine
from yaksh.domain.conversations import CallerSettings
from yaksh.domain.latency import STEP_KEYS, CallerReplyTime
from yaksh.domain.speech import SttProvider
from yaksh.domain.voices import VoiceProvider, VoiceSettings

SOURCE = SimpleNamespace(name="Caller#0")
STT = SimpleNamespace(name="DeepgramSTTService#0")
CONVERSATION = uuid.UUID("01a17ea2-9d59-7ac1-92ef-2bafb49e6dfe")
AUDIO = b"\0\0" * 160


class Call:
    """Frames pushed to the observer at set times."""

    def __init__(self) -> None:
        self.now = 0.0
        self.timer = ReplyTimes(
            CONVERSATION,
            CallerSettings(
                llm_model="caller-model",
                reasoning_effort="low",
                stt_provider=SttProvider.SARVAM,
                stt_language="en-US",
                voice=VoiceSettings(provider=VoiceProvider.NIMBLE, id="t4"),
            ),
            "llm.example.com",
            stt=STT.name,
            now=lambda: self.now,
        )

    async def push(self, at: float, frame: Frame, source: SimpleNamespace = SOURCE) -> None:
        self.now = at
        await self.timer.on_push_frame(
            FramePushed(
                source=cast(Any, source),
                destination=cast(Any, SOURCE),
                frame=frame,
                direction=FrameDirection.DOWNSTREAM,
                timestamp=0,
            )
        )

    async def agent_turn(self, start: float, stop: float) -> None:
        """The agent speaks from start; the voice detector calls it over 0.6 s after stop."""
        await self.push(start, VADUserStartedSpeakingFrame())
        await self.push(
            stop + 0.6, VADUserStoppedSpeakingFrame(stop_secs=0.6, timestamp=stop + 0.6)
        )

    async def model_reply(self, at: float) -> None:
        """The STT's transcript, then the model asked 0.15 s later."""
        await self.push(at, TranscriptionFrame("yes", "agent", "now"), source=STT)
        await self.answer(at + 0.15)

    async def answer(self, at: float) -> None:
        """The model asked: first text 0.7 s later, audio 0.3 s after that, on the line 0.1 s
        after that."""
        await self.push(at, LLMFullResponseStartFrame())
        await self.push(
            at + 0.7, MetricsFrame(data=[TTFBMetricsData(processor="Caller#0", value=0.7)])
        )
        await self.push(at + 0.7, LLMTextFrame("Yes."))
        await self.push(at + 1.0, TTSAudioRawFrame(AUDIO, 8000, 1))
        await self.push(at + 1.1, BotStartedSpeakingFrame())


async def settled(call: Call) -> list[CallerReplyTime]:
    await asyncio.sleep(0)
    return call.timer.replies


async def test_a_model_reply_is_kept_with_where_its_time_went() -> None:
    call = Call()
    await call.agent_turn(0.0, 2.0)
    await call.model_reply(2.65)

    assert await settled(call) == [
        CallerReplyTime(
            audio_index=0,
            total_ms=1900,
            steps={
                "endpointing_wait": 600,
                "transcription": 50,
                "turn_detection": 150,
                "llm_inference": 700,
                "speech_synthesis": 300,
                "output_transport": 100,
            },
            stt_ttfs_ms=650,
        )
    ]


async def test_a_transcript_before_the_end_of_the_agents_turn_keeps_the_turn_check() -> None:
    """Pipecat drops such a transcript and names neither part; the wait from the end of the
    agent's turn to the model's request is the turn check."""
    call = Call()
    await call.push(0.0, VADUserStartedSpeakingFrame())
    await call.push(1.9, TranscriptionFrame("yes", "agent", "now"))
    await call.push(2.6, VADUserStoppedSpeakingFrame(stop_secs=0.6, timestamp=2.6))
    await call.push(5.6, LLMFullResponseStartFrame())
    await call.push(6.3, MetricsFrame(data=[TTFBMetricsData(processor="Caller#0", value=0.7)]))
    await call.push(6.3, LLMTextFrame("Yes."))
    await call.push(6.6, TTSAudioRawFrame(AUDIO, 8000, 1))
    await call.push(6.7, BotStartedSpeakingFrame())

    [reply] = await settled(call)
    assert reply.total_ms == 4700
    assert reply.steps["turn_detection"] == 3000
    assert "transcription" not in reply.steps
    assert "pipeline" not in reply.steps


async def test_fixed_lines_and_machine_lines_are_not_replies() -> None:
    call = Call()
    await call.agent_turn(0.0, 2.0)
    await call.push(17.0, TTSSpeakFrame("Hello? Are you still there?"))
    await call.push(17.3, TTSAudioRawFrame(AUDIO, 8000, 1))
    await call.push(17.4, BotStartedSpeakingFrame())
    await call.agent_turn(20.0, 22.0)
    started = TTSStartedFrame()
    started.metadata[MACHINE] = MachineLine.GREETING
    await call.push(22.7, started)
    await call.push(22.8, TTSAudioRawFrame(AUDIO, 8000, 1))
    await call.push(22.9, BotStartedSpeakingFrame())

    assert await settled(call) == []


async def test_the_callers_first_words_before_the_agent_spoke_are_not_a_reply() -> None:
    call = Call()
    await call.push(0.0, ClientConnectedFrame())
    await call.push(0.1, LLMFullResponseStartFrame())
    await call.push(0.8, LLMTextFrame("Hi."))
    await call.push(1.0, BotStartedSpeakingFrame())

    assert await settled(call) == []


async def test_replies_whose_handlers_run_after_later_frames_keep_their_own_audio_start() -> None:
    call = Call()
    await call.push(0.0, TTSSpeakFrame("Hi, I am calling about my booking."))
    await call.push(0.4, BotStartedSpeakingFrame())
    await call.agent_turn(3.0, 5.0)
    await call.model_reply(5.65)
    await call.agent_turn(9.0, 11.0)
    await call.model_reply(11.65)

    assert [(reply.audio_index, reply.total_ms) for reply in await settled(call)] == [
        (1, 1900),
        (2, 1900),
    ]


async def test_a_reply_whose_breakdown_runs_past_its_own_audio_start_keeps_that_start() -> None:
    """Pipecat adds the sentence wait to the first text's time, which can land after the audio
    started; the fixed goodbye that follows is not part of the reply."""
    call = Call()
    await call.agent_turn(0.0, 2.0)
    await call.push(2.65, TranscriptionFrame("bye", "agent", "now"))
    await call.push(2.8, LLMFullResponseStartFrame())
    await call.push(3.5, MetricsFrame(data=[TTFBMetricsData(processor="Caller#0", value=0.7)]))
    await call.push(3.5, LLMTextFrame("Okay."))
    await call.push(
        3.8, MetricsFrame(data=[TextAggregationMetricsData(processor="Caller#0", value=1.0)])
    )
    await call.push(3.8, TTSAudioRawFrame(AUDIO, 8000, 1))
    await call.push(3.9, BotStartedSpeakingFrame())
    await call.push(4.2, TTSSpeakFrame("Okay, thanks. I have to go now. Bye."))
    await call.push(4.6, BotStartedSpeakingFrame())

    [reply] = await settled(call)
    assert (reply.audio_index, reply.total_ms) == (0, 1900)
    assert sum(reply.steps.values()) == 1900
    assert "pipeline" not in reply.steps


async def test_the_stt_ttfs_is_to_the_last_final_transcript_before_the_model_was_asked() -> None:
    """From the end of the agent's speech, at the STT's own push: an earlier piece of the speech,
    a later hop of the frame and a transcript after the model was asked are not the one the
    reply answers. Below 0 when the transcript came before the end of the speech."""
    call = Call()
    await call.push(0.0, VADUserStartedSpeakingFrame())
    await call.push(1.0, TranscriptionFrame("I can", "agent", "now"), source=STT)
    transcript = TranscriptionFrame("help you", "agent", "now")
    await call.push(2.3, transcript, source=STT)
    await call.push(2.4, transcript)
    await call.push(2.6, VADUserStoppedSpeakingFrame(stop_secs=0.6, timestamp=2.6))
    await call.push(2.8, LLMFullResponseStartFrame())
    await call.push(3.0, TranscriptionFrame("thanks", "agent", "now"), source=STT)
    await call.push(3.5, LLMTextFrame("Yes."))
    await call.push(3.8, TTSAudioRawFrame(AUDIO, 8000, 1))
    await call.push(3.9, BotStartedSpeakingFrame())
    await call.push(6.0, VADUserStartedSpeakingFrame())
    await call.push(7.9, TranscriptionFrame("now", "agent", "now"), source=STT)
    await call.push(8.6, VADUserStoppedSpeakingFrame(stop_secs=0.6, timestamp=8.6))
    await call.answer(8.8)

    assert [reply.stt_ttfs_ms for reply in await settled(call)] == [300, -100]


async def test_a_reply_to_speech_with_no_final_transcript_has_no_stt_ttfs() -> None:
    """The transcript of the agent's earlier speech is not reused."""
    call = Call()
    await call.agent_turn(0.0, 2.0)
    await call.model_reply(2.65)
    await call.agent_turn(6.0, 8.0)
    await call.answer(8.8)

    assert [reply.stt_ttfs_ms for reply in await settled(call)] == [650, None]


async def test_each_reply_is_logged_on_one_line_with_every_part(
    caplog: pytest.LogCaptureFixture,
) -> None:
    call = Call()
    with caplog.at_level(logging.INFO, logger="yaksh.caller.reply_times"):
        await call.agent_turn(0.0, 2.0)
        await call.model_reply(2.65)
        await settled(call)

    [line] = caplog.messages
    event, payload = line.split(" ", 1)
    fields = json.loads(payload)
    assert event == "caller_reply_time"
    assert fields["conversation_id"] == str(CONVERSATION)
    assert (fields["caller_model"], fields["llm_host"], fields["language"]) == (
        "caller-model",
        "llm.example.com",
        "en-US",
    )
    assert (fields["stt_provider"], fields["tts_provider"]) == ("sarvam", "nimble")
    assert fields["reply"] == 0
    assert fields["total_ms"] == 1900
    assert fields["llm_inference_ms"] == 700
    assert fields["pipeline_ms"] == 0
    assert fields["stt_ttfs_ms"] == 650
    assert {f"{key}_ms" for key in STEP_KEYS} <= fields.keys()


def test_a_part_that_comes_twice_in_a_reply_counts_both_times() -> None:
    """A reply that the model ends without a word gets a second inference after its tool call:
    two LLM inference parts with the tool between them."""

    def part(key: str, start: float, secs: float) -> LatencyContribution:
        return LatencyContribution(
            key=key,
            label=key,
            owner="Caller#0",
            owner_kind=LatencyOwnerKind.SERVICE,
            start_time=start,
            duration_secs=secs,
        )

    steps = steps_within(
        [
            part("endpointing_wait", 0.0, 0.6),
            part("llm_inference", 0.6, 0.5),
            part("function_handler", 1.1, 0.1),
            part("llm_inference", 1.2, 0.7),
        ],
        start=0.0,
        end=1.9,
    )

    assert steps == {"endpointing_wait": 600, "llm_inference": 1200, "function_handler": 100}
