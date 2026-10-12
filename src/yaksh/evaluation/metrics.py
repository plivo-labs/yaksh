"""The code metrics of one saved call: pure functions over what the call stored and what the
evaluator heard in its audio. Each returns the metric's value and the flags it raised."""

import re
from collections.abc import Sequence
from difflib import SequenceMatcher

from yaksh.domain.conversations import (
    CallerSettings,
    CallerUsage,
    LineFacts,
    Provenance,
    Role,
    Transcript,
    Turn,
    WireEventKind,
)
from yaksh.domain.evaluations import Metric
from yaksh.domain.latency import Span, Speech, Wait

WAIT_LIMITS_MS = (3_000, 5_000, 10_000)
LONG_WAIT_MS = 5_000
DEAD_AIR_MS = 10_000
MONOLOGUE_MS = 45_000
STALL_MS = 100
"""A worker event-loop stall longer than this also delayed the call's audio."""
REPEATED = 0.9
"""How alike two agent answers are, from 0 to 1, to count as the same answer."""
REPEATS = 3
"""How many same answers in a row make a repetition."""


def goodbye_from(transcript: Transcript) -> int | None:
    """When the caller started to say goodbye. When the caller's model ends the call with
    words, its goodbye is the reply going out at the mark. After a silent end, Yaksh marks
    the end first and says the goodbye after it, so the goodbye is the next reply. With no
    reply at or after the mark, the goodbye had finished before it: the last reply. The event
    does not say which end it was, so a worded goodbye that finished before the mark, followed
    by one more reply, is taken for a silent end. At the turn limit, Yaksh marks the limit
    before the goodbye."""
    end = next(
        (
            event
            for event in transcript.wire_events
            if event.kind in (WireEventKind.END_CALL, WireEventKind.TURN_LIMIT)
        ),
        None,
    )
    if end is None:
        return None
    if end.kind is WireEventKind.TURN_LIMIT:
        return end.at_ms
    replies = transcript.caller_replies or []
    going = [
        reply.start_ms
        for reply in replies
        if reply.start_ms <= end.at_ms and (reply.end_ms is None or reply.end_ms >= end.at_ms)
    ]
    after = [reply.start_ms for reply in replies if reply.start_ms > end.at_ms]
    before = [reply.start_ms for reply in replies if reply.start_ms <= end.at_ms]
    if going:
        return going[-1]
    if after:
        return after[0]
    return before[-1] if before else end.at_ms


def turn_taking(waits: Sequence[Wait]) -> Metric:
    """How the agent answered the caller, over the waits that expected an answer. A wait that a
    media gap cut short counts with the length Yaksh heard."""
    counted = [wait for wait in waits if wait.expects_answer]
    lengths = [wait.wait_ms for wait in counted if wait.wait_ms is not None]
    unanswered = sum(wait.unanswered for wait in counted)
    longest = max(lengths, default=None)
    flags = [
        flag
        for flag, raised in (
            ("unanswered", unanswered > 0),
            ("long_wait", longest is not None and longest >= LONG_WAIT_MS),
            ("dead_air", longest is not None and longest >= DEAD_AIR_MS),
            ("media_gap", any(wait.media_gap for wait in counted)),
        )
        if raised
    ]
    return Metric(
        value={
            "waits": [wait.model_dump(mode="json") for wait in waits],
            "expected": len(counted),
            "unanswered": unanswered,
            "talked_over": sum(wait.talked_over for wait in counted),
            "at_least_ms": {
                str(limit): sum(length >= limit for length in lengths) for limit in WAIT_LIMITS_MS
            },
            "longest_wait_ms": longest,
        },
        flags=flags,
    )


def speaking(speech: Speech, goodbye_from_ms: int | None) -> Metric:
    """How much each side spoke before the caller's goodbye, and the agent's longest
    monologue: the most agent speech with no caller speech in it or between its parts."""
    agent = [s for s in speech.agent if goodbye_from_ms is None or s.start_ms < goodbye_from_ms]
    caller = [s for s in speech.caller if goodbye_from_ms is None or s.start_ms < goodbye_from_ms]
    agent_ms = sum(span.end_ms - span.start_ms for span in agent)
    caller_ms = sum(span.end_ms - span.start_ms for span in caller)
    longest = run = 0
    last_end: int | None = None
    for start, end in sorted(part for span in agent for part in outside(span, caller)):
        if last_end is not None and any(c.start_ms < start and c.end_ms > last_end for c in caller):
            run = 0
        run += end - start
        longest = max(longest, run)
        last_end = end
    total = agent_ms + caller_ms
    return Metric(
        value={
            "agent_ms": agent_ms,
            "caller_ms": caller_ms,
            "agent_share": round(agent_ms / total, 3) if total else None,
            "longest_monologue_ms": longest,
        },
        flags=["monologue"] if longest >= MONOLOGUE_MS else [],
    )


