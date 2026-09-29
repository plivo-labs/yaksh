import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import FakeCaller, create_agent_id, start, wait_for, wait_until
from truman.__main__ import sync_pool
from truman.config import Settings
from truman.db.models import Conversation, PhoneNumber
from truman.db.session import create_engine, create_sessionmaker
from truman.domain.conversations import CallOutcome, ConversationStatus, EndReason, Transcript
from truman.domain.numbers import AccountNumber, PlivoApplication
from truman.integrations.plivo import PlivoApi, PlivoError
from truman.simulation import conversations
from truman.worker.worker import Worker

NUMBER = "+17862242321"
OTHER = "+18005550100"


def account(*numbers: str, voice: bool = True) -> list[AccountNumber]:
    return [AccountNumber(number=number, voice=voice) for number in numbers]


async def enabled_numbers(session: AsyncSession) -> dict[str, bool]:
    rows = await session.execute(select(PhoneNumber.number, PhoneNumber.enabled))
    return {number: enabled for number, enabled in rows.tuples()}


async def queue_phone_conversation(client: AsyncClient) -> uuid.UUID:
    return uuid.UUID((await start(client, await create_agent_id(client)))["id"])


async def test_concurrent_leases_get_distinct_numbers_and_a_finished_call_frees_its_number(
    client: AsyncClient, settings: Settings
) -> None:
    engine = create_engine(settings.database_url.encoded_string())
    sessions = create_sessionmaker(engine)
    first, second, third = [await queue_phone_conversation(client) for _ in range(3)]
    async with sessions() as session:
        await conversations.sync_numbers(session, account(NUMBER, OTHER), [])

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
            60,
        )
        assert recorded
        assert (await session.get_one(Conversation, winner)).caller_number == NUMBER
        rests_until = await session.scalar(
            select(PhoneNumber.available_after).where(PhoneNumber.number == NUMBER)
        )
        assert rests_until is not None and rests_until > datetime.now(UTC) + timedelta(seconds=50)

    assert await lease(third) == NUMBER, "an inbound test uses a resting number as caller id"
    await engine.dispose()


async def test_reaping_a_lost_lease_frees_its_number_and_syncing_keeps_leased_ones(
    client: AsyncClient, settings: Settings
) -> None:
    engine = create_engine(settings.database_url.encoded_string())
    sessions = create_sessionmaker(engine)
    conversation_id = await queue_phone_conversation(client)
    async with sessions() as session:
        await conversations.sync_numbers(session, account(NUMBER, OTHER), [])
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
        await conversations.sync_numbers(session, account("+18005550101"), [])
        pool = set(await session.scalars(select(PhoneNumber.number)))
        assert pool == {NUMBER, "+18005550101"}

        assert await conversations.reap_expired(session, 60) == 1
        free = set(
            await session.scalars(
                select(PhoneNumber.number).where(PhoneNumber.conversation_id.is_(None))
            )
        )
        rests_until = await session.scalar(
            select(PhoneNumber.available_after).where(PhoneNumber.number == NUMBER)
        )
        assert free == {NUMBER, "+18005550101"}
        assert rests_until is not None and rests_until > datetime.now(UTC) + timedelta(seconds=50)
    await engine.dispose()


async def test_phone_conversations_run_from_a_leased_number_and_wait_for_a_free_one(
    client: AsyncClient, worker: Worker, caller: FakeCaller, settings: Settings
) -> None:
    engine = create_engine(settings.database_url.encoded_string())
    async with create_sessionmaker(engine)() as session:
        await conversations.sync_numbers(session, account(NUMBER), [])
    await engine.dispose()
    caller.release.clear()
    first = await queue_phone_conversation(client)
    second = await queue_phone_conversation(client)

    await wait_until(lambda: caller.calls == 1)
    await asyncio.sleep(settings.worker_poll_interval_s * 4)
    running = (await client.get(f"/api/v1/conversations/{first}")).json()
    waiting = (await client.get(f"/api/v1/conversations/{second}")).json()
    caller.release.set()
    done_first = await wait_for(client, str(first), {"completed"})
    done_second = await wait_for(client, str(second), {"completed"})

    assert running["status"] == "running" and running["caller_number"] == NUMBER
    assert waiting["status"] == "queued" and waiting["caller_number"] is None
    assert done_first["caller_number"] == done_second["caller_number"] == NUMBER
    assert caller.calls == 2


