"""Links an agent's trace to its test call, aligns it with the call's recording, and pairs its
replies with Yaksh's waits: the agent_reply_time metric. The evaluator runs this after the call,
once the spans had time to arrive, because the alignment needs the speech in the recording."""

import statistics
import uuid
from bisect import bisect_left, bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from itertools import pairwise
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from yaksh.db.models import Agent, AgentSpan, AgentTraceOwner, Conversation
from yaksh.domain.agents import Transport
from yaksh.domain.evaluations import Metric
from yaksh.domain.latency import AgentReplyTime, Span, Wait, nearest_rank
from yaksh.evaluation import trace_maps, trace_store
from yaksh.evaluation.agent_records import NotReady, connected_at
from yaksh.evaluation.trace_maps.reading import AgentReply, Reading, TraceSpan, ms

ALIGN_MS = 250
"""How near an agent speech start, moved by the offset, must be to a speech start that Yaksh
heard."""
MAX_GAP_MS = 60_000
"""The largest offset that alignment tries."""
DISTINCT_GAP_MS = 1_000
"""A gap more than this far from the best one is a different alignment."""
MAX_ANCHORS = 2_000
"""Alignment tries no trace with more agent speech starts than this: more than one each 2 s
of a 1-hour call, so such a trace is not one agent on one call."""
NUMBER_OFFSET_MS = 2_000
"""A trace that links by number must align within this offset: audio delay and clock error."""
CALL_MARGIN = timedelta(seconds=5)
"""A trace links by number only with a span from this long before the connection to this long
after the end."""
CLOCK_LAG_LOW_MS = -2_000
CLOCK_LAG_HIGH_MS = 7_000
"""The clock lags with which a trace can link by number: export delay, with a correct clock."""
CLOCK_OFF_MS = 2_000
"""A matching trace with a clock lag beyond this tells the card that the clock is wrong."""
ID_CLOCK_OFF_MS = 60_000
"""A trace linked by ID that did not align, with a clock lag beyond this: the gaps that
alignment tries are too short for it."""
LAST_SPAN_MARGIN_MS = 5_000
"""A trace matches a call for the clock check when its last span, moved by its clock lag, ends
this near the end of the call."""
FITS_FROM_MS = -100
"""A reply whose network and telephony time is below 0 but not below this fits, as 0: Yaksh's
voice detector can find a speech start up to about 50 ms late."""
PART_MS = 5
"""The least a part that is not core takes, at its 90th percentile, to be listed."""
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


class Status(StrEnum):
    NO_TRACES = "no_traces"
    NOT_ALIGNED = "not_aligned"
    CLOCK_OFF = "clock_off"
    UNKNOWN_FRAMEWORK = "unknown_framework"


async def wait_for_traces(
    sessionmaker: async_sessionmaker[AsyncSession],
    conversation: Conversation,
    *,
    now: datetime,
    wait_s: float,
) -> None:
    """Raise NotReady until wait_s after a connected phone call while a trace token exists:
    exporters send every few seconds, and Pipecat sends the span with the call's key last."""
    if (
        conversation.transport is not Transport.PHONE
        or conversation.ended_at is None
        or connected_at(conversation) is None
    ):
        return
    until = conversation.ended_at + timedelta(seconds=wait_s)
    if now >= until:
        return
    async with sessionmaker() as session:
        if await trace_store.current_token(session) is not None:
            raise NotReady(until, "waiting for the agent's traces")


def epoch_ns(at: datetime) -> int:
    return (at - EPOCH) // timedelta(microseconds=1) * 1000


@dataclass(frozen=True)
class Call:
    id: uuid.UUID
    agent_id: uuid.UUID
    number: str | None
    clock_ns: int
    """When the call's clock read 0, in ns from the Unix epoch."""
    connected_at: datetime
    ended_at: datetime

    def call_ms(self, agent_ns: int) -> int:
        return ms(agent_ns - self.clock_ns)


@dataclass(frozen=True)
class Alignment:
    offset_ms: int
    """Yaksh's speech start less the agent's, on the call's clock."""
    aligned: int


