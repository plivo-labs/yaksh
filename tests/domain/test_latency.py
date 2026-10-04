from truman.domain.latency import Reply, nearest_rank, place, response_times


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
    speech_starts = [
        1_600,  # the agent greets first
        2_400,  # its second sentence, before the caller spoke: no new reply to answer
        6_200,  # the answer to the first reply
        7_500,  # starts inside the second reply: a talk-over
        8_600,  # more of the same answer; the talk-over already answered that reply
        11_900,  # the third reply got no answer before the fourth began
        14_300,  # inside the unfinished reply: no value, and not the fifth reply's answer
    ]

    measured = response_times(connected, caller_replies, speech_starts)

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
