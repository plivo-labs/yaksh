import json
from pathlib import Path
from typing import Any

import pytest

from yaksh.evaluation.trace_maps import reading
from yaksh.evaluation.trace_maps.reading import Framework, TraceSpan, covered_ns

FIXTURES = Path(__file__).parent / "fixtures" / "traces"
BASE_NS = 1_793_350_000_000_000_000
S = 1_000_000_000


class Trace:
    """Spans with times in seconds from the trace's start, as the plan's examples give them."""

    def __init__(self) -> None:
        self.spans: list[TraceSpan] = []

    def add(
        self, name: str, start: float, end: float, parent: str | None = None, **attributes: Any
    ) -> str:
        span_id = f"{len(self.spans) + 1:016x}"
        self.spans.append(
            TraceSpan(
                span_id,
                parent,
                name,
                BASE_NS + round(start * S),
                BASE_NS + round(end * S),
                {key.replace("__", "."): value for key, value in attributes.items()},
            )
        )
        return span_id


def fixture(name: str) -> list[TraceSpan]:
    data = json.loads((FIXTURES / name).read_text())
    return [TraceSpan(**span) for span in data["spans"]]


def parts(trace: Trace | list[TraceSpan]):
    found = reading(trace.spans if isinstance(trace, Trace) else trace)
    assert found is not None
    return found


def tool_reply(*, first_llm: bool = True, tool: bool = True, ttft: float | None = 0.35) -> Trace:
    """The plan's reply after a tool call, on the agent's clock: the caller stops at 4.000."""
    trace = Trace()
    user = trace.add(
        "user_turn", 0.0, 4.7, lk__end_of_turn_delay=0.70, lk__transcription_delay=0.35
    )
    trace.add("eou_detection", 4.6, 4.68, user)
    first = trace.add("agent_turn", 4.7, 6.0, lk__speech_id="s7", lk__generation_id="s7_1")
    if first_llm:
        trace.add("llm_node", 4.71, 5.4, first, lk__response__ttft=0.60)
    if tool:
        trace.add("function_tool", 5.4, 6.0, first)
    second = trace.add(
        "agent_turn",
        6.0,
        9.9,
        lk__speech_id="s7",
        lk__generation_id="s7_2",
        lk__parent_generation_id="s7_1",
        lk__e2e_latency=2.65,
    )
    llm = {"lk__response__ttft": ttft} if ttft is not None else {}
    trace.add("llm_node", 6.01, 7.2, second, **llm)
    trace.add("tts_node", 6.01, 9.8, second, lk__response__ttfb=0.18)
    trace.add("agent_speaking", 6.65, 9.9, second)
    return trace


def test_a_reply_after_a_tool_call_splits_the_agents_total() -> None:
    found = parts(tool_reply())
    [reply] = found.replies

    assert found.framework is Framework.LIVEKIT
    assert found.core[:2] == ("vad_and_stt", "turn_detection")
    assert reply.total_ms == 2650
    assert reply.parts == {
        "vad_and_stt": 600,
        "turn_detection": 100,
        "llm_inference": 950,
        "function_handler": 610,
        "speech_synthesis": 180,
        "pipeline": 210,
    }
    assert reply.stt_ttfs_ms == 350
    assert not reply.overlapping


@pytest.mark.parametrize(
    ("trace", "reason"),
    [
        (tool_reply(first_llm=False), "an llm_node or its TTFT is missing"),
        (tool_reply(ttft=None), "an llm_node or its TTFT is missing"),
        (tool_reply(tool=False), "a function_tool is missing"),
    ],
)
def test_a_reply_that_lost_a_span_or_a_value_is_incomplete_not_0_ms(
    trace: Trace, reason: str
) -> None:
    [reply] = parts(trace).replies

    assert reply.incomplete == reason
    assert reply.parts == {}
    assert reply.total_ms == 2650


def test_a_tool_reply_that_lost_its_first_turn_is_incomplete() -> None:
    trace = tool_reply()
    trace.spans = [
        span for span in trace.spans if span.attributes.get("lk.generation_id") != "s7_1"
    ]

    [reply] = parts(trace).replies
    assert reply.incomplete == "an earlier turn of the reply is missing"