@dataclass(frozen=True)
class Trace:
    trace_id: str
    spans: list[AgentSpan]

    @property
    def clock_lag_ms(self) -> int:
        """The smallest difference between a span's arrival at Yaksh and its end on the agent's
        clock: the export delay with a correct clock."""
        return min(ms(epoch_ns(span.received_at) - span.end_ns) for span in self.spans)

    @property
    def first_start_ns(self) -> int:
        return min(span.start_ns for span in self.spans)

    @property
    def last_end_ns(self) -> int:
        return max(span.end_ns for span in self.spans)


def read(traces: Sequence[Trace]) -> Reading | None:
    """The call's traces as one reading. An agent can serve one call in several sessions, each
    with its own trace; each trace is read alone, because a reader's rules hold in one
    session, such as the VAD wait of its turns."""
    readings = [
        reading
        for trace in traces
        if (
            reading := trace_maps.reading(
                [
                    TraceSpan(
                        span.span_id,
                        span.parent_span_id,
                        span.name,
                        span.start_ns,
                        span.end_ns,
                        span.attributes,
                    )
                    for span in trace.spans
                ]
            )
        )
    ]
    if not readings:
        return None
    return Reading(
        framework=readings[0].framework,
        core=tuple(dict.fromkeys(key for reading in readings for key in reading.core)),
        anchors_ns=sorted(anchor for reading in readings for anchor in reading.anchors_ns),
        replies=sorted(
            (reply for reading in readings for reply in reading.replies),
            key=lambda reply: reply.speech_ns,
        ),
    )


class AgentTraces:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def metric(
        self, conversation: Conversation, heard: Sequence[Span], found: Sequence[Wait]
    ) -> Metric | None:
        """The agent_reply_time metric of a measured phone call, from heard, the agent's speech
        in the recording, and found, Yaksh's waits. None when the call has no trace and its
        agent has never linked one: the agent does not send traces."""
        call = call_of(conversation)
        if call is None:
            return None
        yaksh_ms = [span.start_ms for span in heard]
        async with self._sessionmaker() as session:
            linked = await self._link(session, call, yaksh_ms)
            if linked is None:
                return await self._unlinked(session, call)
            traces, alignment, reading = linked
            await session.execute(
                update(Agent).where(Agent.id == call.agent_id).values(traces_linked_at=func.now())
            )
            await session.commit()
        if reading is None:
            return status(Status.UNKNOWN_FRAMEWORK)
        if alignment is None:
            lag = min(trace.clock_lag_ms for trace in traces)
            if abs(lag) > ID_CLOCK_OFF_MS:
                return status(Status.CLOCK_OFF, clock_lag_ms=lag)
            return status(Status.NOT_ALIGNED)
        return parts_metric(call, reading, alignment, yaksh_ms, found)

    async def _link(
        self, session: AsyncSession, call: Call, yaksh_ms: Sequence[int]
    ) -> tuple[list[Trace], Alignment | None, Reading | None] | None:
        """The call's traces with their alignment and reading; None when no trace links. Each
        trace with the call's ID links, unless it has another call's ID too. By number, each
        candidate that passes alone links, unless two that pass overlap in time: the sessions
        of one call come one after another."""
        owned = list(
            await session.scalars(
                select(AgentTraceOwner.trace_id).where(AgentTraceOwner.conversation_id == call.id)
            )
        )
        if owned:
            traces = [await load(session, trace_id) for trace_id in owned]
            by_id = any(
                span.link_conversation_id == call.id for trace in traces for span in trace.spans
            )
            if by_id:
                # A session's trace that arrived after an earlier try of this evaluation.
                later = sorted(set(await with_id(session, call)) - set(owned))
                traces += await claim_all(session, call, later)
                traces.sort(key=lambda trace: trace.trace_id)
            return linked(call, traces, yaksh_ms, by_number=not by_id)
        if found := await with_id(session, call):
            traces = await claim_all(session, call, sorted(found))
            return linked(call, traces, yaksh_ms, by_number=False) if traces else None
        if call.number is None:
            return None
        passed = [
            trace
            for trace in await number_candidates(session, call)
            if CLOCK_LAG_LOW_MS <= trace.clock_lag_ms <= CLOCK_LAG_HIGH_MS
            and aligned(call, read([trace]), yaksh_ms, by_number=True) is not None
        ]
        if not passed or overlapping(passed):
            return None
        traces = [
            trace
            for trace in sorted(passed, key=lambda trace: trace.trace_id)
            if await claim(session, trace.trace_id, call.id)
        ]
        return linked(call, traces, yaksh_ms, by_number=True) if traces else None

    async def _unlinked(self, session: AsyncSession, call: Call) -> Metric | None:
        """Why a call has no trace: a wrong clock when one trace matches it after the move by
        its clock lag; else no traces, for an agent that has sent some before."""
        if call.number is not None:
            ended_ns = epoch_ns(call.ended_at)
            matching = [
                trace
                for trace in await arrived_during(session, call)
                if abs(ms(trace.last_end_ns - ended_ns) + trace.clock_lag_ms) <= LAST_SPAN_MARGIN_MS
            ]
            if len(matching) == 1 and abs(matching[0].clock_lag_ms) > CLOCK_OFF_MS:
                return status(Status.CLOCK_OFF, clock_lag_ms=matching[0].clock_lag_ms)
        linked_before = await session.scalar(
            select(Agent.traces_linked_at).where(Agent.id == call.agent_id)
        )
        return status(Status.NO_TRACES) if linked_before is not None else None


