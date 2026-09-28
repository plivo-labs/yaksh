import asyncio
import contextlib
import uuid
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
from truman.db.models import Voice
from truman.db.session import create_engine, create_sessionmaker
from truman.domain.conversations import (
    CallerClaim,
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
from truman.domain.errors import UnavailableError
from truman.domain.languages import Language
from truman.domain.numbers import AccountNumber
from truman.domain.voices import ProviderVoice, VoiceGender, VoiceProvider, VoiceSettings
from truman.simulation import conversations
from truman.worker.worker import Worker

TOKEN = "test-token"
POOL = [AccountNumber(number=f"+1555010{n:04d}") for n in range(8)]
OFFLINE_DATABASE_URL = "postgresql+asyncpg://truman:truman@localhost:5432/truman"


AGENT = {"name": "Front desk", "agent_number": "+14155550100"}
ENGLISH_VOICE = ProviderVoice(
    id="voice-en",
    name="Chris",
    gender=VoiceGender.MALE,
    accent="american",
    listed_languages=(Language.EN,),
)
HINDI_VOICE = ProviderVoice(
    id="voice-hi",
    name="Ananya",
    gender=VoiceGender.FEMALE,
    accent="indian",
    listed_languages=(Language.EN, Language.HINGLISH),
)
UNLISTED_VOICE = ProviderVoice(
    id="voice-new", name="Riya", gender=VoiceGender.FEMALE, accent="indian"
)
"""On the provider account but not in the voices list until a test adds it."""
CALLER = {
    "instructions": "You want to book a room.",
    "nudge": "Hello? Are you still there?",
    "language": Language.EN,
    "voice": VoiceSettings(provider=VoiceProvider.ELEVENLABS, id=ENGLISH_VOICE.id),
}
PERSONA = {
    "name": "Rushed caller",
    "prompt": "You are in a hurry.",
    "voice": {"provider": "elevenlabs", "id": ENGLISH_VOICE.id},
}


async def create_agent(client: AsyncClient, **overrides: Any) -> dict[str, Any]:
    response = await client.post("/api/v1/agents", json={**AGENT, **overrides})
    assert response.status_code == 201, response.text
    return response.json()


async def create_agent_id(client: AsyncClient, **overrides: Any) -> str:
    return (await create_agent(client, **overrides))["id"]


async def listed_voice_id(client: AsyncClient, provider_voice_id: str) -> str:
    voices = (await client.get("/api/v1/voices")).json()["items"]
    return next(v["id"] for v in voices if v["provider_voice_id"] == provider_voice_id)


async def create_persona(client: AsyncClient, **overrides: Any) -> dict[str, Any]:
    response = await client.post("/api/v1/personas", json={**PERSONA, **overrides})
    assert response.status_code == 201, response.text
    return response.json()


async def start(client: AsyncClient, agent_id: str, **overrides: Any) -> dict[str, Any]:
    if "persona_id" not in overrides:
        overrides["persona_id"] = (await create_persona(client, name=f"Caller {uuid.uuid4()}"))[
            "id"
        ]
    body = {"agent_id": agent_id, "goal": "I want to book a room", **overrides}
    response = await client.post("/api/v1/conversations", json=body)
    assert response.status_code == 202, response.text
    return response.json()


async def wait_for(
    client: AsyncClient, conversation_id: str, statuses: set[str], timeout: float = 5.0
) -> dict[str, Any]:
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        conversation = (await client.get(f"/api/v1/conversations/{conversation_id}")).json()
        if conversation["status"] in statuses:
            return conversation
        assert asyncio.get_running_loop().time() < deadline, conversation
        await asyncio.sleep(0.05)


async def wait_until(condition: Callable[[], bool], timeout: float = 5.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not condition():
        assert asyncio.get_running_loop().time() < deadline
        await asyncio.sleep(0.02)


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
        "plivo_auth_id": "MAXXXX",
        "plivo_auth_token": "token",
        "public_url": "http://truman.test",
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
                text="I want to book a room",
                started_at_ms=4,
                ended_at_ms=5,
                provenance=Provenance.TRANSMITTED,
            )
        )
        observer.wire_event(WireEvent(kind=WireEventKind.STOP, at_ms=6))
        if self.mode == "caller_hangs_up":
            return CallOutcome(
                connected=True,
                end_reason=EndReason.CALLER_HANGUP,
                caller_claim=CallerClaim(success=True, reason="the room is booked"),
            )
        return CallOutcome(
            connected=True,
            end_reason=EndReason.AGENT_HANGUP,
            recording_path=self.recording_path,
            call_uuid="call-42",
        )


class FakeVoiceClient:
    """Voices of one provider account; `down` makes every call fail as if the provider
    were unreachable."""

    def __init__(self) -> None:
        self.voices = {voice.id: voice for voice in (ENGLISH_VOICE, HINDI_VOICE, UNLISTED_VOICE)}
        self.lookups: list[str] = []
        self.spoken: list[tuple[VoiceSettings, Language, str]] = []
        self.down = False

    async def get_voice(self, voice_id: str) -> ProviderVoice | None:
        self._answer()
        self.lookups.append(voice_id)
        return self.voices.get(voice_id)

    async def speak(self, voice: VoiceSettings, language: Language, text: str) -> bytes | None:
        self._answer()
        self.spoken.append((voice, language, text))
        return b"RIFF fake wav" if voice.id in self.voices else None

    def _answer(self) -> None:
        if self.down:
            raise UnavailableError("the voice provider did not answer")


def listed_voice(voice: ProviderVoice, *languages: Language) -> Voice:
    return Voice(
        provider=VoiceProvider.ELEVENLABS,
        provider_voice_id=voice.id,
        name=voice.name,
        gender=voice.gender,
        accent=voice.accent,
        languages=list(languages),
        listed_languages=list(voice.listed_languages),
        builtin=False,
    )


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    with PostgresContainer("postgres:18-alpine", driver="asyncpg") as postgres:
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
def voice_client() -> FakeVoiceClient:
    return FakeVoiceClient()


@pytest.fixture
def voice_clients(voice_client: FakeVoiceClient) -> dict[VoiceProvider, FakeVoiceClient]:
    return {VoiceProvider.ELEVENLABS: voice_client}


@pytest.fixture
async def client(
    settings: Settings, voice_clients: dict[VoiceProvider, FakeVoiceClient]
) -> AsyncIterator[AsyncClient]:
    """An API client whose voices list holds the English and the Hindi test voice."""
    app = create_app(settings)
    app.state.voice_clients = voice_clients
    async with create_sessionmaker(app.state.engine)() as session:
        await conversations.sync_numbers(session, POOL, [])
        session.add(listed_voice(ENGLISH_VOICE, Language.EN))
        session.add(listed_voice(HINDI_VOICE, Language.EN, Language.HINGLISH))
        await session.commit()
    transport = ASGITransport(app=app)
    headers = {"Authorization": f"Bearer {TOKEN}"}
    async with AsyncClient(transport=transport, base_url="http://test", headers=headers) as client:
        yield client
    await app.state.engine.dispose()
    engine = create_async_engine(settings.database_url.encoded_string())
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "TRUNCATE phone_numbers, conversations, agent_versions, agents,"
                " persona_versions, personas, voices, scenario_versions, scenarios"
            )
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
