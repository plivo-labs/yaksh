import asyncio
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import (
    Db,
    claim,
    create_agent_id,
    create_scenario,
    finish,
    make_evaluator,
    start_run,
)
from yaksh.config import Settings
from yaksh.db.models import Agent, AgentSpan, AgentTraceOwner, Conversation, Evaluation
from yaksh.domain.conversations import (
    CallOutcome,
    EndReason,
    Transcript,
    WireEvent,
    WireEventKind,
)
from yaksh.domain.latency import Span, Wait
from yaksh.evaluation import agent_traces, trace_store
from yaksh.evaluation.agent_records import NotReady
from yaksh.evaluation.agent_traces import (
    AgentTraces,
    epoch_ns,
    wait_for_traces,
)
from yaksh.evaluation.agent_traces import (
    claim as claim_trace,
)

NUMBER = "+15550100001"
START = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)
CONNECTED = Transcript(wire_events=[WireEvent(kind=WireEventKind.CONNECTED, at_ms=0)])
REPLIES_MS = (5_000, 15_000, 25_000)
"""When the agent starts each reply, on the call's clock: 1.6 s after the caller stops."""
AUDIO_MS = 200
"""How long the agent's audio takes to reach Yaksh's recording."""


@dataclass
class Placed:
    call: Conversation
    heard: list[Span]
    waits: list[Wait]


async def finished_calls(client: AsyncClient, db: Db, count: int) -> list[str]:
    agent = await create_agent_id(client, name=f"Traced {uuid.uuid4()}")
    scenario = await create_scenario(client, agent)
    response = await start_run(client, agent, [scenario["id"]], repeats=count, max_parallel=count)
    assert response.status_code == 202
    ids = [str(await claim(db)) for _ in range(count)]
    for conversation_id in ids:
        outcome = CallOutcome(
            connected=True, end_reason=EndReason.AGENT_HANGUP, clock_started_at=START
        )
        await finish(db, conversation_id, outcome, transcript=CONNECTED)
    return ids


async def place(
    db: Db,
    conversation_id: str,
    start: datetime,
    length_s: float,
    replies: Sequence[int] = REPLIES_MS,
) -> Placed:
    """The call on NUMBER from start, with Yaksh's speech and waits for the replies."""
    async with db() as session:
        await session.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(
                caller_number=NUMBER,
                clock_started_at=start,
                ended_at=start + timedelta(seconds=length_s),
            )
        )
        await session.commit()
        call = await session.get_one(Conversation, conversation_id)
    heard = [Span(start_ms=at + AUDIO_MS, end_ms=at + AUDIO_MS + 2_000) for at in replies]
    waits = [
        Wait(
            start_ms=at + AUDIO_MS - 2_000,
            answer_ms=at + AUDIO_MS,
            until_ms=at + AUDIO_MS,
            expects_answer=True,
        )
        for at in replies
    ]
    return Placed(call, heard, waits)


async def send_trace(
    db: Db,
    start: datetime,
    *,
    number: str | None = NUMBER,
    conversation_id: str | None = None,
    clock_error_s: float = 0.0,
    delay_s: float = 1.0,
    name: str = "agent_turn",
    length_s: float = 40,
    from_s: float = 0,
    replies: Sequence[int] = REPLIES_MS,
) -> str:
    """A LiveKit trace of a call whose clock starts at start, as the agent's clock reads it:
    clock_error_s slow, each span arriving delay_s after it ends on Yaksh's clock. The session
    ends with the call, as LiveKit's does."""
    trace_id = uuid.uuid4().hex
    rows: list[AgentSpan] = []

    def add(
        span: str, start_ms: int, end_ms: int, parent: str | None = None, **attributes: object
    ) -> str:
        span_id = f"{len(rows) + 1:016x}"
        error = round(clock_error_s * 1000)
        rows.append(
            AgentSpan(
                trace_id=trace_id,
                span_id=span_id,
                parent_span_id=parent,
                name=span,
                start_ns=epoch_ns(start) + (start_ms - error) * 1_000_000,
                end_ns=epoch_ns(start) + (end_ms - error) * 1_000_000,
                attributes={key.replace("__", "."): value for key, value in attributes.items()},
                link_conversation_id=uuid.UUID(conversation_id) if conversation_id else None,
                link_number=number,
                received_at=start + timedelta(milliseconds=end_ms) + timedelta(seconds=delay_s),
            )
        )
        return span_id

    add("agent_session", round(from_s * 1000), round(length_s * 1000))
    for index, at in enumerate(replies):
        user = add("user_turn", at - 3_000, at - 1_000, lk__end_of_turn_delay=0.6)
        add("eou_detection", at - 1_100, at - 1_000, user)
        turn = add(name, at - 1_000, at + 2_000, lk__speech_id=f"s{index}", lk__e2e_latency=1.6)
        add("llm_node", at - 990, at - 400, turn, lk__response__ttft=0.4)
        add("tts_node", at - 400, at, turn, lk__response__ttfb=0.3)
        add("agent_speaking", at, at + 2_000, turn)
    async with db() as session:
        session.add_all(rows)
        await session.commit()
    return trace_id