def linked(
    call: Call, traces: list[Trace], yaksh_ms: Sequence[int], *, by_number: bool
) -> tuple[list[Trace], Alignment | None, Reading | None]:
    reading = read(traces)
    return traces, aligned(call, reading, yaksh_ms, by_number=by_number), reading


def overlapping(traces: Sequence[Trace]) -> bool:
    ordered = sorted(traces, key=lambda trace: trace.first_start_ns)
    return any(later.first_start_ns < earlier.last_end_ns for earlier, later in pairwise(ordered))


def call_of(conversation: Conversation) -> Call | None:
    connected = connected_at(conversation)
    if (
        conversation.transport is not Transport.PHONE
        or connected is None
        or conversation.clock_started_at is None
        or conversation.ended_at is None
    ):
        return None
    return Call(
        id=conversation.id,
        agent_id=conversation.agent_id,
        number=conversation.caller_number,
        clock_ns=epoch_ns(conversation.clock_started_at),
        connected_at=connected,
        ended_at=conversation.ended_at,
    )


async def load(session: AsyncSession, trace_id: str) -> Trace:
    spans = await session.scalars(
        select(AgentSpan).where(AgentSpan.trace_id == trace_id).order_by(AgentSpan.start_ns)
    )
    return Trace(trace_id, list(spans))


async def with_id(session: AsyncSession, call: Call) -> list[str]:
    return list(
        await session.scalars(
            select(AgentSpan.trace_id).where(AgentSpan.link_conversation_id == call.id).distinct()
        )
    )


async def claim_all(session: AsyncSession, call: Call, trace_ids: Sequence[str]) -> list[Trace]:
    """The traces among trace_ids, all with the call's ID, that the call now owns. A trace that
    also has another call's ID links to neither."""
    traces = []
    for trace_id in trace_ids:
        trace = await load(session, trace_id)
        if all(
            span.link_conversation_id in (None, call.id) for span in trace.spans
        ) and await claim(session, trace_id, call.id):
            traces.append(trace)
    return traces


async def claim(session: AsyncSession, trace_id: str, conversation_id: uuid.UUID) -> bool:
    """Make the call the trace's owner unless another call is; True when this call is. The
    caller commits once it claimed all the traces of the call, in the order of their IDs, so
    that a failure leaves none of them owned and a retry links them all."""
    await session.execute(
        insert(AgentTraceOwner)
        .values(trace_id=trace_id, conversation_id=conversation_id)
        .on_conflict_do_nothing(index_elements=[AgentTraceOwner.trace_id])
    )
    owner = await session.scalar(
        select(AgentTraceOwner.conversation_id).where(AgentTraceOwner.trace_id == trace_id)
    )
    return owner == conversation_id


async def unowned(session: AsyncSession, trace_ids: Sequence[str]) -> list[Trace]:
    """The traces among trace_ids that no call owns and that have no span with a call's ID:
    a trace with an ID never links by number."""
    if not trace_ids:
        return []
    taken = set(
        await session.scalars(
            select(AgentTraceOwner.trace_id).where(AgentTraceOwner.trace_id.in_(trace_ids))
        )
    ) | set(
        await session.scalars(
            select(AgentSpan.trace_id)
            .where(AgentSpan.trace_id.in_(trace_ids), AgentSpan.link_conversation_id.is_not(None))
            .distinct()
        )
    )
    return [await load(session, trace_id) for trace_id in trace_ids if trace_id not in taken]


