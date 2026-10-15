import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import select, update

from tests.conftest import (
    FAST,
    POOL_APP_ID,
    FakeCaller,
    FakePlivoAccount,
    FakeProviders,
    create_agent_id,
    start,
    start_run,
    wait_for,
    wait_until,
)
from yaksh.config import Settings
from yaksh.db.models import Conversation, PhoneCheck, PhoneNumber
from yaksh.db.session import create_engine, create_sessionmaker
from yaksh.domain.conversations import (
    CallOutcome,
    ConversationStatus,
    EndReason,
    StoredAudio,
    Transcript,
)
from yaksh.domain.numbers import AccountNumber, PlivoApplication
from yaksh.simulation import conversations, numbers, phone_account
from yaksh.simulation.workers import report_worker
from yaksh.worker.worker import Worker

NUMBER = "+17862242321"
OTHER = "+18005550100"
FREE = "+18005550101"
CX = PlivoApplication(
    app_id="77",
    name="agent_flow_18005550102",
    answer_url="https://agentflow.example/answer",
    answer_method="POST",
    hangup_url="https://agentflow.example/hangup",
    hangup_method="POST",
)


def account(
    *numbers: str, app_id: str | None = POOL_APP_ID, voice: bool = True
) -> list[AccountNumber]:
    return [AccountNumber(number=number, application_id=app_id, voice=voice) for number in numbers]


async def queue_phone_conversation(client: AsyncClient) -> uuid.UUID:
    return uuid.UUID((await start(client, await create_agent_id(client)))["id"])


async def test_concurrent_leases_get_distinct_numbers_and_a_finished_call_frees_its_number(
    client: AsyncClient, settings: Settings
) -> None:
    engine = create_engine(settings.database_url.encoded_string())
    sessions = create_sessionmaker(engine)
    first, second, third = [await queue_phone_conversation(client) for _ in range(3)]
    async with sessions() as session:
        await numbers.sync_numbers(session, account(NUMBER, OTHER), {})

    async def lease(conversation_id: uuid.UUID) -> str | None:
        async with sessions() as session:
            return await numbers.lease_number(session, conversation_id, POOL_APP_ID)

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
            StoredAudio(),
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


async def test_reaping_a_lost_lease_frees_its_number_and_a_check_keeps_leased_ones(
    client: AsyncClient, settings: Settings
) -> None:
    engine = create_engine(settings.database_url.encoded_string())
    sessions = create_sessionmaker(engine)
    conversation_id = await queue_phone_conversation(client)
    async with sessions() as session:
        await numbers.sync_numbers(session, account(NUMBER, OTHER), {})
        assert await numbers.lease_number(session, conversation_id, POOL_APP_ID) == NUMBER
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
        await numbers.sync_numbers(session, account(FREE), {})
        stored = set(await session.scalars(select(PhoneNumber.number)))
        assert stored == {NUMBER, FREE}

        assert await conversations.reap_expired(session, 60) == 1
        free = set(
            await session.scalars(
                select(PhoneNumber.number).where(PhoneNumber.conversation_id.is_(None))
            )
        )
        rests_until = await session.scalar(
            select(PhoneNumber.available_after).where(PhoneNumber.number == NUMBER)
        )
        assert free == {NUMBER, FREE}
        assert rests_until is not None and rests_until > datetime.now(UTC) + timedelta(seconds=50)
    await engine.dispose()


async def test_phone_conversations_run_from_a_leased_number_and_wait_for_a_free_one(
    client: AsyncClient, worker: Worker, caller: FakeCaller, settings: Settings
) -> None:
    engine = create_engine(settings.database_url.encoded_string())
    async with create_sessionmaker(engine)() as session:
        await numbers.sync_numbers(session, account(NUMBER), {})
    await engine.dispose()
    caller.release.clear()
    first = await queue_phone_conversation(client)
    second = await queue_phone_conversation(client)

    await wait_until(lambda: caller.calls == 1)
    await asyncio.sleep(FAST.worker_poll_s * 4)
    running = (await client.get(f"/api/v1/conversations/{first}")).json()
    waiting = (await client.get(f"/api/v1/conversations/{second}")).json()
    caller.release.set()
    done_first = await wait_for(client, str(first), {"completed"})
    done_second = await wait_for(client, str(second), {"completed"})

    assert running["status"] == "running" and running["caller_number"] == NUMBER
    assert waiting["status"] == "queued" and waiting["caller_number"] is None
    assert done_first["caller_number"] == done_second["caller_number"] == NUMBER
    assert caller.calls == 2


