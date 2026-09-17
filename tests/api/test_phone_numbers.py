import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import select, update

from tests.api.test_conversations import create_agent, start
from truman.config import Settings
from truman.db.models import Conversation, PhoneNumber
from truman.db.session import create_engine, create_sessionmaker
from truman.domain.conversations import CallOutcome, ConversationStatus, EndReason, Transcript
from truman.simulation import conversations

NUMBER = "+17862242321"
OTHER = "+18005550100"


async def queue_phone_conversation(client: AsyncClient) -> uuid.UUID:
    agent_id = await create_agent(
        client, transport="phone", websocket_url=None, agent_number="+14155550100"
    )
    return uuid.UUID((await start(client, agent_id))["id"])


async def test_concurrent_leases_get_distinct_numbers_and_a_finished_call_frees_its_number(
    client: AsyncClient, settings: Settings
) -> None:
    engine = create_engine(settings.database_url.encoded_string())
    sessions = create_sessionmaker(engine)
    first, second, third = [await queue_phone_conversation(client) for _ in range(3)]
    async with sessions() as session:
        await conversations.sync_numbers(session, [NUMBER, OTHER])

    async def lease(conversation_id: uuid.UUID) -> str | None:
        async with sessions() as session:
            return await conversations.lease_number(session, conversation_id)

    leased = await asyncio.gather(lease(first), lease(second))
    assert sorted(leased, key=str) == [NUMBER, OTHER]
    assert await lease(third) is None
    winner = first if leased[0] == NUMBER else second

    async with sessions() as session:
        await session.execute(
            update(Conversation)
            .where(Conversation.id == winner)
            .values(
                status=ConversationStatus.RUNNING,
                claimed_by="w1",
                lease_expires_at=datetime.now(UTC) + timedelta(seconds=30),
            )
        )
        await session.commit()
        recorded = await conversations.finalize(
            session,
            winner,
            "w1",
            CallOutcome(connected=True, end_reason=EndReason.AGENT_HANGUP),
            Transcript(),
            1000,
        )
        assert recorded
        assert (await session.get_one(Conversation, winner)).caller_number == NUMBER

    assert await lease(third) == NUMBER
    await engine.dispose()


async def test_reaping_a_lost_lease_frees_its_number_and_syncing_keeps_leased_ones(
    client: AsyncClient, settings: Settings
) -> None:
    engine = create_engine(settings.database_url.encoded_string())
    sessions = create_sessionmaker(engine)
    conversation_id = await queue_phone_conversation(client)
    async with sessions() as session:
        await conversations.sync_numbers(session, [NUMBER, OTHER])
        assert await conversations.lease_number(session, conversation_id) == NUMBER
        await session.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(
                status=ConversationStatus.RUNNING,
                claimed_by="gone",
                lease_expires_at=datetime.now(UTC) - timedelta(seconds=1),
            )
        )
        await session.commit()
        await conversations.sync_numbers(session, ["+18005550101"])
        pool = set(await session.scalars(select(PhoneNumber.number)))
        assert pool == {NUMBER, "+18005550101"}

        assert await conversations.reap_expired(session) == 1
        free = set(
            await session.scalars(
                select(PhoneNumber.number).where(PhoneNumber.conversation_id.is_(None))
            )
        )
        assert free == {NUMBER, "+18005550101"}
    await engine.dispose()
