import asyncio
import random
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import insert, select, update

from tests.conftest import OUTBOUND_AGENT, create_agent, create_scenario
from yaksha.config import Settings
from yaksha.db.models import Conversation, PhoneNumber, RefusedCall, Run
from yaksha.db.session import create_engine, create_sessionmaker
from yaksha.domain.conversations import (
    Admission,
    CallOutcome,
    ConversationStatus,
    EndReason,
    IncomingCall,
    Transcript,
)
from yaksha.domain.languages import Language
from yaksha.simulation import conversations

AGENT_NUMBER = "+14155550100"


async def first_version_id(client: AsyncClient, path: str) -> uuid.UUID:
    return uuid.UUID((await client.get(f"{path}/versions")).json()["items"][0]["id"])


async def waiting_conversation(
    client: AsyncClient,
    settings: Settings,
    *,
    calling_numbers: list[str] | None = None,
    deadline_in_s: int = 60,
) -> tuple[uuid.UUID, str]:
    """An outbound conversation claimed by worker w1, waiting for a call on a leased number."""
    outbound = {**OUTBOUND_AGENT["outbound"], "calling_numbers": calling_numbers or []}
    agent = await create_agent(client, **{**OUTBOUND_AGENT, "outbound": outbound})
    scenario = await create_scenario(client, agent["id"])
    agent_version_id = await first_version_id(client, f"/api/v1/agents/{agent['id']}")
    number = f"+1555{random.randrange(10**7):07d}"
    now = datetime.now(UTC)
    engine = create_engine(settings.database_url.encoded_string())
    async with engine.begin() as connection:
        run_id = await connection.scalar(
            insert(Run)
            .values(
                agent_id=uuid.UUID(agent["id"]),
                agent_version_id=agent_version_id,
                repeats=1,
                max_duration_s=120,
                max_turns=20,
                max_retries=0,
            )
            .returning(Run.id)
        )
        conversation_id = await connection.scalar(
            insert(Conversation)
            .values(
                agent_id=uuid.UUID(agent["id"]),
                agent_version_id=agent_version_id,
                run_id=run_id,
                repeat=1,
                persona_id=uuid.UUID(scenario["persona_id"]),
                persona_version_id=await first_version_id(
                    client, f"/api/v1/personas/{scenario['persona_id']}"
                ),
                scenario_id=uuid.UUID(scenario["id"]),
                scenario_version_id=await first_version_id(
                    client, f"/api/v1/scenarios/{scenario['id']}"
                ),
                language=Language.EN,
                instructions="You answer the phone.",
                nudge="Hello?",
                today=date(2026, 10, 5),
                time_zone="UTC",
                max_duration_s=120,
                max_turns=20,
                surroundings={},
                sound_plan={},
                status=ConversationStatus.RUNNING,
                claimed_by="w1",
                lease_expires_at=now + timedelta(seconds=60),
                dial_deadline_at=now + timedelta(seconds=deadline_in_s),
            )
            .returning(Conversation.id)
        )
        await connection.execute(
            insert(PhoneNumber).values(number=number, conversation_id=conversation_id)
        )
    await engine.dispose()
    assert conversation_id is not None
    return conversation_id, number


async def accept(settings: Settings, call: IncomingCall, worker_id: str = "w1") -> Admission | str:
    engine = create_engine(settings.database_url.encoded_string())
    async with create_sessionmaker(engine)() as session:
        verdict = await conversations.accept_incoming_call(session, worker_id, call)
    await engine.dispose()
    return verdict


def call(number: str, call_uuid: str = "call-1", from_number: str = AGENT_NUMBER) -> IncomingCall:
    return IncomingCall(to_number=number, from_number=from_number, call_uuid=call_uuid)


async def test_a_waiting_conversation_takes_one_call_and_plivo_may_retry_it(
    client: AsyncClient, settings: Settings
) -> None:
    conversation_id, number = await waiting_conversation(client, settings)

    first = await accept(settings, call(number))
    retry = await accept(settings, call(number))
    second = await accept(settings, call(number, "call-2"))

    admitted = Admission(conversation_id=conversation_id, max_duration_s=120)
    assert first == retry == admitted
    assert second == "the conversation already has a call"