async def number_candidates(session: AsyncSession, call: Call) -> list[Trace]:
    """The traces with the call's number and a span in the call's time, on the agent's clock."""
    low = epoch_ns(call.connected_at - CALL_MARGIN)
    high = epoch_ns(call.ended_at + CALL_MARGIN)
    trace_ids = await session.scalars(
        select(AgentSpan.trace_id)
        .where(
            AgentSpan.link_number == call.number,
            AgentSpan.start_ns <= high,
            AgentSpan.end_ns >= low,
        )
        .distinct()
    )
    return await unowned(session, list(trace_ids))


async def arrived_during(session: AsyncSession, call: Call) -> list[Trace]:
    """The traces with the call's number and a span that arrived after the call connected, on
    Yaksh's clock, so a wrong clock on the agent does not change the choice."""
    trace_ids = await session.scalars(
        select(AgentSpan.trace_id)
        .where(AgentSpan.link_number == call.number, AgentSpan.received_at > call.connected_at)
        .distinct()
    )
    return await unowned(session, list(trace_ids))


def aligned(
    call: Call, reading: Reading | None, yaksh_ms: Sequence[int], *, by_number: bool
) -> Alignment | None:
    if reading is None:
        return None
    if len(reading.anchors_ns) > MAX_ANCHORS:
        return None
    agent_ms = [call.call_ms(anchor) for anchor in reading.anchors_ns]
    found = align(
        agent_ms,
        yaksh_ms,
        one_needs_one=by_number,
        max_gap_ms=NUMBER_OFFSET_MS if by_number else MAX_GAP_MS,
    )
    if found is None or (by_number and abs(found.offset_ms) > NUMBER_OFFSET_MS):
        return None
    return found


def align(
    agent_ms: Sequence[int],
    yaksh_ms: Sequence[int],
    *,
    one_needs_one: bool = False,
    max_gap_ms: int = MAX_GAP_MS,
) -> Alignment | None:
    """The offset that moves the agent's speech starts onto Yaksh's. Each gap of up to
    max_gap_ms between an agent start and a Yaksh start is tried; its score is how many agent
    starts it aligns, one to one. The best gap counts when it aligns 2 starts or more (1 when
    the agent has only 1, and with one_needs_one, Yaksh too), and more starts than every gap
    more than DISTINCT_GAP_MS away. The offset is the median gap of the starts it aligned.
    A number link tries only the gaps that it can use: a trace of one session of the call has
    part of the call's speech, which can also fit a gap many seconds away."""
    scored = []
    for gap in sorted({y - a for a in agent_ms for y in yaksh_ms if abs(y - a) <= max_gap_ms}):
        scored.append((gap, matches(agent_ms, yaksh_ms, gap)))
    if not scored:
        return None
    best_gap, best = max(scored, key=lambda item: len(item[1]))
    single = len(agent_ms) == 1 and (not one_needs_one or len(yaksh_ms) == 1)
    if len(best) < (1 if single else 2):
        return None
    if any(
        len(pairs) >= len(best) for gap, pairs in scored if abs(gap - best_gap) > DISTINCT_GAP_MS
    ):
        return None
    return Alignment(offset_ms=round(statistics.median(y - a for a, y in best)), aligned=len(best))


def matches(agent_ms: Sequence[int], yaksh_ms: Sequence[int], gap: int) -> list[tuple[int, int]]:
    """The agent starts that the gap moves within ALIGN_MS of a Yaksh start, nearest first,
    each start in one pair at most."""
    heard = sorted(yaksh_ms)
    near = sorted(
        (abs(y - (a + gap)), a, y)
        for a in agent_ms
        for y in heard[
            bisect_left(heard, a + gap - ALIGN_MS) : bisect_right(heard, a + gap + ALIGN_MS)
        ]
    )
    used_a: set[int] = set()
    used_y: set[int] = set()
    pairs = []
    for _, a, y in near:
        if a not in used_a and y not in used_y:
            used_a.add(a)
            used_y.add(y)
            pairs.append((a, y))
    return pairs


