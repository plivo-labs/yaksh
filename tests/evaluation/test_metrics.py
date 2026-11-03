import io
import wave
from pathlib import Path

from tests.conftest import FakeFileStore
from yaksh import simulation
from yaksh.db.models import Conversation
from yaksh.domain.answering import AnsweredBy
from yaksh.domain.conversations import (
    LineFacts,
    Provenance,
    Role,
    Transcript,
    Turn,
    Validity,
    WireEvent,
    WireEventKind,
)
from yaksh.domain.evaluations import Metric, MetricKey
from yaksh.domain.latency import (
    AgentMedia,
    CallerReplyTime,
    CallerReplyWindow,
    LoopLag,
    Span,
    Speech,
    waits,
)
from yaksh.domain.stops import LineStop, StopResult
from yaksh.evaluation import call, metrics


def reply(start_ms: int, end_ms: int) -> CallerReplyWindow:
    return CallerReplyWindow(
        start_ms=start_ms, end_ms=end_ms, finished=True, audio_start_ms=0, audio_ms=0
    )


def turn(role: Role, text: str, at_ms: int = 0, **fields: object) -> Turn:
    return Turn.model_validate(
        {"role": role, "text": text, "started_at_ms": at_ms, "ended_at_ms": at_ms, **fields}
    )


def test_the_goodbye_starts_with_the_reply_that_was_going_out_when_the_caller_ended() -> None:
    replies = [reply(1_000, 2_000), reply(5_000, 6_500)]
    ended = Transcript(
        caller_replies=replies,
        wire_events=[WireEvent(kind=WireEventKind.END_CALL, at_ms=5_800, detail="done")],
    )
    limited = Transcript(
        caller_replies=replies, wire_events=[WireEvent(kind=WireEventKind.TURN_LIMIT, at_ms=4_000)]
    )

    # After a silent end, Yaksh marks the end first and then says the goodbye.
    silent = Transcript(
        caller_replies=[reply(10_000, 12_000), reply(20_600, 21_400)],
        wire_events=[WireEvent(kind=WireEventKind.END_CALL, at_ms=20_000, detail="done")],
    )

    assert metrics.goodbye_from(ended) == 5_000
    assert metrics.goodbye_from(silent) == 20_600
    assert metrics.goodbye_from(limited) == 4_000
    assert metrics.goodbye_from(Transcript(caller_replies=replies)) is None


def test_turn_taking_counts_the_waits_that_expected_an_answer() -> None:
    paired = waits(
        0,
        [(1_000, 2_000), (8_000, 9_000), (21_000, 21_500), (30_000, 31_000)],
        [Span(start_ms=at, end_ms=at + 300) for at in (500, 7_600, 31_200)],
        40_000,
        goodbye_from_ms=30_000,
        gaps=[Span(start_ms=22_000, end_ms=23_000)],
        agent_opens=True,
    )

    found = metrics.turn_taking(paired)

    assert {key: value for key, value in found.value.items() if key != "waits"} == {
        "expected": 4,
        "unanswered": 1,
        "talked_over": 0,
        "at_least_ms": {"3000": 2, "5000": 2, "10000": 1},
        "longest_wait_ms": 12_000,
    }
    assert found.flags == ["unanswered", "long_wait", "dead_air", "media_gap"]


def test_a_monologue_ends_where_the_caller_speaks_and_the_goodbye_is_left_out() -> None:
    speech = Speech(
        agent=[
            Span(start_ms=0, end_ms=20_000),
            Span(start_ms=20_500, end_ms=50_000),
            Span(start_ms=52_000, end_ms=55_000),
            Span(start_ms=70_000, end_ms=71_000),
        ],
        caller=[Span(start_ms=50_500, end_ms=51_500), Span(start_ms=69_000, end_ms=69_500)],
    )

    found = metrics.speaking(speech, goodbye_from_ms=69_000)

    assert found.value == {
        "agent_ms": 52_500,
        "caller_ms": 1_000,
        "agent_share": 0.981,
        "longest_monologue_ms": 49_500,
    }
    assert found.flags == ["monologue"]
    # Caller speech inside one stretch of agent speech splits it.
    over = Speech(
        agent=[Span(start_ms=0, end_ms=46_000)], caller=[Span(start_ms=5_000, end_ms=6_000)]
    )
    assert metrics.speaking(over, None).value["longest_monologue_ms"] == 40_000