def test_preemptive_generation_counts_llm_time_only_after_the_user_turn() -> None:
    trace = Trace()
    user = trace.add("user_turn", 0.0, 4.7, lk__end_of_turn_delay=0.70)
    trace.add("eou_detection", 4.6, 4.68, user)
    turn = trace.add("agent_turn", 4.45, 9.0, lk__speech_id="s1", lk__e2e_latency=1.4)
    trace.add("llm_node", 4.45, 6.0, turn, lk__response__ttft=0.60)
    trace.add("tts_node", 5.05, 7.0, turn, lk__response__ttfb=0.20)
    trace.add("agent_speaking", 5.4, 9.0, turn)

    [reply] = parts(trace).replies
    assert reply.parts["llm_inference"] == 350
    assert reply.parts["turn_detection"] == 100


def test_preemptive_synthesis_counts_tts_time_only_after_the_user_turn() -> None:
    trace = Trace()
    user = trace.add("user_turn", 0.0, 4.7, lk__end_of_turn_delay=0.70)
    trace.add("eou_detection", 4.6, 4.68, user)
    turn = trace.add("agent_turn", 4.05, 9.0, lk__speech_id="s1", lk__e2e_latency=1.0)
    trace.add("llm_node", 4.05, 6.0, turn, lk__response__ttft=0.25)
    trace.add("tts_node", 4.3, 7.0, turn, lk__response__ttfb=0.6)
    trace.add("agent_speaking", 5.0, 9.0, turn)

    [reply] = parts(trace).replies
    assert reply.parts["speech_synthesis"] == 200
    assert not reply.overlapping


@pytest.mark.parametrize("in_wait", [False, True], ids=["1.8.0", "1.8.10"])
def test_the_vad_check_divides_the_wait_before_the_turn_detection(in_wait: bool) -> None:
    """The VAD reported the end of speech at 4.600 and the final transcript came at 4.650.
    From LiveKit 1.8.10 the checks are children of an eou_wait span of the user turn."""
    trace = Trace()
    user = trace.add(
        "user_turn", 0.0, 4.7, lk__end_of_turn_delay=0.70, lk__transcription_delay=0.65
    )
    parent = trace.add("eou_wait", 4.0, 4.7, user) if in_wait else user
    trace.add("eou_detection", 4.6, 4.62, parent, lk__eou__source="vad")
    trace.add("eou_detection", 4.65, 4.68, parent, lk__eou__source="stt")
    turn = trace.add("agent_turn", 4.7, 9.0, lk__speech_id="s1", lk__e2e_latency=1.4)
    trace.add("llm_node", 4.7, 6.0, turn, lk__response__ttft=0.4)
    trace.add("tts_node", 5.1, 7.0, turn, lk__response__ttfb=0.2)
    trace.add("agent_speaking", 5.4, 9.0, turn)

    found = parts(trace)
    [reply] = found.replies
    assert found.core[:3] == ("endpointing_wait", "transcription", "turn_detection")
    assert [reply.parts[key] for key in found.core[:3]] == [600, 50, 50]


def test_a_turn_with_no_vad_check_takes_the_vad_wait_of_the_trace() -> None:
    """In the second turn the transcript was not final at the VAD's end, so LiveKit checked
    only when it came, at 14.900."""
    trace = Trace()
    first = trace.add("user_turn", 0.0, 4.7, lk__end_of_turn_delay=0.70)
    trace.add("eou_detection", 4.6, 4.62, first, lk__eou__source="vad")
    turn = trace.add("agent_turn", 4.7, 9.0, lk__speech_id="s1", lk__e2e_latency=1.4)
    trace.add("llm_node", 4.7, 6.0, turn, lk__response__ttft=0.4)
    trace.add("tts_node", 5.1, 7.0, turn, lk__response__ttfb=0.2)
    trace.add("agent_speaking", 5.4, 9.0, turn)
    second = trace.add("user_turn", 10.0, 15.0, lk__end_of_turn_delay=1.0)
    trace.add("eou_detection", 14.9, 14.95, second, lk__eou__source="stt")
    turn = trace.add("agent_turn", 15.0, 19.0, lk__speech_id="s2", lk__e2e_latency=1.6)
    trace.add("llm_node", 15.0, 16.0, turn, lk__response__ttft=0.3)
    trace.add("tts_node", 15.3, 17.0, turn, lk__response__ttfb=0.2)
    trace.add("agent_speaking", 15.6, 19.0, turn)

    [_, reply] = parts(trace).replies
    assert [reply.parts[key] for key in ("endpointing_wait", "transcription")] == [600, 300]
    assert reply.parts["turn_detection"] == 100


