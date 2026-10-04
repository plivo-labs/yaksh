from collections.abc import Sequence

from truman.domain.latency import Latency, Reply, Span, Wait, nearest_rank, place, waits


def spoke(*starts: int, ms: int = 300) -> list[Span]:
    return [Span(start_ms=start, end_ms=start + ms) for start in starts]


def paired(
    connected: int,
    caller_replies: Sequence[tuple[int, int | None]],
    agent: list[Span],
    end_ms: int,
    *,
    goodbye_from_ms: int | None = None,
    gaps: list[Span] | None = None,
    agent_opens: bool = True,
) -> list[Wait]:
    return waits(
        connected,
        caller_replies,
        agent,
        end_ms,
        goodbye_from_ms=goodbye_from_ms,
        gaps=gaps or [],
        agent_opens=agent_opens,
    )


def test_replies_are_paired_with_the_agent_speech_that_answers_them() -> None:
    connected = 1_000
    caller_replies = [
        (3_000, 5_000),
        (7_000, 8_000),
        (9_000, 9_500),
        (11_000, 11_400),
        (13_000, 13_600),
        (14_000, None),  # the call ended during this reply, so Pipecat reported no end
    ]
    agent = spoke(
        1_600,  # the agent greets first
        2_400,  # its second sentence, before the caller spoke: no new reply to answer
        6_200,  # the answer to the first reply
        7_500,  # starts inside the second reply: a talk-over
        8_600,  # more of the same answer; the talk-over already answered that reply
        11_900,  # the third reply got no answer before the fourth began
        14_300,  # inside the unfinished reply: no value, and not the fifth reply's answer
    )

    measured = Latency.answered(paired(connected, caller_replies, agent, 20_000))

    assert measured.replies == [
        Reply(start_ms=1_000, speech_ms=1_600),
        Reply(start_ms=5_000, speech_ms=6_200),
        Reply(start_ms=8_000, speech_ms=7_500),
        Reply(start_ms=11_400, speech_ms=11_900),
    ]
    assert [reply.response_ms for reply in measured.replies] == [600, 1_200, None, 500]
    assert (measured.p50_ms, measured.p90_ms) == (600, 1_200)
    assert nearest_rank(list(range(1, 11)), 0.9) == 9
    assert nearest_rank([], 0.5) is None
    # A transcript turn starts late, so a turn just before the next reply's speech is still the
    # late turn of this reply; the next reply takes the turn after it.
    early, late = Reply(start_ms=1_000, speech_ms=1_500), Reply(start_ms=2_000, speech_ms=2_400)
    assert place([2_350, 2_500], [early, late]) == [early, late]
    # The agent was already speaking when Truman's stream opened: its greeting has no start to
    # measure, and its next sentence is not taken for one.
    speaking = paired(1_000, [(3_000, 4_000)], spoke(200, 2_400, 4_500), 6_000)
    assert Latency.answered(speaking).replies == [Reply(start_ms=4_000, speech_ms=4_500)]


def test_each_wait_says_how_long_the_caller_waited_and_whether_it_was_answered() -> None:
    caller_replies = [(3_000, 4_000), (9_000, 9_500), (12_000, 12_400), (14_000, None)]

    found = paired(
        1_000, caller_replies, spoke(1_600, 5_200, 12_300), 15_000, goodbye_from_ms=12_000
    )

    assert [
        (w.answer_ms, w.wait_ms, w.talked_over, w.unanswered, w.expects_answer) for w in found
    ] == [
        (1_600, 600, False, False, True),
        (5_200, 1_200, False, False, True),
        # no answer before the caller spoke again: the wait ran to the caller's next reply
        (None, 2_500, False, True, True),
        # the goodbye, talked over by the agent's own goodbye
        (12_300, None, True, False, False),
        # cut off by the end of the call
        (None, None, False, False, False),
    ]
    # The goodbye's answer is not a response time either.
    assert [r.speech_ms for r in Latency.answered(found).replies] == [1_600, 5_200]


def test_the_wait_starts_where_the_agent_stopped_when_it_spoke_over_the_reply() -> None:
    agent = [Span(start_ms=5_000, end_ms=12_000), Span(start_ms=12_700, end_ms=14_000)]

    [opening, reply] = paired(4_000, [(5_500, 6_500)], agent, 20_000)

    assert (opening.answer_ms, opening.wait_ms) == (5_000, 1_000)
    assert (reply.start_ms, reply.answer_ms, reply.wait_ms) == (12_000, 12_700, 700)


def test_a_media_gap_cuts_a_wait_short_and_an_opening_by_the_caller_expects_nothing() -> None:
    found = paired(
        1_000,
        [(2_000, 2_500), (9_000, 9_400)],
        spoke(6_000),
        30_000,
        gaps=[Span(start_ms=3_000, end_ms=4_000)],
        agent_opens=False,
    )

    assert found == [
        Wait(start_ms=1_000, answer_ms=None, until_ms=2_000, expects_answer=False),
        Wait(start_ms=2_500, answer_ms=6_000, until_ms=3_000, expects_answer=True, media_gap=True),
        # nothing more before the call ended: a long wait, but not an unanswered reply
        Wait(start_ms=9_400, answer_ms=None, until_ms=30_000, expects_answer=True, ran_to_end=True),
    ]
    assert [w.wait_ms for w in found] == [1_000, 500, 20_600]
    assert not any(w.unanswered for w in found)
    assert Latency.answered(found).replies == []