async def test_only_numbers_of_the_receiving_application_that_take_calls_are_leased(
    client: AsyncClient, settings: Settings
) -> None:
    engine = create_engine(settings.database_url.encoded_string())
    sessions = create_sessionmaker(engine)
    first, second = [await queue_phone_conversation(client) for _ in range(2)]
    async with sessions() as session:
        listed = (
            account(NUMBER, app_id="99")
            + account(FREE, app_id=None)
            + account("+18005550102", voice=False)
            + account(OTHER)
        )
        await numbers.sync_numbers(session, listed, {})
        assert await numbers.lease_number(session, first, POOL_APP_ID) == OTHER
        assert await numbers.lease_number(session, second, POOL_APP_ID) is None
    await engine.dispose()


async def test_a_run_without_test_numbers_is_refused_with_what_to_do(
    client: AsyncClient, settings: Settings
) -> None:
    engine = create_engine(settings.database_url.encoded_string())
    async with create_sessionmaker(engine)() as session:
        await numbers.sync_numbers(session, account(NUMBER, app_id=None), {})
    await engine.dispose()

    refused = await start_run(client, await create_agent_id(client), [str(uuid.uuid4())])

    assert refused.status_code == 422
    assert refused.json()["error"]["message"] == (
        "phone calls are off: choose test numbers on the Numbers page"
    )


async def test_a_check_keeps_the_stored_numbers_when_plivo_lists_none_or_cannot_be_reached(
    client: AsyncClient, settings: Settings
) -> None:
    engine = create_engine(settings.database_url.encoded_string())
    sessions = create_sessionmaker(engine)
    async with sessions() as session:
        assert await phone_account.check_numbers(session, FakePlivoAccount(account(NUMBER))) is None
        empty = await phone_account.check_numbers(session, FakePlivoAccount([]))
        down = FakePlivoAccount(account(OTHER))
        down.down = True
        unreachable = await phone_account.check_numbers(session, down)
        stored = set(await session.scalars(select(PhoneNumber.number)))
        checked_at, error = await phone_account.last_check(session)
    await engine.dispose()

    assert stored == {NUMBER}
    assert empty == "the Plivo account lists no numbers"
    assert unreachable == error == "Plivo is down"
    assert checked_at is not None


async def test_one_process_checks_at_a_time_and_only_when_the_interval_has_passed(
    client: AsyncClient, settings: Settings
) -> None:
    engine = create_engine(settings.database_url.encoded_string())
    sessions = create_sessionmaker(engine)
    async with sessions() as session:
        first = await phone_account.claim_check(session, 300)
        second = await phone_account.claim_check(session, 300)
        await phone_account.check_numbers(session, FakePlivoAccount())
        after_check = await phone_account.claim_check(session, 300)
        await session.execute(
            update(PhoneCheck).values(checked_at=datetime.now(UTC) - timedelta(seconds=301))
        )
        await session.commit()
        stale = await phone_account.claim_check(session, 300)
    await engine.dispose()

    assert (first, second, after_check, stale) == (True, False, False, True)


async def lease_one(settings: Settings, conversation_id: uuid.UUID) -> str | None:
    engine = create_engine(settings.database_url.encoded_string())
    async with create_sessionmaker(engine)() as session:
        number = await numbers.lease_number(session, conversation_id, POOL_APP_ID)
    await engine.dispose()
    return number