def eligible(found: Sequence[Wait]) -> list[Wait]:
    """The answered waits that start at the end of the caller's speech: the agent's total
    measures the same time. A talk-over has no wait."""
    return [
        wait
        for wait in found
        if wait.expects_answer
        and not wait.media_gap
        and not wait.start_moved
        and not wait.call_start
        and wait.start_ms is not None
        and wait.answer_ms is not None
        and wait.answer_ms >= wait.start_ms
    ]


def parts_metric(
    call: Call,
    reading: Reading,
    alignment: Alignment,
    yaksh_ms: Sequence[int],
    found: Sequence[Wait],
) -> Metric:
    waits = eligible(found)
    moved = [
        (call.call_ms(reply.speech_ns) + alignment.offset_ms, reply) for reply in reading.replies
    ]
    not_heard = sum(
        1 for at, _ in moved if not any(abs(start - at) <= ALIGN_MS for start in yaksh_ms)
    )
    near = sorted(
        (abs(at - wait.answer_ms), index, reply_index)
        for index, wait in enumerate(waits)
        for reply_index, (at, _) in enumerate(moved)
        if wait.answer_ms is not None and abs(at - wait.answer_ms) <= ALIGN_MS
    )
    paired: dict[int, AgentReply] = {}
    taken: set[int] = set()
    for _, index, reply_index in near:
        if index not in paired and reply_index not in taken:
            paired[index] = moved[reply_index][1]
            taken.add(reply_index)
    by_reply = [reply_time(waits[index], paired[index]) for index in sorted(paired)]
    usable = [reply for reply in by_reply if reply.steps is not None]
    return Metric(
        value={
            "status": "ok",
            "framework": reading.framework.value,
            "eligible": len(waits),
            "paired": len(paired),
            "usable": len(usable),
            "incomplete": sum(1 for reply in by_reply if not reply.complete),
            "not_fitting": sum(1 for reply in by_reply if reply.complete and not reply.fits),
            "not_heard": not_heard,
            "overlapping": sum(1 for reply in usable if reply.overlapping),
            "offset_ms": alignment.offset_ms,
            "steps": percentiles(usable, ("network", *reading.core)),
            "stt_ttfs": stt_percentiles(usable),
            "by_reply": [reply.model_dump(mode="json") for reply in by_reply],
        }
    )


def reply_time(wait: Wait, reply: AgentReply) -> AgentReplyTime:
    """One paired reply: network and telephony is Yaksh's wait less the agent's total."""
    assert wait.answer_ms is not None and wait.start_ms is not None
    complete = reply.incomplete is None and reply.total_ms is not None
    network = wait.answer_ms - wait.start_ms - (reply.total_ms or 0)
    fits = complete and network >= FITS_FROM_MS
    return AgentReplyTime(
        speech_ms=wait.answer_ms,
        agent_ms=reply.total_ms,
        complete=complete,
        fits=fits,
        overlapping=reply.overlapping,
        stt_ttfs_ms=reply.stt_ttfs_ms,
        reason=reply.incomplete,
        steps={"network": max(network, 0)} | reply.parts if fits else None,
    )


def percentiles(usable: Sequence[AgentReplyTime], core: Sequence[str]) -> list[dict[str, Any]]:
    """Each part over the usable replies, a missing part as 0: core parts always, another part
    when its 90th percentile is PART_MS or more. No parts with no usable reply."""
    if not usable:
        return []
    times = [reply.steps or {} for reply in usable]
    keys = list(dict.fromkeys([*core, *(key for steps in times for key in steps)]))
    steps = []
    for key in keys:
        values = sorted(step.get(key, 0) for step in times)
        p90 = nearest_rank(values, 0.9)
        if key in core or (p90 is not None and p90 >= PART_MS):
            steps.append({"key": key, "p50_ms": nearest_rank(values, 0.5), "p90_ms": p90})
    return steps


def stt_percentiles(usable: Sequence[AgentReplyTime]) -> dict[str, Any] | None:
    values = sorted(reply.stt_ttfs_ms for reply in usable if reply.stt_ttfs_ms is not None)
    if not values:
        return None
    return {
        "replies": len(values),
        "p50_ms": nearest_rank(values, 0.5),
        "p90_ms": nearest_rank(values, 0.9),
    }


def status(name: str, **values: int) -> Metric:
    return Metric(value={"status": name} | values)