async def test_the_allowlist_and_voice_capability_decide_which_numbers_are_leased(
    client: AsyncClient, settings: Settings
) -> None:
    engine = create_engine(settings.database_url.encoded_string())
    sessions = create_sessionmaker(engine)
    first, second = [await queue_phone_conversation(client) for _ in range(2)]
    async with sessions() as session:
        listed = account(NUMBER, OTHER) + account("+18005550102", voice=False)
        await conversations.sync_numbers(session, listed, [OTHER])
        rows = await enabled_numbers(session)
        assert rows == {NUMBER: False, OTHER: True, "+18005550102": False}
        assert await conversations.lease_number(session, first) == OTHER
        assert await conversations.lease_number(session, second) is None

        await conversations.sync_numbers(session, listed, [])
        rows = await enabled_numbers(session)
        assert rows == {NUMBER: True, OTHER: True, "+18005550102": False}
        assert await conversations.lease_number(session, second) == NUMBER

        with pytest.raises(conversations.UnknownNumbersError, match=r"\+15550009999"):
            await conversations.sync_numbers(session, listed, ["+15550009999"])
    await engine.dispose()


class Listing(PlivoApi):
    """A Plivo client whose account lists exactly these numbers and applications, or cannot be
    reached."""

    def __init__(
        self,
        numbers: list[AccountNumber] | PlivoError,
        applications: dict[str, PlivoApplication] | None = None,
    ) -> None:
        super().__init__("MAXXXX", "token")
        self.numbers = numbers
        self.applications = applications or {}

    async def list_numbers(self) -> list[AccountNumber]:
        if isinstance(self.numbers, PlivoError):
            raise self.numbers
        return self.numbers

    async def get_application(self, app_id: str) -> PlivoApplication:
        if app_id not in self.applications:
            raise PlivoError(f"reading application {app_id} failed with 404")
        return self.applications[app_id]


async def test_an_empty_listing_or_an_unreachable_plivo_keeps_the_last_synced_pool(
    client: AsyncClient, settings: Settings
) -> None:
    engine = create_engine(settings.database_url.encoded_string())
    sessions = create_sessionmaker(engine)
    await sync_pool(sessions, Listing(account(NUMBER)), [])
    await sync_pool(sessions, Listing([]), [])
    await sync_pool(sessions, Listing(PlivoError("plivo is down")), [])
    async with sessions() as session:
        assert await enabled_numbers(session) == {NUMBER: True}
    await engine.dispose()


async def test_the_pool_records_which_application_each_usable_number_is_linked_to(
    client: AsyncClient, settings: Settings
) -> None:
    truman = PlivoApplication(
        app_id="11",
        name="truman",
        answer_url="https://truman.example/incoming",
        answer_method="POST",
        hangup_url="https://truman.example/incoming/hangup",
        hangup_method="POST",
    )
    listed = [
        AccountNumber(number=NUMBER, application_id="11"),
        AccountNumber(number=OTHER, application_id="99"),
    ]
    engine = create_engine(settings.database_url.encoded_string())
    await sync_pool(create_sessionmaker(engine), Listing(listed, {"11": truman}), [])
    async with create_sessionmaker(engine)() as session:
        rows = await session.execute(
            select(PhoneNumber.number, PhoneNumber.application_id, PhoneNumber.application_name)
        )
        links = {number: (app_id, name) for number, app_id, name in rows.tuples()}
    await engine.dispose()

    assert links == {NUMBER: ("11", "truman"), OTHER: ("99", None)}
