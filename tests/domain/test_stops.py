from collections.abc import Sequence

import pytest

from yaksh.domain.latency import AgentMedia, Span
from yaksh.domain.stops import LineStop, StopReason, StopResult, StopTime, line_stops

END_MS = 60_000
S = 28_227


def media(first_ms: int = 0, last_ms: int = END_MS, gaps: Sequence[Span] = ()) -> AgentMedia:
    return AgentMedia(first_ms=first_ms, last_ms=last_ms, gaps=list(gaps))


def span(start_ms: int, end_ms: int) -> Span:
    return Span(start_ms=start_ms, end_ms=end_ms)


def one(
    agent: Sequence[Span],
    *,
    start_ms: int = S,
    found: AgentMedia | None = None,
    end_ms: int = END_MS,
) -> LineStop:
    line = [span(start_ms, start_ms + 1_200)]
    [stop] = line_stops([(1, line)], agent, found or media(), end_ms)
    return stop


def test_speech_that_stops_within_the_window_is_a_stop() -> None:
    assert one([span(25_430, 29_014)]) == LineStop(
        number=1, line_ms=S, result=StopResult.STOPPED, stop_ms=787
    )


def test_speech_that_goes_on_past_the_window_kept_talking() -> None:
    stop = one([span(44_742, 52_614)], start_ms=46_784)

    assert (stop.result, stop.stop_ms, stop.at_least) == (StopResult.KEPT_TALKING, 5_830, False)


def test_a_sentence_that_ended_by_itself_is_a_stop_at_its_end() -> None:
    stop = one([span(S - 2_000, S + 337), span(S + 2_937, S + 5_000)])

    assert (stop.result, stop.stop_ms) == (StopResult.STOPPED, 337)


def test_speech_that_comes_back_after_a_stop_does_not_undo_it() -> None:
    stop = one([span(S - 1_000, S + 500), span(S + 1_500, S + 4_000)])

    assert (stop.result, stop.stop_ms) == (StopResult.STOPPED, 500)


def test_a_gap_where_the_speech_ends_leaves_the_stop_unknown() -> None:
    stop = one([span(S - 1_000, S + 300)], found=media(gaps=[span(S + 300, S + 1_000)]))

    assert (stop.result, stop.stop_ms, stop.reason) == (
        StopResult.UNKNOWN,
        None,
        StopReason.MEDIA_GAP,
    )


def test_a_gap_after_the_heard_quiet_keeps_the_stop() -> None:
    stop = one([span(S - 1_000, S + 800)], found=media(gaps=[span(S + 1_600, S + 2_000)]))

    assert (stop.result, stop.stop_ms) == (StopResult.STOPPED, 800)


def test_a_gap_after_the_window_keeps_the_heard_speech_as_the_least_time() -> None:
    stop = one([span(S - 1_000, S + 3_000)], found=media(gaps=[span(S + 3_000, S + 4_000)]))

    assert (stop.result, stop.stop_ms, stop.at_least, stop.reason) == (
        StopResult.KEPT_TALKING,
        3_000,
        True,
        StopReason.MEDIA_GAP,
    )


def test_a_gap_over_the_line_start_is_unknown_also_with_no_speech_there() -> None:
    stop = one([span(S - 3_000, S - 500)], found=media(gaps=[span(S - 500, S + 200)]))

    assert (stop.result, stop.reason) == (StopResult.UNKNOWN, StopReason.MEDIA_GAP)


@pytest.mark.parametrize(
    ("found", "why"),
    [
        (media(first_ms=S + 100), "the agent's media started after the line"),
        (media(last_ms=S), "the agent's media ended at the line"),
    ],
)
def test_the_line_start_outside_the_agents_media_is_unknown(found: AgentMedia, why: str) -> None:
    stop = one([span(S - 1_000, S + 500)], found=found)

    assert (stop.result, stop.reason) == (StopResult.UNKNOWN, StopReason.MEDIA_GAP), why


def test_a_call_with_no_record_of_the_agents_media_is_unknown() -> None:
    [stop] = line_stops([(1, [span(S, S + 900)])], [span(S - 1_000, S + 500)], None, END_MS)

    assert (stop.result, stop.reason) == (StopResult.UNKNOWN, StopReason.MEDIA_GAP)


def test_speech_that_ended_before_the_line_start_is_not_speaking() -> None:
    stop = one([span(S - 2_000, S - 50)])

    assert (stop.result, stop.line_ms, stop.stop_ms) == (StopResult.NOT_SPEAKING, S, None)


def test_speech_that_ends_exactly_at_the_line_start_does_not_hold_it() -> None:
    assert one([span(S - 2_000, S)]).result is StopResult.NOT_SPEAKING


def test_the_recording_ending_in_the_speech_gives_no_stop_within_the_window() -> None:
    within = one([span(S - 1_000, S + 1_200)], end_ms=S + 1_200)
    past = one([span(S - 1_000, S + 3_500)], end_ms=S + 3_500)

    assert (within.result, within.reason) == (StopResult.UNKNOWN, StopReason.RECORDING_ENDED)
    assert (past.result, past.stop_ms, past.at_least, past.reason) == (
        StopResult.KEPT_TALKING,
        3_500,
        True,
        StopReason.RECORDING_ENDED,
    )