def test_the_greeting_and_a_reminder_are_anchors_not_replies() -> None:
    trace = Trace()
    greeting = trace.add("agent_turn", 0.5, 3.0, lk__speech_id="s0")
    trace.add("tts_node", 0.5, 1.0, greeting, lk__response__ttfb=0.3)
    trace.add("agent_speaking", 0.9, 3.0, greeting)
    user = trace.add("user_turn", 4.0, 6.0, lk__end_of_turn_delay=0.6)
    trace.add("eou_detection", 5.9, 6.0, user)
    reminder = trace.add("agent_turn", 14.0, 16.0, lk__speech_id="s2")
    trace.add("tts_node", 14.0, 14.5, reminder, lk__response__ttfb=0.2)
    trace.add("agent_speaking", 14.3, 16.0, reminder)

    found = parts(trace)
    assert found.replies == []
    assert len(found.anchors_ns) == 2


def test_a_filler_is_the_reply_and_the_answer_after_it_an_anchor() -> None:
    trace = Trace()
    user = trace.add("user_turn", 0.0, 2.0, lk__end_of_turn_delay=0.5)
    trace.add("eou_detection", 1.9, 2.0, user)
    filler = trace.add(
        "agent_turn", 2.0, 3.5, lk__speech_id="s1", lk__generation_id="s1_1", lk__e2e_latency=1.0
    )
    trace.add("llm_node", 2.0, 2.4, filler, lk__response__ttft=0.2)
    trace.add("tts_node", 2.2, 2.6, filler, lk__response__ttfb=0.2)
    trace.add("agent_speaking", 2.5, 3.5, filler)
    trace.add("function_tool", 2.4, 4.0, filler)
    answer = trace.add(
        "agent_turn",
        4.0,
        7.0,
        lk__speech_id="s1",
        lk__generation_id="s1_2",
        lk__parent_generation_id="s1_1",
    )
    trace.add("llm_node", 4.0, 4.8, answer, lk__response__ttft=0.4)
    trace.add("tts_node", 4.4, 5.0, answer, lk__response__ttfb=0.2)
    trace.add("agent_speaking", 4.7, 7.0, answer)

    found = parts(trace)
    [reply] = found.replies
    assert reply.speech_ns == BASE_NS + round(2.5 * S)
    assert reply.parts["function_handler"] == 0
    assert len(found.anchors_ns) == 2


def test_two_tools_at_the_same_time_count_once() -> None:
    trace = tool_reply()
    first = next(span for span in trace.spans if span.attributes.get("lk.generation_id") == "s7_1")
    trace.add("function_tool", 5.5, 5.9, first.span_id)

    [reply] = parts(trace).replies
    assert reply.parts["function_handler"] == 610


def test_a_reply_with_no_tts_node_is_incomplete() -> None:
    trace = tool_reply()
    trace.spans = [span for span in trace.spans if span.name != "tts_node"]

    [reply] = parts(trace).replies
    assert reply.incomplete == "a tts_node or its TTFB is missing"


