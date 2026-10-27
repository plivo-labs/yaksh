import uuid
from datetime import timedelta

from httpx import AsyncClient
from sqlalchemy import func, update

from tests.conftest import Db, claim, finish, new_run
from yaksh.db.models import Conversation
from yaksh.domain.conversations import (
    CallerSettings,
    CallOutcome,
    EndReason,
    Provenance,
    Role,
    Transcript,
    Turn,
)
from yaksh.domain.latency import CallerReplyTime
from yaksh.integrations.openai_models import caller_effort


def timed(audio_index: int, total_ms: int, llm_ms: int | None = None) -> CallerReplyTime:
    steps = {} if llm_ms is None else {"llm_inference": llm_ms}
    return CallerReplyTime(audio_index=audio_index, total_ms=total_ms, steps=steps)


def outcome(model: str, effort: str | None, *replies: CallerReplyTime) -> CallOutcome:
    return CallOutcome(
        connected=True,
        end_reason=EndReason.AGENT_HANGUP,
        caller_settings=CallerSettings(llm_model=model, reasoning_effort=effort),
        caller_reply_times=list(replies),
    )


async def test_a_caller_turn_gets_the_reply_time_of_the_audio_start_that_played_it(
    client: AsyncClient, db: Db
) -> None:
    await new_run(client)
    conversation = await claim(db)
    assert conversation is not None

    def caller(
        at: int, provenance: Provenance, audio_index: int | None, *, scripted: bool = False
    ) -> Turn:
        return Turn(
            role=Role.CALLER,
            text="Yes.",
            started_at_ms=at,
            ended_at_ms=at + 500,
            provenance=provenance,
            audio_index=audio_index,
            scripted=scripted,
        )

    agent = Turn(role=Role.AGENT, text="Hello?", started_at_ms=0, ended_at_ms=900)
    # Reply 0 was cut off before any word went out; reply 1's words came before its audio; the
    # nudge at audio start 2 is fixed text, not a reply of the caller's model.
    transcript = Transcript(
        turns=[
            agent,
            caller(1_000, Provenance.CUT, None),
            agent,
            caller(2_000, Provenance.TRANSMITTED, 1),
            caller(9_000, Provenance.TRANSMITTED, 2, scripted=True),
        ]
    )
    await finish(
        db,
        conversation,
        outcome("gpt-6-luna", "low", timed(0, 1_500), timed(1, 1_900, 700)),
        transcript=transcript,
    )

    detail = (await client.get(f"/api/v1/conversations/{conversation}")).json()

    assert [turn["caller_reply"] for turn in detail["transcript"]] == [
        None,
        None,
        None,
        {"audio_index": 1, "total_ms": 1_900, "steps": {"llm_inference": 700}},
        None,
    ]


async def test_the_caller_reply_time_by_model_counts_the_replies_of_last_weeks_calls(
    client: AsyncClient, db: Db
) -> None:
    await new_run(client, repeats=6)
    calls = [await claim(db) for _ in range(6)]
    assert all(calls)
    first, second, other, old, text, invalid = (str(call) for call in calls)
    effort = caller_effort("gpt-6-luna", None)
    await finish(db, first, outcome("gpt-6-luna", effort, timed(0, 1_000), timed(1, 3_000)))
    await finish(db, second, outcome("gpt-6-luna", effort, timed(0, 2_000, 800)))
    await finish(db, other, outcome("other-model", "high", timed(0, 4_000, 3_000)))
    await finish(db, old, outcome("other-model", "high", timed(0, 9_000, 9_000)))
    await finish(db, text, CallOutcome(connected=True, end_reason=EndReason.AGENT_HANGUP))
    broken = outcome("gpt-6-luna", effort, timed(0, 8_000)).model_copy(
        update={"caller_error": "the stream dropped"}
    )
    await finish(db, invalid, broken)
    async with db() as session:
        await session.execute(
            update(Conversation)
            .where(Conversation.id == uuid.UUID(old))
            .values(started_at=func.now() - timedelta(days=8))
        )
        await session.commit()

    found = (await client.get("/api/v1/settings/caller-reply-times")).json()

    assert found == {
        "days": 7,
        "rows": [
            {
                "model": "gpt-6-luna",
                "reasoning_effort": effort,
                "calls": 2,
                "replies": 3,
                "p50_ms": 2_000,
                "p90_ms": 3_000,
                "llm_p50_ms": 0,
                "in_use": True,
            },
            {
                "model": "other-model",
                "reasoning_effort": "high",
                "calls": 1,
                "replies": 1,
                "p50_ms": 4_000,
                "p90_ms": 4_000,
                "llm_p50_ms": 3_000,
                "in_use": False,
            },
        ],
    }
