import asyncio
import contextlib
from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from testcontainers.community.postgres import PostgresContainer

from truman.api import create_app
from truman.config import Settings
from truman.db.migrate import upgrade_to_head
from truman.db.session import create_engine, create_sessionmaker
from truman.domain.conversations import (
    CallObserver,
    CallOutcome,
    CallRequest,
    EndReason,
    Provenance,
    Role,
    Turn,
    WireEvent,
    WireEventKind,
)
from truman.worker.worker import Worker

TOKEN = "test-token"
OFFLINE_DATABASE_URL = "postgresql+asyncpg://truman:truman@localhost:5432/truman"


def make_settings(tmp_path: Path, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "api_token": TOKEN,
        "database_url": OFFLINE_DATABASE_URL,
        "data_dir": tmp_path / "data",
        "frontend_dist": tmp_path / "missing",
        "worker_poll_interval_s": 0.05,
        "worker_heartbeat_s": 0.05,
        "worker_lease_s": 2,
        "end_timeout_s": 0.5,
    }
    return Settings.model_validate({**values, **overrides})


async def first(*events: asyncio.Event) -> asyncio.Event:
    waiters = {asyncio.ensure_future(event.wait()): event for event in events}
    done, pending = await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)
    for waiter in pending:
        waiter.cancel()
    return waiters[next(iter(done))]


class Observer:
    def __init__(self) -> None:
        self.events: list[WireEvent] = []
        self.turns: list[Turn] = []

    def turn(self, turn: Turn) -> None:
        self.turns.append(turn)

    def wire_event(self, event: WireEvent) -> None:
        self.events.append(event)

    def kinds(self) -> list[WireEventKind]:
        return [event.kind for event in self.events]


class FakeCaller:
    """A caller the tests steer: gates for connecting and finishing, and failure modes."""

    def __init__(self) -> None:
        self.calls = 0
        self.mode = "normal"
        self.connect_gate = asyncio.Event()
        self.connect_gate.set()
        self.release = asyncio.Event()
        self.release.set()
        self.recording_path: Path | None = None

    async def run(
        self, request: CallRequest, observer: CallObserver, stop: asyncio.Event
    ) -> CallOutcome:
        self.calls += 1
        observer.wire_event(WireEvent(kind=WireEventKind.CONNECT_STARTED, at_ms=0))
        if await first(stop, self.connect_gate) is stop:
            return CallOutcome(connected=False, end_reason=EndReason.USER_REQUEST)
        if self.mode == "refuse":
            return CallOutcome(
                connected=False, end_reason=EndReason.ERROR, caller_error="connection refused"
            )
        observer.wire_event(WireEvent(kind=WireEventKind.CONNECTED, at_ms=1))
        observer.turn(
            Turn(role=Role.AGENT, text="Hello, how can I help?", started_at_ms=2, ended_at_ms=3)
        )
        if self.mode == "raise_after_connect":
            raise RuntimeError("tts exploded")
        if self.mode == "ignore_stop":
            await asyncio.sleep(3600)
        if self.mode == "immortal":
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.sleep(3600)
            await asyncio.sleep(3600)
        if await first(stop, self.release) is stop:
            return CallOutcome(
                connected=True,
                end_reason=EndReason.USER_REQUEST,
                recording_path=self.recording_path,
            )
        observer.turn(
            Turn(
                role=Role.CALLER,
                text=request.persona_prompt,
                started_at_ms=4,
                ended_at_ms=5,
                provenance=Provenance.TRANSMITTED,
            )
        )
        observer.wire_event(WireEvent(kind=WireEventKind.STOP, at_ms=6))
        return CallOutcome(
            connected=True,
            end_reason=EndReason.AGENT_HANGUP,
            recording_path=self.recording_path,
            call_uuid="call-42",
        )


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    with PostgresContainer("postgres:17-alpine", driver="asyncpg") as postgres:
        url = postgres.get_connection_url()
        upgrade_to_head(url)
        yield url


@pytest.fixture
def settings_factory(tmp_path: Path) -> Callable[..., Settings]:
    return lambda **overrides: make_settings(tmp_path, **overrides)


@pytest.fixture
def offline_settings(tmp_path: Path) -> Settings:
    return make_settings(tmp_path)


@pytest.fixture
def settings(database_url: str, tmp_path: Path) -> Settings:
    return make_settings(tmp_path, database_url=database_url)


@pytest.fixture
async def client(settings: Settings) -> AsyncIterator[AsyncClient]:
    app = create_app(settings)
    transport = ASGITransport(app=app)
    headers = {"Authorization": f"Bearer {TOKEN}"}
    async with AsyncClient(transport=transport, base_url="http://test", headers=headers) as client:
        yield client
    await app.state.engine.dispose()
    engine = create_async_engine(settings.database_url.encoded_string())
    async with engine.begin() as connection:
        await connection.execute(
            text("TRUNCATE phone_numbers, conversations, agent_versions, agents")
        )
    await engine.dispose()


@pytest.fixture
def caller() -> FakeCaller:
    return FakeCaller()


@pytest.fixture
async def worker(
    client: AsyncClient, settings: Settings, caller: FakeCaller
) -> AsyncIterator[Worker]:
    engine = create_engine(settings.database_url.encoded_string())
    worker = Worker(create_sessionmaker(engine), caller, settings, worker_id="test-worker")
    stop = asyncio.Event()
    task = asyncio.create_task(worker.run(stop))
    yield worker
    stop.set()
    await task
    await engine.dispose()