def test_a_reply_after_a_handoff_takes_its_total_from_the_user_turn() -> None:
    """The tool hands the call to a new agent, whose turn speaks with no lk.e2e_latency."""
    trace = Trace()
    user = trace.add("user_turn", 0.0, 2.6, lk__end_of_turn_delay=1.15)
    trace.add("eou_detection", 2.05, 2.6, user)
    tool_turn = trace.add("agent_turn", 1.7, 3.45, lk__speech_id="a", lk__generation_id="a_1")
    trace.add("llm_node", 1.7, 3.45, tool_turn, lk__response__ttft=1.7)
    trace.add("function_tool", 3.42, 3.43, tool_turn)
    new_agent = trace.add("agent_turn", 3.52, 9.0, lk__speech_id="b", lk__generation_id="b_1")
    trace.add("llm_node", 3.52, 5.4, new_agent, lk__response__ttft=1.6)
    trace.add("tts_node", 5.12, 5.8, new_agent, lk__response__ttfb=0.23)
    trace.add("agent_speaking", 5.57, 9.0, new_agent)

    [reply] = parts(trace).replies
    assert reply.total_ms == 4120
    assert reply.incomplete is None
    assert reply.parts["function_handler"] == 100
    assert sum(reply.parts.values()) == reply.total_ms


def test_a_handoff_that_an_earlier_user_turn_started_is_no_reply_to_the_next() -> None:
    """The caller speaks again while the tool of the first user turn runs; the new agent then
    speaks with no lk.e2e_latency."""
    trace = Trace()
    first = trace.add("user_turn", 0.0, 2.6, lk__end_of_turn_delay=0.5)
    trace.add("eou_detection", 2.5, 2.6, first)
    tool_turn = trace.add("agent_turn", 2.6, 9.0, lk__speech_id="a", lk__generation_id="a_1")
    trace.add("llm_node", 2.6, 3.4, tool_turn, lk__response__ttft=0.7)
    trace.add("function_tool", 3.4, 8.9, tool_turn)
    second = trace.add("user_turn", 5.0, 6.6, lk__end_of_turn_delay=0.5)
    trace.add("eou_detection", 6.5, 6.6, second)
    new_agent = trace.add("agent_turn", 9.0, 14.0, lk__speech_id="b", lk__generation_id="b_1")
    trace.add("llm_node", 9.0, 10.0, new_agent, lk__response__ttft=0.6)
    trace.add("tts_node", 9.6, 10.5, new_agent, lk__response__ttfb=0.2)
    trace.add("agent_speaking", 9.8, 14.0, new_agent)

    assert parts(trace).replies == []


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        (
            "livekit_inbound_handoff.json",
            [
                (
                    2315,
                    {
                        "endpointing_wait": 609,
                        "transcription": 0,
                        "turn_detection": 538,
                        "llm_inference": 947,
                        "function_handler": 0,
                        "speech_synthesis": 184,
                        "pipeline": 38,
                    },
                ),
                (
                    2676,
                    {
                        "endpointing_wait": 609,
                        "transcription": 0,
                        "turn_detection": 962,
                        "llm_inference": 602,
                        "function_handler": 0,
                        "speech_synthesis": 355,
                        "pipeline": 148,
                    },
                ),
                (
                    4053,
                    {
                        "endpointing_wait": 609,
                        "transcription": 0,
                        "turn_detection": 1540,
                        "llm_inference": 1561,
                        "function_handler": 68,
                        "speech_synthesis": 213,
                        "pipeline": 61,
                    },
                ),
            ],
        ),
        (
            "livekit_outbound.json",
            [
                (
                    3256,
                    {
                        "endpointing_wait": 609,
                        "transcription": 0,
                        "turn_detection": 96,
                        "llm_inference": 2276,
                        "function_handler": 0,
                        "speech_synthesis": 160,
                        "pipeline": 115,
                    },
                ),
                (
                    4123,
                    {
                        "endpointing_wait": 609,
                        "transcription": 0,
                        "turn_detection": 550,
                        "llm_inference": 2419,
                        "function_handler": 97,
                        "speech_synthesis": 227,
                        "pipeline": 221,
                    },
                ),
                (
                    2412,
                    {
                        "endpointing_wait": 609,
                        "transcription": 0,
                        "turn_detection": 1166,
                        "llm_inference": 272,
                        "function_handler": 0,
                        "speech_synthesis": 187,
                        "pipeline": 177,
                    },
                ),
                (
                    3134,
                    {
                        "endpointing_wait": 609,
                        "transcription": 0,
                        "turn_detection": 1616,
                        "llm_inference": 0,
                        "function_handler": 0,
                        "speech_synthesis": 169,
                        "pipeline": 740,
                    },
                ),
            ],
        ),
    ],
)
def test_the_recorded_livekit_traces(name: str, expected: list[tuple[int, dict[str, int]]]) -> None:
    found = parts(fixture(name))

    assert [(reply.total_ms, reply.parts) for reply in found.replies] == expected
    assert all(reply.incomplete is None and not reply.overlapping for reply in found.replies)