async def test_the_numbers_page_lists_every_number_with_its_owner_and_a_test_numbers_state(
    client: AsyncClient, settings: Settings, providers: FakeProviders
) -> None:
    providers.account = FakePlivoAccount(
        account(NUMBER)
        + account(FREE, app_id=None)
        + account("+18005550102", app_id=CX.app_id)
        + account(OTHER, app_id="99")
        + account("+18005550103", app_id=None, voice=False),
        applications=[*FakePlivoAccount().applications.values(), CX],
    )
    await client.post("/api/v1/phone-numbers/check")
    assert await lease_one(settings, await queue_phone_conversation(client)) == NUMBER

    listed = (await client.get("/api/v1/phone-numbers")).json()

    owners = {item["number"]: (item["owner"], item["state"]) for item in listed["items"]}
    assert owners == {
        NUMBER: ("test", "in_use"),
        FREE: ("free", None),
        "+18005550102": ("cx_agent", None),
        OTHER: ("other", None),
        "+18005550103": ("no_voice", None),
    }
    assert listed["application_id"] == POOL_APP_ID
    assert listed["checked_at"] is not None and listed["check_error"] is None
    assert listed["problem"] is None


async def test_a_free_number_becomes_a_test_number_and_another_applications_number_is_not_taken(
    client: AsyncClient, providers: FakeProviders
) -> None:
    providers.account = FakePlivoAccount(account(FREE, app_id=None) + account(OTHER, app_id="99"))
    await client.post("/api/v1/phone-numbers/check")

    used = await client.post(f"/api/v1/phone-numbers/{FREE}/use")
    taken = await client.post(f"/api/v1/phone-numbers/{OTHER}/use")

    assert used.status_code == 200
    assert {item["number"]: item["owner"] for item in used.json()["items"]}[FREE] == "test"
    assert taken.status_code == 409
    assert providers.account.links == [(FREE, POOL_APP_ID)]
    assert providers.account.numbers[OTHER].application_id == "99"


async def test_a_test_number_stops_only_when_no_test_holds_it_and_it_is_not_resting(
    client: AsyncClient, settings: Settings, providers: FakeProviders
) -> None:
    providers.account = FakePlivoAccount(account(NUMBER, OTHER))
    await client.post("/api/v1/phone-numbers/check")
    held = await lease_one(settings, await queue_phone_conversation(client))
    free = OTHER if held == NUMBER else NUMBER
    engine = create_engine(settings.database_url.encoded_string())
    async with create_sessionmaker(engine)() as session:
        await session.execute(
            update(PhoneNumber)
            .where(PhoneNumber.number == free)
            .values(available_after=datetime.now(UTC) + timedelta(seconds=60))
        )
        await session.commit()
    await engine.dispose()

    in_test = await client.post(f"/api/v1/phone-numbers/{held}/stop")
    resting = await client.post(f"/api/v1/phone-numbers/{free}/stop")
    engine = create_engine(settings.database_url.encoded_string())
    async with create_sessionmaker(engine)() as session:
        await session.execute(update(PhoneNumber).values(available_after=None))
        await session.commit()
    await engine.dispose()
    stopped = await client.post(f"/api/v1/phone-numbers/{free}/stop")

    assert (in_test.status_code, resting.status_code, stopped.status_code) == (409, 409, 200)
    assert in_test.json()["error"]["message"] == f"{held} is in a test"
    assert resting.json()["error"]["message"] == f"{free} rests after a test"
    assert {item["number"]: item["owner"] for item in stopped.json()["items"]}[free] == "free"
    assert providers.account.links == [(free, None)]


async def test_a_number_another_install_took_since_the_last_check_is_not_taken(
    client: AsyncClient, providers: FakeProviders
) -> None:
    providers.account = FakePlivoAccount(account(FREE, app_id=None))
    await client.post("/api/v1/phone-numbers/check")
    await providers.account.link_number(FREE, "99")
    providers.account.links.clear()

    taken = await client.post(f"/api/v1/phone-numbers/{FREE}/use")
    listed = (await client.get("/api/v1/phone-numbers")).json()

    assert taken.status_code == 409
    assert providers.account.links == []
    assert [(item["number"], item["owner"]) for item in listed["items"]] == [(FREE, "other")]


