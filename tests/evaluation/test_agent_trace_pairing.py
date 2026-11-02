import uuid
from datetime import UTC, datetime

from yaksh.db.models import AgentSpan
from yaksh.domain.latency import Wait
from yaksh.evaluation.agent_traces import (
    Alignment,
    Call,
    Trace,
    align,
    epoch_ns,
    parts_metric,
    read,
)
from yaksh.evaluation.trace_maps.reading import AgentReply, Framework, Reading

CLOCK = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)
CALL = Call(
    id=uuid.uuid4(),
    agent_id=uuid.uuid4(),
    number="+15550100001",
    clock_ns=epoch_ns(CLOCK),
    connected_at=CLOCK,
    ended_at=CLOCK,
)
CORE = ("vad_and_stt", "turn_detection", "llm_inference", "speech_synthesis", "pipeline")


def at(call_ms: int) -> int:
    """An agent time, on the agent's clock, that is call_ms on the call's clock."""
    return CALL.clock_ns + call_ms * 1_000_000


def wait(start_ms: int, answer_ms: int, **fields: bool) -> Wait:
    return Wait(
        start_ms=start_ms, answer_ms=answer_ms, until_ms=answer_ms, expects_answer=True, **fields
    )


def reply(speech_ms: int, total_ms: int, **fields) -> AgentReply:
    parts = {
        "vad_and_stt": 600,
        "turn_detection": 100,
        "llm_inference": total_ms - 900,
        "speech_synthesis": 200,
        "pipeline": 0,
    }
    return AgentReply(at(speech_ms), total_ms, parts, **fields)


def test_the_six_turn_example_aligns_at_the_median_gap() -> None:
    agent = [1100, 9600, 15000, 19400, 27000, 33000]
    yaksh = [1310, 9800, 15220, 19610, 27190]

    found = align(agent, yaksh)
    assert found == Alignment(offset_ms=210, aligned=5)


def test_a_clock_12_s_wrong_with_turns_10_s_apart_aligns_at_the_true_gap() -> None:
    agent = [0, 10_000, 20_000, 30_000]
    yaksh = [start + 12_200 for start in agent]

    assert align(agent, yaksh) == Alignment(offset_ms=12_200, aligned=4)


def test_two_gaps_that_align_as_many_starts_are_not_aligned() -> None:
    agent = [0, 10_000]
    yaksh = [5_000, 15_000, 25_000]

    assert align(agent, yaksh) is None


def test_a_single_start_links_by_number_only_when_the_recording_has_one_too() -> None:
    """Two Yaksh starts within 1 s do not compete as different gaps, so only the number rule
    refuses the single agent start that could be either."""
    assert align([1_000], [1_200, 1_900]) == Alignment(offset_ms=200, aligned=1)
    assert align([1_000], [1_200, 1_900], one_needs_one=True) is None
    assert align([1_000], [1_200], one_needs_one=True) == Alignment(offset_ms=200, aligned=1)


def metric(replies: list[AgentReply], waits: list[Wait], yaksh: list[int]) -> dict:
    reading = Reading(Framework.LIVEKIT, CORE, [r.speech_ns for r in replies], replies)
    return parts_metric(
        CALL, reading, Alignment(offset_ms=200, aligned=len(replies)), yaksh, waits
    ).value


def test_pairing_counts_each_reason_and_network_is_the_rest_of_the_wait() -> None:
    waits = [
        wait(5_000, 7_400),  # paired, network 400
        wait(9_000, 11_000),  # paired, but the agent's total is longer than the wait
        wait(13_000, 15_000, start_moved=True),  # not eligible: the agent was still speaking
        wait(1_000, 900),  # a talk-over: not eligible
        wait(0, 2_000, call_start=True),  # the greeting: not eligible
        wait(18_000, 20_500),  # no reply in the trace
    ]
    replies = [
        reply(7_200, 2_000),
        reply(10_800, 2_300),
        reply(30_000, 1_800),  # not heard on the call
        reply(22_800, 1_500, incomplete="a tts_node or its TTFB is missing"),
    ]
    yaksh = [2_000, 7_400, 11_000, 15_000, 20_500, 23_000]
    waits.append(wait(21_000, 23_000))

    value = metric(replies, waits, yaksh)
    assert {
        key: value[key]
        for key in ("eligible", "paired", "usable", "incomplete", "not_fitting", "not_heard")
    } == {
        "eligible": 4,
        "paired": 3,
        "usable": 1,
        "incomplete": 1,
        "not_fitting": 1,
        "not_heard": 1,
    }
    [first] = [entry for entry in value["by_reply"] if entry["speech_ms"] == 7_400]
    assert first["steps"]["network"] == 400


def test_a_total_up_to_100_ms_longer_than_the_wait_fits_with_no_network_time() -> None:
    value = metric([reply(7_200, 2_480)], [wait(5_000, 7_400)], [7_400])

    [entry] = value["by_reply"]
    assert entry["fits"] and entry["steps"]["network"] == 0


def test_percentiles_list_core_parts_and_skip_small_other_parts() -> None:
    replies = [reply(7_200, 2_000), reply(17_200, 3_000)]
    replies = [
        AgentReply(r.speech_ns, r.total_ms, r.parts | {"function_handler": 3}) for r in replies
    ]
    value = metric(replies, [wait(5_000, 7_400), wait(14_000, 17_400)], [7_400, 17_400])

    keys = [step["key"] for step in value["steps"]]
    assert keys == ["network", *CORE]
    llm = next(step for step in value["steps"] if step["key"] == "llm_inference")
    assert (llm["p50_ms"], llm["p90_ms"]) == (1_100, 2_100)


def test_no_usable_reply_gives_no_parts() -> None:
    incomplete = reply(7_200, 2_000, incomplete="a tts_node or its TTFB is missing")
    value = metric([incomplete], [wait(5_000, 7_400)], [7_400])

    assert (value["paired"], value["usable"], value["steps"]) == (1, 0, [])


def test_each_session_of_a_call_is_read_with_its_own_rules() -> None:
    """The first session has a turn detector, the second has none: the VAD wait of the first
    is not a rule of the second."""

    def session(trace_id: str, start: float, check: bool) -> Trace:
        spans: list[AgentSpan] = []

        def add(name: str, low: float, high: float, parent: str | None, **values: object) -> str:
            span_id = f"{len(spans) + 1:016x}"
            spans.append(
                AgentSpan(
                    trace_id=trace_id,
                    span_id=span_id,
                    parent_span_id=parent,
                    name=name,
                    start_ns=at(round((start + low) * 1000)),
                    end_ns=at(round((start + high) * 1000)),
                    attributes={key.replace("__", "."): value for key, value in values.items()},
                )
            )
            return span_id

        user = add("user_turn", 0.0, 4.7, None, lk__end_of_turn_delay=0.7)
        if check:
            add("eou_detection", 4.6, 4.62, user, lk__eou__source="vad")
        turn = add("agent_turn", 4.7, 9.0, None, lk__speech_id="s", lk__e2e_latency=1.4)
        add("llm_node", 4.7, 6.0, turn, lk__response__ttft=0.4)
        add("tts_node", 5.1, 7.0, turn, lk__response__ttfb=0.2)
        add("agent_speaking", 5.4, 9.0, turn)
        return Trace(trace_id, spans)

    found = read([session("a" * 32, 0.0, check=True), session("b" * 32, 20.0, check=False)])

    assert found is not None
    first, second = found.replies
    assert (first.parts["endpointing_wait"], second.parts["vad_and_stt"]) == (600, 700)