def pipecat_turn(
    trace: Trace,
    conversation: str,
    start: float,
    *,
    llm_ttfbs: tuple[float | None, ...],
    latency: float | None,
) -> None:
    turn = trace.add(
        "turn",
        start,
        start + 6.0,
        conversation,
        **({"turn__user_bot_latency_seconds": latency} if latency is not None else {}),
    )
    at = start + 1.0
    for ttfb in llm_ttfbs:
        trace.add(
            "llm", at, at + 0.9, turn, **({"metrics__ttfb": ttfb} if ttfb is not None else {})
        )
        at += 1.0
    trace.add("tts", at, at + 1.0, turn, metrics__ttfb=0.2)


def test_a_pipecat_reply_with_two_llm_spans() -> None:
    trace = Trace()
    conversation = trace.add("conversation", 0.0, 30.0)
    pipecat_turn(trace, conversation, 0.0, llm_ttfbs=(0.4, 0.3), latency=2.6)

    found = parts(trace)
    [reply] = found.replies
    assert found.framework is Framework.PIPECAT
    assert reply.parts == {
        "end_of_turn": 400,
        "llm_inference": 700,
        "function_handler": 100,
        "sentence_aggregation": 700,
        "speech_synthesis": 200,
        "pipeline": 500,
    }


def test_the_recorded_pipecat_trace() -> None:
    """The caller's first line came in two VAD segments, so Pipecat started an LLM request and
    cancelled it before the reply. The first two replies call a tool that takes 0.6 s."""
    found = parts(fixture("pipecat_tool_calls.json"))

    assert found.framework is Framework.PIPECAT
    assert [(reply.total_ms, reply.parts) for reply in found.replies] == [
        (
            3308,
            {
                "end_of_turn": 354,
                "llm_inference": 1802,
                "function_handler": 604,
                "sentence_aggregation": 301,
                "speech_synthesis": 212,
                "pipeline": 36,
            },
        ),
        (
            2968,
            {
                "end_of_turn": 354,
                "llm_inference": 1673,
                "function_handler": 603,
                "sentence_aggregation": 117,
                "speech_synthesis": 188,
                "pipeline": 34,
            },
        ),
        (
            4128,
            {
                "end_of_turn": 3206,
                "llm_inference": 645,
                "function_handler": 0,
                "sentence_aggregation": 76,
                "speech_synthesis": 202,
                "pipeline": 0,
            },
        ),
    ]
    assert all(reply.incomplete is None and not reply.overlapping for reply in found.replies)


@pytest.mark.parametrize(
    ("llm_ttfbs", "reason"),
    [((None,), "an llm span or its TTFB is missing"), ((), "an llm span or its TTFB is missing")],
)
def test_a_pipecat_reply_without_metrics_or_llm_spans_is_incomplete(
    llm_ttfbs: tuple[float | None, ...], reason: str
) -> None:
    trace = Trace()
    conversation = trace.add("conversation", 0.0, 30.0)
    pipecat_turn(trace, conversation, 0.0, llm_ttfbs=llm_ttfbs, latency=2.0)

    [reply] = parts(trace).replies
    assert reply.incomplete == reason


def test_a_trace_that_no_reader_knows_gives_no_reading() -> None:
    trace = Trace()
    trace.add("http_request", 0.0, 1.0)
    assert reading(trace.spans) is None


def test_covered_time_counts_overlaps_once_and_clips_to_the_window() -> None:
    assert covered_ns([(0, 10), (5, 15), (20, 30)], 2, 25) == 18