async def test_a_stop_without_plivos_answer_takes_the_number_out_of_the_pool(
    client: AsyncClient, providers: FakeProviders
) -> None:
    providers.account = FakePlivoAccount(account(NUMBER, OTHER))
    await client.post("/api/v1/phone-numbers/check")
    await providers.account.link_number(OTHER, "99")
    providers.account.links_fail = True

    moved = await client.post(f"/api/v1/phone-numbers/{OTHER}/stop")
    unanswered = await client.post(f"/api/v1/phone-numbers/{NUMBER}/stop")
    listed = (await client.get("/api/v1/phone-numbers")).json()

    assert moved.status_code == 409
    assert moved.json()["error"]["message"] == (
        f"{OTHER} is no longer linked to the receiving application"
    )
    assert unanswered.status_code == 503
    owners = {item["number"]: item["owner"] for item in listed["items"]}
    assert owners == {NUMBER: "free", OTHER: "other"}


class Overtaken(FakePlivoAccount):
    """A Plivo account whose first listing comes back after Yaksh changed a number: by then
    what it lists is out of date."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(account(NUMBER))
        self.settings = settings
        self.listings = 0

    async def list_numbers(self) -> list[AccountNumber]:
        self.listings += 1
        stale = await super().list_numbers()
        if self.listings == 1:
            engine = create_engine(self.settings.database_url.encoded_string())
            async with create_sessionmaker(engine)() as session:
                row = await phone_account.locked_number(session, NUMBER)
                await phone_account.changed(session, row, None)
            await engine.dispose()
            self.numbers[NUMBER] = self.numbers[NUMBER].model_copy(update={"application_id": None})
        return stale


async def test_a_check_that_a_change_overtook_reads_again_and_stores_the_change(
    client: AsyncClient, settings: Settings
) -> None:
    engine = create_engine(settings.database_url.encoded_string())
    sessions = create_sessionmaker(engine)
    async with sessions() as session:
        await numbers.sync_numbers(session, account(NUMBER), {})
        plivo = Overtaken(settings)
        await phone_account.check_numbers(session, plivo)
        linked = await session.scalar(
            select(PhoneNumber.application_id).where(PhoneNumber.number == NUMBER)
        )
    await engine.dispose()

    assert plivo.listings == 2
    assert linked is None, "the stale listing would have linked the number again"


async def test_a_number_gone_from_the_account_leaves_the_pool_but_keeps_its_test(
    client: AsyncClient, settings: Settings
) -> None:
    engine = create_engine(settings.database_url.encoded_string())
    sessions = create_sessionmaker(engine)
    conversation_id = await queue_phone_conversation(client)
    async with sessions() as session:
        await numbers.sync_numbers(session, account(NUMBER), {})
        assert await numbers.lease_number(session, conversation_id, POOL_APP_ID) == NUMBER
        await numbers.sync_numbers(session, account(OTHER), {})
        held = await session.scalar(
            select(PhoneNumber.conversation_id).where(PhoneNumber.number == NUMBER)
        )
        await numbers.release_numbers(session, [conversation_id], 0)
        await session.commit()
        first, second = [await queue_phone_conversation(client) for _ in range(2)]
        leased = [
            await numbers.lease_number(session, first, POOL_APP_ID),
            await numbers.lease_number(session, second, POOL_APP_ID),
        ]
    await engine.dispose()

    assert held == conversation_id, "the check keeps the running test's lease"
    assert leased == [OTHER, None], "the gone number is not leased again after its test"


async def test_an_inbound_run_is_refused_while_the_running_workers_cannot_use_the_application(
    client: AsyncClient, settings: Settings
) -> None:
    agent_id = await create_agent_id(client)
    engine = create_engine(settings.database_url.encoded_string())
    async with create_sessionmaker(engine)() as session:
        await report_worker(
            session,
            "w1",
            receiving_app_id=None,
            outbound_problem="Plivo application Yaksh-Test has answer URL 'x'; set it to 'y'",
            lease_s=FAST.worker_lease_s,
        )
    await engine.dispose()

    refused = await start_run(client, agent_id, [str(uuid.uuid4())])

    assert refused.status_code == 422
    assert refused.json()["error"]["message"] == (
        "phone calls are off: Plivo application Yaksh-Test has answer URL 'x'; set it to 'y'"
    )