def test_the_same_answer_after_each_caller_reply_is_a_repetition() -> None:
    sorry = "Sorry, I didn't get that. Could you repeat?"
    turns = [
        turn(Role.AGENT, "Hello, how can I help?"),
        turn(Role.CALLER, "I want to book a table."),
        turn(Role.AGENT, sorry, 1_000),
        turn(Role.CALLER, "A table for two."),
        turn(Role.AGENT, "Sorry, I didn't get that."),
        turn(Role.AGENT, "Could you repeat?"),
        turn(Role.CALLER, "For two people, tonight."),
        turn(Role.AGENT, "sorry i didnt get that could you repeat"),
        turn(Role.CALLER, "Hello?"),
        turn(Role.AGENT, "Sure, for what time?"),
    ]

    found = metrics.agent_repetition(turns)

    assert found.value == {"runs": [{"text": sorry, "count": 3, "at_ms": 1_000}]}
    assert found.flags == ["repetition"]
    assert metrics.agent_repetition(turns[:6]).flags == []


def test_capture_faults_name_what_went_wrong_on_yakshs_side() -> None:
    transcript = Transcript(
        turns=[
            turn(Role.CALLER, "Hi", provenance=Provenance.UNCONFIRMED),
            turn(Role.AGENT, "Hello", 1_000),
            # the end of the call left the last reply, and words that never went out,
            # unconfirmed
            turn(Role.CALLER, "Bye", 5_000, provenance=Provenance.UNCONFIRMED),
            turn(Role.CALLER, "Take care", 5_600, provenance=Provenance.UNCONFIRMED),
        ],
        caller_replies=[reply(0, 800), reply(5_000, 5_500)],
        validity=Validity(ok=False, reasons=["the caller model failed"]),
        agent_media=AgentMedia(
            first_ms=300, last_ms=9_000, gaps=[Span(start_ms=1_000, end_ms=1_400)]
        ),
        loop_lag=LoopLag(max_ms=417, max_at_ms=120, p99_ms=30, samples=500),
    )
    # The agent's media started 200 ms after the stream opened: a gap too.
    gaps = call.media_gaps(transcript, 100)
    assert gaps == [Span(start_ms=100, end_ms=300), Span(start_ms=1_000, end_ms=1_400)]

    found = metrics.capture_faults(transcript, recorded=False, gaps=gaps)

    assert found.value == {
        "caller_error": ["the caller model failed"],
        "unconfirmed_caller_turns": 1,
        "media_gaps": 2,
        "media_gap_ms": 600,
        "worker_stall": {"max_ms": 417, "at_ms": 120},
    }
    assert found.flags == [
        "caller_error",
        "unconfirmed_caller_turns",
        "missing_recording",
        "media_gap",
        "worker_stall",
    ]
    assert metrics.capture_faults(Transcript(), recorded=True, gaps=[]).flags == ["no_agent_media"]


def test_connect_timing_runs_from_the_first_event_of_each_kind() -> None:
    transcript = Transcript(
        stream_opened_ms=6_100,
        wire_events=[
            WireEvent(kind=WireEventKind.CONNECT_STARTED, at_ms=0),
            WireEvent(kind=WireEventKind.RINGING, at_ms=1_200),
            WireEvent(kind=WireEventKind.ANSWERED, at_ms=5_900),
            WireEvent(kind=WireEventKind.ANSWERED, at_ms=7_000),
            WireEvent(kind=WireEventKind.CONNECTED, at_ms=5_300),
        ],
    )

    found = metrics.usage(transcript, None, None, LineFacts(bill_duration_s=60))

    assert found.value == {
        "settings": None,
        "usage": None,
        "bill_duration_s": 60,
        "ringing_ms": 1_200,
        "answered_ms": 5_900,
        "stream_opened_ms": 6_100,
    }


def test_the_callers_reply_time_and_each_part_are_percentiles_over_the_same_replies() -> None:
    def reply(total: int, stt: int | None = None, **steps: int) -> CallerReplyTime:
        return CallerReplyTime(audio_index=0, total_ms=total, steps=steps, stt_ttfs_ms=stt)

    found = metrics.caller_reply_time(
        [
            reply(1_900, stt=280, endpointing_wait=600, llm_inference=1_300),
            reply(2_400, endpointing_wait=600, llm_inference=1_500, function_handler=300),
            reply(1_700, stt=310, endpointing_wait=600, llm_inference=1_100, pipeline=1),
        ]
    )

    # The core parts are listed even at 0 ms; another part only from PART_MS at its p90.
    assert found.value == {
        "replies": 3,
        "p50_ms": 1_900,
        "p90_ms": 2_400,
        "steps": [
            {"key": "endpointing_wait", "p50_ms": 600, "p90_ms": 600},
            {"key": "transcription", "p50_ms": 0, "p90_ms": 0},
            {"key": "turn_detection", "p50_ms": 0, "p90_ms": 0},
            {"key": "llm_inference", "p50_ms": 1_300, "p90_ms": 1_500},
            {"key": "function_handler", "p50_ms": 0, "p90_ms": 300},
            {"key": "speech_synthesis", "p50_ms": 0, "p90_ms": 0},
        ],
        "stt_ttfs": {"replies": 2, "p50_ms": 280, "p90_ms": 310},
    }


