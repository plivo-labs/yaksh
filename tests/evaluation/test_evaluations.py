import asyncio
import uuid
import wave
from pathlib import Path

from httpx import AsyncClient
from sqlalchemy import func, select, update

from tests.conftest import Db, claim, eventually, expire_leases, finish, new_run, reap
from yaksha.config import Settings
from yaksha.db.models import Conversation, Evaluation, MetricValue
from yaksha.domain.conversations import CallOutcome, EndReason, Transcript, WireEvent, WireEventKind
from yaksha.domain.evaluations import EvaluationState, Metric, MetricKey
from yaksha.domain.latency import CallerReplyWindow
from yaksha.evaluation import evaluations
from yaksha.evaluation.evaluations import MAX_ATTEMPTS, Evaluated
from yaksha.worker.evaluator import Evaluator

HUNG_UP = CallOutcome(connected=True, end_reason=EndReason.AGENT_HANGUP)
RATE = 8000


async def saved_call(client: AsyncClient, db: Db, outcome: CallOutcome = HUNG_UP) -> str:
    await new_run(client)
    conversation_id = await claim(db)
    assert conversation_id is not None
    connected = [WireEvent(kind=WireEventKind.CONNECTED, at_ms=0)] if outcome.connected else []
    assert await finish(db, conversation_id, outcome, transcript=Transcript(wire_events=connected))
    return conversation_id


async def queued(db: Db) -> list[Evaluation]:
    async with db() as session:
        return list(await session.scalars(select(Evaluation)))


async def stored(db: Db, evaluation_id: uuid.UUID) -> dict[str, Metric]:
    async with db() as session:
        rows = await session.scalars(
            select(MetricValue).where(MetricValue.evaluation_id == evaluation_id)
        )
        return {row.metric_key: Metric(value=row.value, flags=row.flags) for row in rows}


async def end_lease(db: Db, evaluation_id: uuid.UUID) -> None:
    async with db.begin() as session:
        await session.execute(
            update(Evaluation)
            .where(Evaluation.id == evaluation_id)
            .values(lease_expires_at=func.now(), not_before=func.now())
        )


async def test_a_saved_call_is_queued_once_and_a_cancelled_one_not_at_all(
    client: AsyncClient, db: Db
) -> None:
    conversation_id = await saved_call(client, db)
    async with db.begin() as session:
        await evaluations.enqueue(session, [uuid.UUID(conversation_id)])
    await saved_call(client, db, CallOutcome(connected=False, end_reason=EndReason.USER_REQUEST))

    assert [str(e.conversation_id) for e in await queued(db)] == [conversation_id]


async def test_queueing_keeps_working_on_one_connection(client: AsyncClient, db: Db) -> None:
    conversation_id = uuid.UUID(await saved_call(client, db))
    async with db() as session:
        for _ in range(8):
            await evaluations.enqueue(session, [conversation_id])
        await session.commit()

    assert len(await queued(db)) == 1


async def test_a_call_whose_worker_stopped_is_evaluated_too(client: AsyncClient, db: Db) -> None:
    await new_run(client)
    conversation_id = await claim(db)
    await expire_leases(db, Conversation.id == conversation_id)

    assert await reap(db) == 1
    assert [str(e.conversation_id) for e in await queued(db)] == [conversation_id]


async def test_a_late_write_from_an_earlier_claim_changes_nothing(
    client: AsyncClient, db: Db
) -> None:
    await saved_call(client, db)
    async with db() as session:
        first = await evaluations.claim(session, "e1", 60)
        assert first is not None
        assert await evaluations.claim(session, "e2", 60) is None
    await end_lease(db, first.id)
    async with db() as session:
        second = await evaluations.claim(session, "e2", 60)
    assert second is not None and second.id == first.id

    async with db() as session:
        assert not await evaluations.renew(session, first.id, first.claim_seq, 60)
        assert not await evaluations.finish(
            session,
            first.id,
            first.claim_seq,
            Evaluated(metrics={MetricKey.SPEECH: Metric(value={})}),
            audit=False,
        )
        assert await evaluations.finish(
            session,
            second.id,
            second.claim_seq,
            Evaluated(metrics={MetricKey.RESPONSE_TIME: Metric(value={"n": 1})}),
            audit=False,
        )

    assert await stored(db, first.id) == {MetricKey.RESPONSE_TIME: Metric(value={"n": 1})}
    [done] = await queued(db)
    assert (done.state, done.attempts) == (EvaluationState.DONE, 2)