def outside(span: Span, others: Sequence[Span]) -> list[tuple[int, int]]:
    """The parts of span that none of others covers."""
    parts = []
    start = span.start_ms
    for other in sorted(others, key=lambda other: other.start_ms):
        if other.end_ms <= start or other.start_ms >= span.end_ms:
            continue
        if other.start_ms > start:
            parts.append((start, other.start_ms))
        start = max(start, other.end_ms)
    if start < span.end_ms:
        parts.append((start, span.end_ms))
    return parts


def agent_repetition(turns: Sequence[Turn]) -> Metric:
    """Runs of the same agent answer, given again after each caller reply. The agent turns
    between two caller turns are one answer."""
    answers: list[Turn] = []
    joined: list[str] = []
    after_caller = True
    for turn in turns:
        if turn.role is Role.CALLER:
            after_caller = True
        elif after_caller:
            answers.append(turn)
            joined.append(words(turn.text))
            after_caller = False
        else:
            joined[-1] = f"{joined[-1]} {words(turn.text)}"
    runs: list[dict[str, object]] = []
    start = 0
    for index in range(1, len(joined) + 1):
        if index < len(joined) and alike(joined[index - 1], joined[index]):
            continue
        if index - start >= REPEATS:
            first = answers[start]
            runs.append({"text": first.text, "count": index - start, "at_ms": first.started_at_ms})
        start = index
    return Metric(value={"runs": runs}, flags=["repetition"] if runs else [])


def words(text: str) -> str:
    return " ".join(re.findall(r"\w+", text.casefold()))


def alike(first: str, second: str) -> bool:
    return SequenceMatcher(None, first, second).ratio() >= REPEATED


def capture_faults(transcript: Transcript, recorded: bool, gaps: Sequence[Span]) -> Metric:
    """What went wrong on Yaksh's side of a connected call, so its other metrics can be read
    with care. The end of a call can leave its last reply, and words that never went out,
    unconfirmed, so only caller turns before the last reply count. gaps are where no media
    came from the agent's side."""
    replies = transcript.caller_replies or []
    last = replies[-1].start_ms if replies else None
    unconfirmed = sum(
        turn.role is Role.CALLER
        and turn.provenance is Provenance.UNCONFIRMED
        and last is not None
        and turn.started_at_ms < last
        for turn in transcript.turns
    )
    lag = transcript.loop_lag
    stall = lag if lag is not None and lag.max_ms > STALL_MS else None
    caller_error = (
        transcript.validity.reasons if transcript.validity and not transcript.validity.ok else []
    )
    flags = [
        flag
        for flag, raised in (
            ("caller_error", bool(caller_error)),
            ("unconfirmed_caller_turns", unconfirmed > 0),
            ("missing_recording", not recorded),
            ("no_agent_media", transcript.agent_media is None),
            ("media_gap", bool(gaps)),
            ("worker_stall", stall is not None),
        )
        if raised
    ]
    return Metric(
        value={
            "caller_error": caller_error,
            "unconfirmed_caller_turns": unconfirmed,
            "media_gaps": len(gaps),
            "media_gap_ms": sum(gap.end_ms - gap.start_ms for gap in gaps),
            "worker_stall": None
            if stall is None
            else {"max_ms": stall.max_ms, "at_ms": stall.max_at_ms},
        },
        flags=flags,
    )


def incomplete_record() -> Metric:
    """A connected call whose worker stopped before it saved the call in full: its other
    faults are unknown, as are its speech metrics."""
    return Metric(value={"incomplete_record": True}, flags=["incomplete_record"])


def usage(
    transcript: Transcript,
    settings: CallerSettings | None,
    consumed: CallerUsage | None,
    line: LineFacts | None,
) -> Metric:
    """What the call cost in units, and how long it took to connect, from when Yaksh started
    the call."""
    firsts: dict[WireEventKind, int] = {}
    for event in transcript.wire_events:
        firsts.setdefault(event.kind, event.at_ms)
    started = firsts.get(WireEventKind.CONNECT_STARTED)

    def since_start(at_ms: int | None) -> int | None:
        return None if started is None or at_ms is None else at_ms - started

    return Metric(
        value={
            "settings": settings.model_dump(mode="json") if settings else None,
            "usage": consumed.model_dump(mode="json") if consumed else None,
            "bill_duration_s": line.bill_duration_s if line else None,
            "ringing_ms": since_start(firsts.get(WireEventKind.RINGING)),
            "answered_ms": since_start(firsts.get(WireEventKind.ANSWERED)),
            "stream_opened_ms": since_start(transcript.stream_opened_ms),
        }
    )
