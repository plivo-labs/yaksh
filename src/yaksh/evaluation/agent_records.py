from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from yaksh.db.models import AgentRecordRow, AgentVersion, Conversation, Evaluation
from yaksh.domain.agent_records import (
    AgentRecord,
    CallRef,
    Found,
    Lookup,
    Missing,
    Pending,
    RecordReader,
    RecordState,
    RecordStatus,
    RecordTool,
    RecordTurn,
    StoredRecord,
)
from yaksh.domain.agents import AgentConfig, Transport
from yaksh.domain.conversations import Transcript, Turn, WireEventKind
from yaksh.domain.evaluations import EvaluationState
from yaksh.domain.record_sources import RecordProvider, RecordSource
from yaksh.domain.settings import Secrets
from yaksh.domain.triggers import Filler, RenderError
from yaksh.evaluation.call import judged

PAIR_MARGIN_MS = 4000
"""How far a record line's time can be from a Yaksh turn and still belong to it. A provider
logs a line at its own moment: on live calls, Plivo CX logged an agent line when its speech
ended and a caller line up to 0.9 s after it."""


class NotReady(Exception):
    """The record is not final yet: evaluate the call again at `until`."""

    def __init__(self, until: datetime, reason: str) -> None:
        super().__init__(reason)
        self.until = until


def connected_at(conversation: Conversation) -> datetime | None:
    transcript = Transcript.model_validate(conversation.transcript or {})
    event = next(
        (event for event in transcript.wire_events if event.kind is WireEventKind.CONNECTED), None
    )
    if event is None or conversation.clock_started_at is None:
        return None
    return conversation.clock_started_at + timedelta(milliseconds=event.at_ms)


def applies(conversation: Conversation, agent: AgentConfig) -> bool:
    return (
        agent.record_source is not None
        and conversation.transport is Transport.PHONE
        and conversation.caller_number is not None
        and judged(conversation)
        and connected_at(conversation) is not None
    )


def call_ref(conversation: Conversation) -> CallRef:
    connected = connected_at(conversation)
    assert connected is not None and conversation.started_at is not None
    assert conversation.ended_at is not None and conversation.caller_number is not None
    return CallRef(
        direction=conversation.direction,
        yaksh_number=conversation.caller_number,
        started_at=conversation.started_at,
        connected_at=connected,
        ended_at=conversation.ended_at,
        trigger_response=conversation.trigger_response,
    )


def stored(row: AgentRecordRow) -> StoredRecord:
    return StoredRecord(
        state=row.state,
        record=None if row.record is None else AgentRecord.model_validate(row.record),
        reason=row.reason,
    )


async def resolve(
    sessionmaker: async_sessionmaker[AsyncSession],
    conversation: Conversation,
    source: RecordSource,
    readers: Mapping[RecordProvider, RecordReader],
    secrets: Secrets,
    *,
    now: datetime,
    wait_s: float,
    poll_s: float,
) -> StoredRecord:
    """The call's stored record; else read it, and store it once it is final or the wait is
    over. Raises NotReady while the provider is still writing it."""
    async with sessionmaker() as session:
        row = await session.get(AgentRecordRow, conversation.id)
    if row is not None:
        return stored(row)
    lookup = await look_up(conversation, source, readers, secrets)
    if isinstance(lookup, Pending):
        assert conversation.ended_at is not None
        deadline = conversation.ended_at + timedelta(seconds=wait_s)
        if now < deadline:
            wait = timedelta(seconds=max(poll_s, lookup.retry_after_s or 0.0))
            raise NotReady(min(now + wait, deadline), lookup.reason)
    found = final(lookup, wait_s)
    async with sessionmaker() as session:
        await session.execute(
            insert(AgentRecordRow)
            .values(
                conversation_id=conversation.id,
                state=found.state,
                provider=source.provider,
                external_id=found.record.external_id if found.record else None,
                record=found.record.model_dump(mode="json") if found.record else None,
                reason=found.reason,
            )
            .on_conflict_do_nothing(index_elements=["conversation_id"])
        )
        await session.commit()
        return stored(await session.get_one(AgentRecordRow, conversation.id))