async def metric(db: Db, placed: Placed) -> dict | None:
    found = await AgentTraces(db).metric(placed.call, placed.heard, placed.waits)
    return None if found is None else found.value


async def linked(db: Db, placed: Placed) -> dict:
    value = await metric(db, placed)
    assert value is not None
    return value


async def owner(db: Db, trace_id: str) -> uuid.UUID | None:
    async with db() as session:
        return await session.scalar(
            select(AgentTraceOwner.conversation_id).where(AgentTraceOwner.trace_id == trace_id)
        )


async def mark_linked_before(db: Db, conversation: Conversation) -> None:
    async with db() as session:
        await session.execute(
            update(Agent).where(Agent.id == conversation.agent_id).values(traces_linked_at=START)
        )
        await session.commit()


async def test_a_trace_with_the_calls_id_links_and_splits_each_wait(
    client: AsyncClient, db: Db
) -> None:
    [call_id] = await finished_calls(client, db, 1)
    placed = await place(db, call_id, START, 40)
    trace = await send_trace(db, START, number=None, conversation_id=call_id)

    value = await linked(db, placed)

    assert value["status"] == "ok"
    assert (value["eligible"], value["paired"], value["usable"], value["offset_ms"]) == (
        3,
        3,
        3,
        AUDIO_MS,
    )
    assert value["by_reply"][0]["steps"]["network"] == 400
    assert await owner(db, trace) == uuid.UUID(call_id)


async def test_a_trace_with_the_calls_number_links_when_its_clock_is_right(
    client: AsyncClient, db: Db
) -> None:
    [call_id] = await finished_calls(client, db, 1)
    placed = await place(db, call_id, START, 40)
    trace = await send_trace(db, START)

    value = await linked(db, placed)

    assert value["status"] == "ok" and value["paired"] == 3
    assert await owner(db, trace) == uuid.UUID(call_id)
    async with db() as session:
        assert (await session.get_one(Agent, placed.call.agent_id)).traces_linked_at is not None


async def test_two_calls_on_one_number_each_get_their_own_trace(
    client: AsyncClient, db: Db
) -> None:
    first_id, second_id = await finished_calls(client, db, 2)
    first = await place(db, first_id, START, 30)
    second = await place(db, second_id, START + timedelta(seconds=35), 30)
    first_trace = await send_trace(db, START, length_s=30)
    second_trace = await send_trace(db, START + timedelta(seconds=35), length_s=30)

    assert (await linked(db, second))["status"] == "ok"
    assert (await linked(db, first))["status"] == "ok"
    assert await owner(db, first_trace) == uuid.UUID(first_id)
    assert await owner(db, second_trace) == uuid.UUID(second_id)


@pytest.mark.parametrize(("clock_error_s", "lag_ms"), [(12.0, 13_000), (-5.0, -4_000)])
async def test_a_wrong_clock_links_nothing_and_shows_the_clock_lag(
    client: AsyncClient, db: Db, clock_error_s: float, lag_ms: int
) -> None:
    [call_id] = await finished_calls(client, db, 1)
    placed = await place(db, call_id, START, 40)
    trace = await send_trace(db, START, clock_error_s=clock_error_s)

    assert await metric(db, placed) == {"status": "clock_off", "clock_lag_ms": lag_ms}
    assert await owner(db, trace) is None


async def test_all_spans_3_s_late_with_a_right_clock_still_link(
    client: AsyncClient, db: Db
) -> None:
    [call_id] = await finished_calls(client, db, 1)
    placed = await place(db, call_id, START, 40)
    await send_trace(db, START, delay_s=3.0)

    assert (await linked(db, placed))["status"] == "ok"


async def test_two_traces_at_one_time_that_both_fit_the_call_give_no_trace(
    client: AsyncClient, db: Db
) -> None:
    [call_id] = await finished_calls(client, db, 1)
    placed = await place(db, call_id, START, 40)
    await send_trace(db, START)
    await send_trace(db, START)

    assert await metric(db, placed) is None
    await mark_linked_before(db, placed.call)
    assert await metric(db, placed) == {"status": "no_traces"}