async def test_a_failed_evaluation_waits_then_ends_failed_after_its_last_attempt(
    client: AsyncClient, db: Db
) -> None:
    await saved_call(client, db)
    waiting = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        async with db() as session:
            claimed = await evaluations.claim(session, "e1", 60)
            assert claimed is not None and claimed.attempts == attempt
            await evaluations.fail(session, claimed.id, claimed.claim_seq, attempt, "boom")
            assert await evaluations.claim(session, "e1", 60) is None
        [waiting] = await queued(db)
        if attempt < MAX_ATTEMPTS:
            assert waiting.state is EvaluationState.QUEUED and waiting.not_before is not None
            await end_lease(db, waiting.id)

    assert waiting is not None
    assert (waiting.state, waiting.failure, waiting.ended_at is not None) == (
        EvaluationState.FAILED,
        "boom",
        True,
    )


async def test_an_evaluation_that_stops_its_evaluator_every_time_ends_failed(
    client: AsyncClient, db: Db
) -> None:
    await saved_call(client, db)
    for _ in range(MAX_ATTEMPTS):
        async with db() as session:
            assert await evaluations.claim(session, "e1", 60) is not None
        [running] = await queued(db)
        await end_lease(db, running.id)

    async with db() as session:
        assert await evaluations.claim(session, "e2", 60) is None
    [ended] = await queued(db)
    assert (ended.state, ended.attempts, ended.lease_expires_at) == (
        EvaluationState.FAILED,
        MAX_ATTEMPTS,
        None,
    )


def write_wav(path: Path, channels: int, seconds: float) -> None:
    with wave.open(str(path), "wb") as file:
        file.setnchannels(channels)
        file.setsampwidth(2)
        file.setframerate(RATE)
        file.writeframes(bytes(2 * channels * round(RATE * seconds)))


async def run_evaluator(db: Db, settings: Settings) -> Evaluation:
    """Run an evaluator until the one queued evaluation is done or has failed once."""
    stop = asyncio.Event()
    evaluator = asyncio.create_task(Evaluator(db, settings).run(stop))
    try:
        [evaluation] = await eventually(
            lambda: queued(db),
            lambda found: found[0].state is EvaluationState.DONE or found[0].failure is not None,
        )
    finally:
        stop.set()
        await evaluator
    return evaluation


async def test_the_evaluator_measures_a_saved_call_from_its_files(
    client: AsyncClient, db: Db, settings: Settings, tmp_path: Path
) -> None:
    recording, voice = tmp_path / "recording.wav", tmp_path / "caller-voice.wav"
    write_wav(recording, 2, 3)
    write_wav(voice, 1, 0.5)
    reply = CallerReplyWindow(
        start_ms=1000, end_ms=1500, finished=True, audio_start_ms=0, audio_ms=500
    )
    outcome = HUNG_UP.model_copy(
        update={
            "recording_path": recording,
            "caller_voice_path": voice,
            "recording_start_ms": 0,
            "stream_opened_ms": 0,
            "caller_replies": [reply],
        }
    )
    await saved_call(client, db, outcome)

    evaluation = await run_evaluator(db, settings)

    assert evaluation.state is EvaluationState.DONE
    found = await stored(db, evaluation.id)
    assert set(found) == set(MetricKey)
    assert found[MetricKey.SPEECH] == Metric(value={"agent": [], "caller": []})
    assert found[MetricKey.RESPONSE_TIME] == Metric(
        value={"replies": [], "p50_ms": None, "p90_ms": None}
    )
    # Silent audio: the agent answered neither the start of the call nor the caller's reply,
    # which waited until the recording ended.
    assert (
        found[MetricKey.TURN_TAKING].value["longest_wait_ms"],
        found[MetricKey.TURN_TAKING].flags,
    ) == (1_500, ["unanswered"])


async def test_an_evaluation_that_cannot_read_its_files_is_tried_again_later(
    client: AsyncClient, db: Db, settings: Settings, tmp_path: Path
) -> None:
    outcome = HUNG_UP.model_copy(
        update={
            "recording_path": tmp_path / "missing.wav",
            "recording_start_ms": 0,
            "stream_opened_ms": 0,
            "caller_replies": [],
        }
    )
    await saved_call(client, db, outcome)

    evaluation = await run_evaluator(db, settings)

    assert (evaluation.state, evaluation.attempts, evaluation.claimed_by) == (
        EvaluationState.QUEUED,
        1,
        None,
    )
    assert evaluation.not_before is not None and "missing.wav" in (evaluation.failure or "")
    assert await stored(db, evaluation.id) == {}