async def look_up(
    conversation: Conversation,
    source: RecordSource,
    readers: Mapping[RecordProvider, RecordReader],
    secrets: Secrets,
) -> Lookup:
    reader = readers.get(source.provider)
    if reader is None:
        return Missing("Yaksh cannot read records from this provider")
    filler = Filler(
        number=None,
        conversation_id=str(conversation.id),
        agent_data=[],
        secrets={name: value.get_secret_value() for name, value in secrets.triggers.items()},
    )
    try:
        headers = filler.headers(source.headers)
    except RenderError as error:
        return Missing(str(error))
    return await reader.find(source, headers, call_ref(conversation))


def final(lookup: Lookup, wait_s: float) -> StoredRecord:
    """What to keep once there is no more waiting: a record that is not final is kept as it is,
    with why it can be incomplete."""
    match lookup:
        case Found(record):
            return StoredRecord(state=RecordState.FOUND, record=record)
        case Pending(reason, partial) if partial is not None:
            minutes = f"{wait_s / 60:g} min"
            return StoredRecord(
                state=RecordState.FOUND,
                record=partial,
                reason=f"not final {minutes} after the call, so it can miss its end: {reason}",
            )
        case Pending(reason) | Missing(reason):
            return StoredRecord(state=RecordState.MISSING, reason=reason)


def call_clock_ms(conversation: Conversation, at: datetime | None) -> int | None:
    if at is None or conversation.clock_started_at is None:
        return None
    return round((at - conversation.clock_started_at).total_seconds() * 1000)


def paired_turn(line: RecordTurn, at_ms: int | None, turns: list[Turn]) -> int | None:
    """The number of the Yaksh turn a record line belongs to, counted from 1: the turn of the
    same speaker nearest the line's time, within the margin; a turn that holds the time is
    nearest. One turn can hold several lines: speech-to-text splits and joins turns."""
    if at_ms is None:
        return None
    gaps = [
        (max(turn.started_at_ms - at_ms, at_ms - turn.ended_at_ms, 0), number)
        for number, turn in enumerate(turns, 1)
        if turn.role is line.role and turn.machine is None
    ]
    gap, number = min(gaps, default=(None, None))
    return number if gap is not None and gap <= PAIR_MARGIN_MS else None


@dataclass(frozen=True)
class PairedTurn:
    turn: RecordTurn
    at_ms: int | None
    """On the call's clock."""
    started_ms: int | None
    """When its speech started, on the call's clock."""
    number: int | None
    """The Yaksh turn it belongs to, counted from 1."""


@dataclass(frozen=True)
class PlacedTool:
    tool: RecordTool
    at_ms: int | None


@dataclass(frozen=True)
class RecordView:
    status: RecordStatus
    source: RecordSource
    reason: str | None
    row: AgentRecordRow | None
    turns: list[PairedTurn]
    tools: list[PlacedTool]


async def record_view(session: AsyncSession, conversation: Conversation) -> RecordView | None:
    """None when the call has no agent record to read: its pinned agent has no record source,
    or the call is not a judged phone test."""
    version = await session.get_one(AgentVersion, conversation.agent_version_id)
    agent = AgentConfig.model_validate(version.config)
    source = agent.record_source
    if source is None or not applies(conversation, agent):
        return None
    row = await session.get(AgentRecordRow, conversation.id)
    if row is None:
        state = await session.scalar(
            select(Evaluation.state).where(Evaluation.conversation_id == conversation.id)
        )
        if state in (EvaluationState.QUEUED, EvaluationState.RUNNING):
            return RecordView(RecordStatus.WAITING, source, None, None, [], [])
        reason = "the evaluation ended before Yaksh read the record"
        return RecordView(RecordStatus.MISSING, source, reason, None, [], [])
    kept = stored(row)
    status = RecordStatus.FOUND if kept.state is RecordState.FOUND else RecordStatus.MISSING
    if kept.record is None:
        return RecordView(status, source, kept.reason, row, [], [])
    turns = Transcript.model_validate(conversation.transcript or {}).turns
    paired = []
    for line in kept.record.turns:
        at_ms = call_clock_ms(conversation, line.at)
        started_ms = call_clock_ms(conversation, line.started_at)
        paired.append(PairedTurn(line, at_ms, started_ms, paired_turn(line, at_ms, turns)))
    tools = [PlacedTool(tool, call_clock_ms(conversation, tool.at)) for tool in kept.record.tools]
    return RecordView(status, source, kept.reason, row, paired, tools)