async def test_a_call_in_two_sessions_links_both_traces_by_number(
    client: AsyncClient, db: Db
) -> None:
    """The agent served the call in two sessions, one after the other, each with its own
    trace."""
    [call_id] = await finished_calls(client, db, 1)
    replies = (5_000, 15_000, 25_000, 35_000)
    placed = await place(db, call_id, START, 45, replies)
    first = await send_trace(db, START, length_s=20, replies=replies[:2])
    second = await send_trace(db, START, from_s=21, length_s=45, replies=replies[2:])

    value = await linked(db, placed)
    assert (value["eligible"], value["paired"], value["usable"]) == (4, 4, 4)
    assert (await owner(db, first), await owner(db, second)) == (placed.call.id,) * 2


async def test_a_failure_while_claiming_leaves_no_owner_and_a_retry_links_all(
    client: AsyncClient, db: Db, monkeypatch: pytest.MonkeyPatch
) -> None:
    [call_id] = await finished_calls(client, db, 1)
    replies = (5_000, 15_000, 25_000, 35_000)
    placed = await place(db, call_id, START, 45, replies)
    first = await send_trace(db, START, conversation_id=call_id, length_s=20, replies=replies[:2])
    second = await send_trace(
        db, START, conversation_id=call_id, from_s=21, length_s=45, replies=replies[2:]
    )
    claims = 0

    async def fails_second(
        session: AsyncSession, trace_id: str, conversation_id: uuid.UUID
    ) -> bool:
        nonlocal claims
        claims += 1
        if claims == 2:
            raise ConnectionError("the database went away")
        return await claim_trace(session, trace_id, conversation_id)

    monkeypatch.setattr(agent_traces, "claim", fails_second)
    with pytest.raises(ConnectionError):
        await metric(db, placed)
    assert (await owner(db, first), await owner(db, second)) == (None, None)

    monkeypatch.undo()
    assert (await linked(db, placed))["paired"] == 4


async def test_two_traces_with_the_calls_id_both_link(client: AsyncClient, db: Db) -> None:
    [call_id] = await finished_calls(client, db, 1)
    replies = (5_000, 15_000, 25_000, 35_000)
    placed = await place(db, call_id, START, 45, replies)
    first = await send_trace(db, START, conversation_id=call_id, length_s=20, replies=replies[:2])
    second = await send_trace(
        db, START, conversation_id=call_id, from_s=21, length_s=45, replies=replies[2:]
    )

    value = await linked(db, placed)
    assert (value["paired"], value["usable"]) == (4, 4)
    assert (await owner(db, first), await owner(db, second)) == (placed.call.id,) * 2


async def test_a_session_trace_that_arrives_before_a_retry_links_too(
    client: AsyncClient, db: Db
) -> None:
    """The first try owned the first session's trace; the second session's trace came later."""
    [call_id] = await finished_calls(client, db, 1)
    replies = (5_000, 15_000, 25_000, 35_000)
    placed = await place(db, call_id, START, 45, replies)
    first = await send_trace(db, START, conversation_id=call_id, length_s=20, replies=replies[:2])
    await linked(db, placed)
    assert await owner(db, first) == placed.call.id

    second = await send_trace(
        db, START, conversation_id=call_id, from_s=21, length_s=45, replies=replies[2:]
    )

    assert (await linked(db, placed))["paired"] == 4
    assert (await owner(db, first), await owner(db, second)) == (placed.call.id,) * 2