def test_a_quiet_shorter_than_the_vad_stop_before_the_recording_ends_is_no_stop() -> None:
    stop = one([span(S - 1_000, S + 500)], end_ms=S + 700)

    assert (stop.result, stop.reason) == (StopResult.UNKNOWN, StopReason.RECORDING_ENDED)


def test_silence_after_the_agents_media_ended_is_no_quiet() -> None:
    stop = one([span(S - 1_000, S + 500)], found=media(last_ms=S + 500), end_ms=S + 5_000)

    assert (stop.result, stop.reason) == (StopResult.UNKNOWN, StopReason.MEDIA_GAP)


def test_two_lines_in_one_long_speech_each_count_from_their_own_start() -> None:
    later = S + 6_000
    stops = line_stops(
        [(1, [span(S, S + 900)]), (2, [span(later, later + 900)])],
        [span(S - 2_000, S + 9_000)],
        media(),
        END_MS,
    )

    assert [(stop.number, stop.result, stop.stop_ms) for stop in stops] == [
        (1, StopResult.KEPT_TALKING, 9_000),
        (2, StopResult.KEPT_TALKING, 3_000),
    ]


@pytest.mark.parametrize(
    ("stop_ms", "end_ms", "result", "at_least"),
    [
        (2_000, END_MS, StopResult.STOPPED, False),
        (2_001, END_MS, StopResult.KEPT_TALKING, False),
        (2_000, S + 2_000, StopResult.UNKNOWN, False),
        (2_001, S + 2_001, StopResult.KEPT_TALKING, True),
    ],
)
def test_the_window_holds_its_last_ms_when_the_stop_is_heard(
    stop_ms: int, end_ms: int, result: StopResult, at_least: bool
) -> None:
    stop = one([span(S - 1_000, S + stop_ms)], end_ms=end_ms)

    assert (stop.result, stop.at_least) == (result, at_least)


def test_a_line_with_no_speech_has_no_start_and_no_stop() -> None:
    [stop] = line_stops([(3, [])], [span(0, 5_000)], media(), END_MS)

    assert stop == LineStop(number=3, result=StopResult.UNKNOWN, reason=StopReason.NO_LINE_SPEECH)


def test_the_percentiles_count_only_the_lines_whose_speech_stopped_in_time() -> None:
    def line(result: StopResult, stop_ms: int | None) -> LineStop:
        return LineStop(number=1, line_ms=0, result=result, stop_ms=stop_ms)

    found = StopTime.of(
        [
            line(StopResult.STOPPED, 900),
            line(StopResult.STOPPED, 700),
            line(StopResult.KEPT_TALKING, 9_000),
            line(StopResult.NOT_SPEAKING, None),
        ]
    )

    assert (found.p50_ms, found.p90_ms) == (700, 900)
    assert found.counts == {
        StopResult.STOPPED: 2,
        StopResult.KEPT_TALKING: 1,
        StopResult.NOT_SPEAKING: 1,
        StopResult.UNKNOWN: 0,
    }
    assert StopTime.model_validate(found.model_dump(mode="json")) == found


def test_no_stopped_line_gives_no_percentiles() -> None:
    found = StopTime.of(
        [LineStop(number=1, line_ms=0, result=StopResult.KEPT_TALKING, stop_ms=3_000)]
    )

    assert (found.p50_ms, found.p90_ms) == (None, None)


@pytest.mark.parametrize(
    ("found", "end_ms", "result", "reason"),
    [
        (media(), 2_099, StopResult.UNKNOWN, StopReason.RECORDING_ENDED),
        (media(), 2_100, StopResult.STOPPED, None),
        (media(last_ms=2_099), END_MS, StopResult.UNKNOWN, StopReason.MEDIA_GAP),
        (media(last_ms=2_100), END_MS, StopResult.STOPPED, None),
        (media(gaps=[span(2_099, 2_200)]), END_MS, StopResult.UNKNOWN, StopReason.MEDIA_GAP),
        (media(gaps=[span(2_100, 2_200)]), END_MS, StopResult.STOPPED, None),
        (media(gaps=[span(800, 1_000)]), END_MS, StopResult.STOPPED, None),
        (media(first_ms=1_000), END_MS, StopResult.STOPPED, None),
        (media(gaps=[span(1_600, 1_700)]), 2_000, StopResult.UNKNOWN, StopReason.RECORDING_ENDED),
    ],
)
def test_the_quiet_after_the_speech_must_be_heard_for_the_whole_vad_stop(
    found: AgentMedia, end_ms: int, result: StopResult, reason: StopReason | None
) -> None:
    """The line starts at 1000 and the agent's speech ends at 1500: Yaksh must hear [1500, 2100)."""
    stop = one([span(1_000, 1_500)], start_ms=1_000, found=found, end_ms=end_ms)

    assert (stop.result, stop.reason) == (result, reason)


def test_a_recording_that_ends_at_the_line_start_did_not_hear_it() -> None:
    stop = one([span(0, 900)], start_ms=1_000, end_ms=1_000)

    assert (stop.result, stop.reason) == (StopResult.UNKNOWN, StopReason.MEDIA_GAP)


def test_a_line_with_no_speech_is_unknown_for_that_reason_first() -> None:
    [stop] = line_stops([(1, [])], [span(0, 5_000)], None, END_MS)

    assert stop.reason is StopReason.NO_LINE_SPEECH