@pytest.mark.parametrize(
    ("change", "refusal"),
    [
        ({"call_uuid": "call-a"}, "the conversation already has a call"),
        ({"status": ConversationStatus.ENDING}, "the conversation is not running on this worker"),
    ],
    ids=["another call won", "cancelled"],
)
async def test_a_call_waits_for_a_concurrent_change_and_then_sees_it(
    client: AsyncClient, settings: Settings, change: dict[str, object], refusal: str
) -> None:
    conversation_id, number = await waiting_conversation(client, settings)
    engine = create_engine(settings.database_url.encoded_string())
    async with create_sessionmaker(engine)() as holder:
        await holder.execute(
            select(Conversation).where(Conversation.id == conversation_id).with_for_update()
        )
        waiting = asyncio.create_task(accept(settings, call(number, "call-b")))
        await asyncio.sleep(0.3)
        assert not waiting.done(), "the second transaction waits for the row lock"
        await holder.execute(
            update(Conversation).where(Conversation.id == conversation_id).values(**change)
        )
        await holder.commit()
    await engine.dispose()

    assert await waiting == refusal


async def test_after_the_dial_window_only_a_retry_of_the_accepted_call_gets_in(
    client: AsyncClient, settings: Settings
) -> None:
    closed_id, closed = await waiting_conversation(client, settings, deadline_in_s=-1)
    retried_id, retried = await waiting_conversation(client, settings)
    assert isinstance(await accept(settings, call(retried)), Admission)
    engine = create_engine(settings.database_url.encoded_string())
    async with engine.begin() as connection:
        await connection.execute(
            update(Conversation)
            .where(Conversation.id == retried_id)
            .values(dial_deadline_at=datetime.now(UTC) - timedelta(seconds=1))
        )
    await engine.dispose()

    assert await accept(settings, call(closed)) == "the dial window has closed"
    assert await accept(settings, call(retried)) == Admission(
        conversation_id=retried_id, max_duration_s=120
    )
    assert closed_id != retried_id


async def test_only_the_agents_calling_numbers_may_call(
    client: AsyncClient, settings: Settings
) -> None:
    _, number = await waiting_conversation(client, settings, calling_numbers=[AGENT_NUMBER])

    stranger = await accept(settings, call(number, from_number="+19998887777"))
    agent = await accept(settings, call(number))

    assert stranger == "+19998887777 is not one of the agent's calling numbers"
    assert isinstance(agent, Admission)


async def test_calls_that_no_waiting_conversation_owns_are_refused(
    client: AsyncClient, settings: Settings
) -> None:
    ending_id, ending = await waiting_conversation(client, settings)
    _, elsewhere = await waiting_conversation(client, settings)
    engine = create_engine(settings.database_url.encoded_string())
    async with engine.begin() as connection:
        await connection.execute(
            update(Conversation)
            .where(Conversation.id == ending_id)
            .values(status=ConversationStatus.ENDING)
        )
    await engine.dispose()

    assert await accept(settings, call("+15550000000")) == "no conversation holds this number"
    assert await accept(settings, call(ending)) == "the conversation is not running on this worker"
    assert (
        await accept(settings, call(elsewhere), worker_id="w2")
        == "the conversation is not running on this worker"
    )


async def test_each_refused_call_is_kept_once_with_its_reason(
    client: AsyncClient, settings: Settings
) -> None:
    conversation_id, number = await waiting_conversation(client, settings)

    assert await accept(settings, call("+15550000000", "call-x")) == (
        "no conversation holds this number"
    )
    await accept(settings, call("+15550000000", "call-x"))
    assert await accept(settings, call(number, "call-y"), worker_id="w2") == (
        "the conversation is not running on this worker"
    )
    assert isinstance(await accept(settings, call(number, "call-z")), Admission)

    engine = create_engine(settings.database_url.encoded_string())
    async with create_sessionmaker(engine)() as session:
        refused = (await session.scalars(select(RefusedCall).order_by(RefusedCall.id))).all()
    await engine.dispose()

    assert [(r.call_uuid, r.to_number, r.reason, r.conversation_id) for r in refused] == [
        ("call-x", "+15550000000", "no conversation holds this number", None),
        ("call-y", number, "the conversation is not running on this worker", conversation_id),
    ]


async def test_a_call_the_worker_never_took_leaves_no_caller_on_the_conversation(
    client: AsyncClient, settings: Settings
) -> None:
    conversation_id, number = await waiting_conversation(client, settings)
    assert isinstance(await accept(settings, call(number)), Admission)
    engine = create_engine(settings.database_url.encoded_string())
    async with create_sessionmaker(engine)() as session:
        await conversations.finalize(
            session,
            conversation_id,
            "w1",
            CallOutcome(connected=False, end_reason=EndReason.NO_CALL),
            Transcript(),
            number_rest_s=0,
        )
        finished = await session.get_one(Conversation, conversation_id)
    await engine.dispose()

    assert (finished.call_uuid, finished.agent_caller_id) == (None, None)
