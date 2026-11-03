from httpx import AsyncClient

from tests.conftest import Db, claim, evaluate_queued, finish, new_run
from yaksh.domain.conversations import (
    CallOutcome,
    EndReason,
    Provenance,
    Role,
    Transcript,
    Turn,
    WireEvent,
    WireEventKind,
)
from yaksh.domain.evaluations import MetricKey
from yaksh.domain.stops import LineStop, StopResult
from yaksh.evaluation import metrics


def line(number: int, at: int, text: str, provenance: Provenance) -> Turn:
    return Turn(
        role=Role.CALLER,
        text=text,
        started_at_ms=at,
        ended_at_ms=at + 400,
        provenance=provenance,
        scripted=True,
        interruption=number,
    )


async def test_the_first_turn_of_each_line_gets_its_stop(client: AsyncClient, db: Db) -> None:
    await new_run(client)
    conversation = await claim(db)
    assert conversation is not None
    agent = Turn(role=Role.AGENT, text="Your booking is", started_at_ms=0, ended_at_ms=9_000)
    # Line 1 went out only in part: its words are two turns.
    transcript = Transcript(
        turns=[
            agent,
            line(1, 2_000, "Sorry,", Provenance.TRANSMITTED),
            line(1, 2_400, "can you repeat that?", Provenance.CUT),
            agent,
            line(2, 12_000, "Wait.", Provenance.TRANSMITTED),
        ],
        wire_events=[WireEvent(kind=WireEventKind.CONNECTED, at_ms=0)],
    )
    connected = CallOutcome(connected=True, end_reason=EndReason.AGENT_HANGUP, stream_opened_ms=0)
    await finish(db, conversation, connected, transcript=transcript)
    first = LineStop(number=1, line_ms=2_150, result=StopResult.STOPPED, stop_ms=788)
    second = LineStop(number=2, line_ms=12_100, result=StopResult.KEPT_TALKING, stop_ms=9_662)
    await evaluate_queued(
        db, {conversation: {MetricKey.STOP_TIME: metrics.stop_time([first, second])}}
    )

    detail = (await client.get(f"/api/v1/conversations/{conversation}")).json()

    assert [turn["agent_stop"] for turn in detail["transcript"]] == [
        None,
        first.model_dump(mode="json"),
        None,
        None,
        second.model_dump(mode="json"),
    ]