def silence(channels: int, seconds: float) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as file:
        file.setnchannels(channels)
        file.setsampwidth(2)
        file.setframerate(8000)
        file.writeframes(bytes(2 * channels * round(8000 * seconds)))
    return buffer.getvalue()


async def test_an_interruption_line_is_no_reply_that_waits_for_the_agent() -> None:
    store = FakeFileStore()
    await store.put("recording.wav", silence(2, 6), "audio/wav")
    await store.put("caller-voice.wav", silence(1, 1), "audio/wav")
    persona = CallerReplyWindow(
        start_ms=1_000, end_ms=1_500, finished=True, audio_start_ms=0, audio_ms=500
    )
    line = CallerReplyWindow(
        start_ms=3_000,
        end_ms=3_500,
        finished=True,
        audio_start_ms=500,
        audio_ms=500,
        interruption=1,
    )
    transcript = Transcript(
        stream_opened_ms=0,
        recording_start_ms=0,
        caller_replies=[persona, line],
        wire_events=[WireEvent(kind=WireEventKind.CONNECTED, at_ms=0)],
    )
    conversation = Conversation(
        transcript=transcript.model_dump(mode="json"),
        recording_key="recording.wav",
        caller_voice_key="caller-voice.wav",
        answered_by=AnsweredBy.CALLER,
        caller_settings=None,
        caller_usage=None,
        line_facts=None,
    )

    found = await call.measure_call(conversation, store, agent_speaks_first=True)

    waits_for = [wait["start_ms"] for wait in found[MetricKey.TURN_TAKING].value["waits"]]
    assert waits_for == [0, 1_500], "the call's start and the persona's reply, not the line"


async def test_a_call_gets_only_the_metrics_its_facts_support() -> None:
    def saved(transcript: Transcript) -> Conversation:
        return Conversation(
            transcript=transcript.model_dump(mode="json"),
            recording_key=None,
            caller_voice_key=None,
            caller_settings=None,
            caller_usage=None,
            line_facts=None,
        )

    never_connected = await call.measure_call(
        saved(Transcript()), FakeFileStore(), agent_speaks_first=True
    )
    connected = [WireEvent(kind=WireEventKind.CONNECTED, at_ms=900)]
    no_recording = await call.measure_call(
        saved(Transcript(stream_opened_ms=900, caller_replies=[], wire_events=connected)),
        FakeFileStore(),
        agent_speaks_first=True,
    )
    # The worker failed after the call connected, before it saved the stream's opening.
    crashed = await call.measure_call(
        saved(Transcript(wire_events=connected)), FakeFileStore(), agent_speaks_first=True
    )

    assert set(never_connected) == {MetricKey.USAGE}
    assert set(no_recording) == {
        MetricKey.USAGE,
        MetricKey.CAPTURE_FAULTS,
        MetricKey.AGENT_REPETITION,
    }
    assert "missing_recording" in no_recording[MetricKey.CAPTURE_FAULTS].flags
    assert set(crashed) == set(no_recording)
    assert crashed[MetricKey.CAPTURE_FAULTS].flags == ["incomplete_record"]


async def test_a_phone_call_with_measured_caller_replies_gets_their_reply_time() -> None:
    connected = Transcript(
        stream_opened_ms=900,
        caller_replies=[],
        wire_events=[WireEvent(kind=WireEventKind.CONNECTED, at_ms=900)],
    )
    measured = Conversation(
        transcript=connected.model_dump(mode="json"),
        caller_reply_times=[{"audio_index": 0, "total_ms": 1_900, "steps": {}}],
    )
    unmeasured = Conversation(transcript=connected.model_dump(mode="json"), caller_reply_times=[])

    found = await call.measure_call(measured, FakeFileStore(), agent_speaks_first=True)
    none = await call.measure_call(unmeasured, FakeFileStore(), agent_speaks_first=True)

    assert found[MetricKey.CALLER_REPLY_TIME].value["p50_ms"] == 1_900
    assert MetricKey.CALLER_REPLY_TIME not in none


SPEAKERS = Path(simulation.__file__).parent / "sounds" / "speakers"


def clip(name: str, from_s: float, to_s: float) -> bytes:
    with wave.open(str(SPEAKERS / f"{name}.wav")) as file:
        assert (file.getframerate(), file.getnchannels()) == (8000, 1)
        file.setpos(round(8000 * from_s))
        return file.readframes(round(8000 * (to_s - from_s)))