async def test_a_trace_with_more_speech_starts_than_the_limit_is_not_aligned(
    client: AsyncClient, db: Db, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(agent_traces, "MAX_ANCHORS", len(REPLIES_MS) - 1)
    [call_id] = await finished_calls(client, db, 1)
    placed = await place(db, call_id, START, 40)
    await send_trace(db, START, conversation_id=call_id)

    assert await metric(db, placed) == {"status": "not_aligned"}


async def test_a_trace_that_another_call_owns_does_not_link_again(
    client: AsyncClient, db: Db
) -> None:
    first_id, second_id = await finished_calls(client, db, 2)
    first = await place(db, first_id, START, 40)
    trace = await send_trace(db, START)
    assert (await linked(db, first))["status"] == "ok"
    second = await place(db, second_id, START, 40)

    assert await metric(db, second) == {"status": "no_traces"}
    assert await owner(db, trace) == uuid.UUID(first_id)
    assert (await linked(db, first))["paired"] == 3


async def test_a_trace_that_no_reader_knows_is_linked_with_an_unknown_framework(
    client: AsyncClient, db: Db
) -> None:
    [call_id] = await finished_calls(client, db, 1)
    placed = await place(db, call_id, START, 40)
    await send_trace(db, START, number=None, conversation_id=call_id)
    async with db() as session:
        await session.execute(update(AgentSpan).values(name="their_own_span"))
        await session.commit()

    assert await metric(db, placed) == {"status": "unknown_framework"}


async def test_a_trace_by_id_with_a_clock_90_s_slow_shows_the_clock(
    client: AsyncClient, db: Db
) -> None:
    [call_id] = await finished_calls(client, db, 1)
    placed = await place(db, call_id, START, 40)
    await send_trace(db, START, number=None, conversation_id=call_id, clock_error_s=90)

    assert await metric(db, placed) == {"status": "clock_off", "clock_lag_ms": 91_000}


async def test_an_evaluation_waits_for_traces_only_while_a_trace_token_exists(
    client: AsyncClient, db: Db
) -> None:
    [call_id] = await finished_calls(client, db, 1)
    placed = await place(db, call_id, START, 40)
    ended = START + timedelta(seconds=40)

    await wait_for_traces(db, placed.call, now=ended, wait_s=30)
    async with db() as session:
        await trace_store.make_token(session)
    with pytest.raises(NotReady) as waiting:
        await wait_for_traces(db, placed.call, now=ended + timedelta(seconds=10), wait_s=30)
    assert waiting.value.until == ended + timedelta(seconds=30)
    await wait_for_traces(db, placed.call, now=ended + timedelta(seconds=30), wait_s=30)


async def test_a_slow_clock_that_hides_the_gap_between_two_calls_links_neither(
    client: AsyncClient, db: Db
) -> None:
    """Call A from 0 s to 9 s, call B from 12 s to 21 s on one number, the agent's clock 12 s
    slow: the trace of call B shows its speech in the time of call A."""
    replies = (2_000, 6_000)
    a_id, b_id = await finished_calls(client, db, 2)
    a = await place(db, a_id, START, 9, replies)
    b = await place(db, b_id, START + timedelta(seconds=12), 9, replies)
    trace = await send_trace(
        db, START + timedelta(seconds=12), clock_error_s=12, length_s=9, replies=replies
    )

    assert await metric(db, a) is None
    assert await metric(db, b) == {"status": "clock_off", "clock_lag_ms": 13_000}
    assert await owner(db, trace) is None


async def test_two_calls_that_claim_one_trace_at_once_give_it_one_owner(
    client: AsyncClient, db: Db
) -> None:
    a_id, b_id = await finished_calls(client, db, 2)
    trace = await send_trace(db, START)

    async def claimed(call_id: str) -> bool:
        async with db() as session:
            owned = await claim_trace(session, trace, uuid.UUID(call_id))
            await session.commit()
            return owned

    assert sorted(await asyncio.gather(claimed(a_id), claimed(b_id))) == [False, True]


async def test_two_matching_traces_with_a_wrong_clock_give_no_clock_line(
    client: AsyncClient, db: Db
) -> None:
    [call_id] = await finished_calls(client, db, 1)
    placed = await place(db, call_id, START, 40)
    await send_trace(db, START, clock_error_s=12)
    await send_trace(db, START, clock_error_s=12)

    assert await metric(db, placed) is None


async def test_the_evaluator_deletes_spans_and_links_older_than_7_days(
    client: AsyncClient, db: Db, settings: Settings
) -> None:
    old_call, new_call = await finished_calls(client, db, 2)
    now = datetime.now(UTC)
    old = await send_trace(db, now - timedelta(days=8))
    new = await send_trace(db, now - timedelta(hours=1))
    async with db() as session:
        await session.execute(delete(Evaluation))
        session.add_all(
            [
                AgentTraceOwner(
                    trace_id=old,
                    conversation_id=uuid.UUID(old_call),
                    linked_at=now - timedelta(days=8),
                ),
                AgentTraceOwner(trace_id=new, conversation_id=uuid.UUID(new_call), linked_at=now),
            ]
        )
        await session.commit()

    stop = asyncio.Event()
    run = asyncio.create_task(make_evaluator(db, settings).run(stop))
    for _ in range(100):
        async with db() as session:
            traces = set(await session.scalars(select(AgentSpan.trace_id).distinct()))
            owners = set(await session.scalars(select(AgentTraceOwner.trace_id)))
        if old not in traces:
            break
        await asyncio.sleep(0.1)
    stop.set()
    await run

    assert (traces, owners) == ({new}, {new})