def wav(channels: list[bytes]) -> bytes:
    size = max(len(pcm) for pcm in channels)
    frames = b"".join(
        b"".join(pcm.ljust(size, b"\0")[at : at + 2] for pcm in channels)
        for at in range(0, size, 2)
    )
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as file:
        file.setnchannels(len(channels))
        file.setsampwidth(2)
        file.setframerate(8000)
        file.writeframes(frames)
    return buffer.getvalue()


def quiet(seconds: float) -> bytes:
    return bytes(2 * round(8000 * seconds))


async def interrupted_call(media: AgentMedia) -> dict[MetricKey, Metric]:
    """A 10 s call: the agent speaks from about 1.1 s to 3.8 s, and a line goes out from 2 s."""
    store = FakeFileStore()
    agent = quiet(1) + clip("en_own_phone_call_1", 4.0, 6.9) + quiet(6)
    voice = clip("en_talks_to_caller_2", 0, 2.1)
    await store.put("recording.wav", wav([agent, quiet(10)]), "audio/wav")
    await store.put("caller-voice.wav", wav([voice]), "audio/wav")
    line = CallerReplyWindow(
        start_ms=2_000,
        end_ms=4_100,
        finished=True,
        audio_start_ms=0,
        audio_ms=2_100,
        interruption=1,
    )
    transcript = Transcript(
        stream_opened_ms=0,
        recording_start_ms=0,
        caller_replies=[line],
        agent_media=media,
        wire_events=[WireEvent(kind=WireEventKind.CONNECTED, at_ms=0)],
    )
    conversation = Conversation(
        transcript=transcript.model_dump(mode="json"),
        recording_key="recording.wav",
        caller_voice_key="caller-voice.wav",
        answered_by=AnsweredBy.CALLER,
        caller_settings=None,
        caller_usage=None,
        line_facts=None,
    )
    return await call.measure_call(conversation, store, agent_speaks_first=True)


async def test_a_line_gets_the_time_in_which_the_agents_speech_stopped_after_it() -> None:
    found = await interrupted_call(AgentMedia(first_ms=0, last_ms=10_000, gaps=[]))

    speech = Speech.model_validate(found[MetricKey.SPEECH].value)
    [stop] = found[MetricKey.STOP_TIME].value["lines"]
    start = speech.caller[0].start_ms
    holding = next(span for span in speech.agent if span.start_ms <= start < span.end_ms)
    assert 2_000 < start < 2_500, "the line's speech, not its audio start"
    assert stop == {
        "number": 1,
        "line_ms": start,
        "result": "stopped",
        "stop_ms": holding.end_ms - start,
        "at_least": False,
        "reason": None,
    }
    assert holding.start_ms < 2_000 < 3_500 < holding.end_ms, "the speech the line came into"
    assert found[MetricKey.STOP_TIME].value["counts"] == {
        "stopped": 1,
        "kept_talking": 0,
        "not_speaking": 0,
        "unknown": 0,
    }


async def test_silence_after_the_agents_media_ended_is_no_stop_of_its_speech() -> None:
    found = await interrupted_call(AgentMedia(first_ms=0, last_ms=4_000, gaps=[]))

    [stop] = found[MetricKey.STOP_TIME].value["lines"]
    assert (stop["result"], stop["reason"]) == ("unknown", "media_gap")


async def test_a_call_without_lines_gets_no_stop_time() -> None:
    store = FakeFileStore()
    await store.put("recording.wav", silence(2, 6), "audio/wav")
    await store.put("caller-voice.wav", silence(1, 1), "audio/wav")
    transcript = Transcript(
        stream_opened_ms=0,
        recording_start_ms=0,
        caller_replies=[reply(1_000, 1_500)],
        wire_events=[WireEvent(kind=WireEventKind.CONNECTED, at_ms=0)],
    )
    conversation = Conversation(
        transcript=transcript.model_dump(mode="json"),
        recording_key="recording.wav",
        caller_voice_key="caller-voice.wav",
        answered_by=AnsweredBy.CALLER,
        caller_settings=None,
        caller_usage=None,
        line_facts=None,
    )

    found = await call.measure_call(conversation, store, agent_speaks_first=True)

    assert MetricKey.SPEECH in found
    assert MetricKey.STOP_TIME not in found


def test_the_stop_time_metric_flags_a_line_the_agent_kept_talking_over() -> None:
    kept = LineStop(number=2, line_ms=9_000, result=StopResult.KEPT_TALKING, stop_ms=5_830)
    stopped = LineStop(number=1, line_ms=1_000, result=StopResult.STOPPED, stop_ms=788)

    assert metrics.stop_time([stopped, kept]).flags == ["kept_talking"]
    assert metrics.stop_time([stopped]).flags == []
    assert metrics.stop_time([stopped, kept]).value["p50_ms"] == 788
