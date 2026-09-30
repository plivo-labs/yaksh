import asyncio
import uuid
from collections.abc import AsyncGenerator, AsyncIterator, Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from testcontainers.community.postgres import PostgresContainer

from truman.api import create_app
from truman.config import Settings
from truman.db.migrate import upgrade_to_head
from truman.db.models import Voice
from truman.db.session import create_engine, create_sessionmaker
from truman.domain.conversations import (
    Admission,
    CallerClaim,
    CallObserver,
    CallOutcome,
    CallRequest,
    EndReason,
    IncomingCall,
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
from truman.integrations.plivo_signature import signature, signed_text
from truman.simulation import conversations
from truman.worker.worker import Worker

TOKEN = "test-token"
PLIVO_TOKEN = "token"
POOL = [AccountNumber(number=f"+1555010{n:04d}") for n in range(8)]
OFFLINE_DATABASE_URL = "postgresql+asyncpg://truman:truman@localhost:5432/truman"


AGENT = {"name": "Front desk", "agent_number": "+14155550100"}
OUTBOUND_AGENT: dict[str, Any] = {
    "name": "Payment reminders",
    "direction": "outbound",
    "agent_number": None,
    "outbound": {
        "trigger": {
            "url": "https://agents.example.com/calls",
            "headers": [{"name": "Authorization", "value": "Bearer {{env.TRUMAN_TRIGGER_KEY}}"}],
            "body": {
                "to": "{{truman.number}}",
                "customer": {"name": "{{agent_data.Customer name}}"},
                "tags": ["truman", "{{truman.conversation_id}}"],
            },
        },
        "calling_numbers": ["+14155550100"],
    },
}
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
    "caller_language": Language.EN,
    "voice": VoiceSettings(provider=VoiceProvider.ELEVENLABS, id=ENGLISH_VOICE.id),
}
PERSONA = {
    "name": "Rushed caller",
    "prompt": "You are in a hurry.",
    "voice": {"provider": "elevenlabs", "id": ENGLISH_VOICE.id},
}
SCENARIO: dict[str, Any] = {
    "name": "Reschedule a cleaning",
    "goal": "Move your cleaning to an evening next week; if none is free, keep the current one.",
    "known_facts": [
        {"name": "Name", "value": "Priya Raman"},
        {"name": "Current appointment", "value": "next Thursday, 10:30 am"},
    ],
    "unknown_facts": ["Patient ID"],
    "criteria": ["Reads the new date and time back before it moves the appointment."],
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


async def create_scenario(client: AsyncClient, agent_id: str, **overrides: Any) -> dict[str, Any]:
    if "persona_id" not in overrides:
        overrides["persona_id"] = (await create_persona(client, name=f"Caller {uuid.uuid4()}"))[
            "id"
        ]
    response = await client.post(
        f"/api/v1/agents/{agent_id}/scenarios", json={**SCENARIO, **overrides}
    )
    assert response.status_code == 201, response.text
    return response.json()


async def start(client: AsyncClient, agent_id: str, **overrides: Any) -> dict[str, Any]:
    if "persona_id" not in overrides:
        overrides["persona_id"] = (await create_persona(client, name=f"Caller {uuid.uuid4()}"))[
            "id"
        ]
    if "scenario_id" not in overrides:
        overrides["scenario_id"] = (
            await create_scenario(
                client,
                agent_id,
                name=f"Scenario {uuid.uuid4()}",
                persona_id=overrides["persona_id"],
            )
        )["id"]
    body = {"agent_id": agent_id, **overrides}
    response = await client.post("/api/v1/conversations", json=body)
    assert response.status_code == 202, response.text
    return response.json()


async def start_run(
    client: AsyncClient,
    agent_id: str,
    scenario_ids: list[str],
    *,
    key: str | None = None,
    **fields: Any,
) -> Response:
    return await client.post(
        "/api/v1/runs",
        json={"agent_id": agent_id, "scenario_ids": scenario_ids, **fields},
        headers={} if key is None else {"Idempotency-Key": key},
    )


async def run_conversations(
    client: AsyncClient, run_id: str, **params: Any
) -> list[dict[str, Any]]:
    """The run's conversations in queue order."""
    response = await client.get(
        "/api/v1/conversations",
        params={"run_id": run_id, "sort": "created_at", "page_size": 100, **params},
    )
    assert response.status_code == 200, response.text
    return response.json()["items"]


async def new_run(client: AsyncClient, *, scenarios: int = 1, **fields: Any) -> dict[str, Any]:
    """A run of a new agent's new scenarios."""
    agent = await create_agent_id(client, name=f"Agent {uuid.uuid4()}")
    ids = [
        (await create_scenario(client, agent, name=f"Scenario {n}"))["id"] for n in range(scenarios)
    ]
    response = await start_run(client, agent, ids, **fields)
    assert response.status_code == 202, response.text
    return response.json()


async def claim(settings: Settings, worker_id: str = "w1") -> str | None:
    """The id of the conversation a worker claims next, if any."""
    engine = create_engine(settings.database_url.encoded_string())
    async with create_sessionmaker(engine)() as session:
        claimed = await conversations.claim_next(session, worker_id, 30, None)
    await engine.dispose()
    return None if claimed is None else str(claimed.id)


async def reap(settings: Settings, rest_s: int = 0) -> int:
    engine = create_engine(settings.database_url.encoded_string())
    async with create_sessionmaker(engine)() as session:
        reaped = await conversations.reap_expired(session, rest_s)
    await engine.dispose()
    return reaped


async def wait_for_run(
    client: AsyncClient, run_id: str, status: str, timeout: float = 10.0
) -> dict[str, Any]:
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        run = (await client.get(f"/api/v1/runs/{run_id}")).json()
        if run["status"] == status:
            return run
        assert asyncio.get_running_loop().time() < deadline, run
        await asyncio.sleep(0.05)


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


async def wait_for_lock_waiters(settings: Settings, count: int, timeout: float = 5.0) -> None:
    """Wait until `count` database sessions wait on a lock, so a test releases a lock it holds
    only after every request it races has reached that lock."""
    engine = create_async_engine(
        settings.database_url.encoded_string(), isolation_level="AUTOCOMMIT"
    )
    deadline = asyncio.get_running_loop().time() + timeout
    try:
        async with engine.connect() as connection:
            while True:
                waiting = await connection.scalar(
                    text(
                        "SELECT count(*) FROM pg_stat_activity"
                        " WHERE datname = current_database() AND wait_event_type = 'Lock'"
                    )
                )
                if waiting is not None and waiting >= count:
                    return
                assert asyncio.get_running_loop().time() < deadline, f"{waiting} of {count} wait"
                await asyncio.sleep(0.02)
    finally:
        await engine.dispose()


async def wait_until(condition: Callable[[], bool], timeout: float = 5.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not condition():
        assert asyncio.get_running_loop().time() < deadline
        await asyncio.sleep(0.02)


async def refuse_calls(call: IncomingCall) -> Admission | str:
    return "no conversation expects a call"


def plivo_signed(
    url: str, fields: dict[str, str] | None = None, *, method: str = "POST"
) -> dict[str, str]:
    """Headers Plivo would send with a request to url, signed with the test account token."""
    nonce = "nonce-1"
    text = signed_text(method, url, {key: [value] for key, value in (fields or {}).items()})
    return {
        "X-Plivo-Signature-V3-Nonce": nonce,
        "X-Plivo-Signature-V3": signature(PLIVO_TOKEN, text, nonce),
    }


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
        if self.mode == "no_answer":
            return CallOutcome(connected=False, end_reason=EndReason.NO_ANSWER)
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


class FakeJsonModel:
    """Answers the scenario generator: the plan it is given, and for each scenario what
    `write` makes of the writer's prompt."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.capabilities: list[dict[str, Any]] = []
        self.questions: dict[str, Any] = {"answered": [], "unanswered": []}
        self.write: Callable[[str], dict[str, Any]] = written_scenario
        self.down = False

    async def complete_json(
        self, *, system: str, user: str, name: str, schema: dict[str, Any]
    ) -> dict[str, Any]:
        self.calls.append((name, user))
        if self.down:
            raise UnavailableError("the model call failed: timed out")
        if name == "capabilities":
            return {"capabilities": self.capabilities}
        if name == "questions":
            return self.questions
        return self.write(user)

    async def close(self) -> None:
        pass


def written_scenario(prompt: str) -> dict[str, Any]:
    """A valid scenario named after what the writer was asked to test."""
    subject = next(
        (
            line.split(":", 1)[1].split(":")[0].strip().strip('"')
            for line in prompt.splitlines()
            if line.startswith(("Area:", "The caller asks:"))
        ),
        "Out of scope",
    )
    return {
        "name": subject[:60],
        "description": f"Tests {subject}.",
        "goal": "Get the request done, then end the call.",
        "known_facts": [{"name": "Name", "value": "Priya Raman"}],
        "unknown_facts": [],
        "criteria": ["The agent confirms the name Priya Raman."],
        "agent_data": [],
    }


class FakeFileStore:
    def __init__(self) -> None:
        self.files: dict[str, tuple[bytes, str]] = {}
        self.puts = 0
        self.down = False

    async def put(self, key: str, data: bytes, media_type: str) -> None:
        if self.down:
            raise UnavailableError("file storage refused the upload")
        self.puts += 1
        self.files[key] = (data, media_type)

    async def stream(self, key: str) -> AsyncGenerator[bytes]:
        if self.down or key not in self.files:
            raise UnavailableError("file storage could not return the file")
        data = self.files[key][0]
        for start in range(0, len(data), 1000):
            yield data[start : start + 1000]


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
def file_store() -> FakeFileStore:
    return FakeFileStore()


@pytest.fixture
def generation_model() -> FakeJsonModel:
    return FakeJsonModel()


@pytest.fixture
async def client(
    settings: Settings,
    voice_clients: dict[VoiceProvider, FakeVoiceClient],
    file_store: FakeFileStore,
    generation_model: FakeJsonModel,
) -> AsyncIterator[AsyncClient]:
    """An API client whose voices list holds the English and the Hindi test voice."""
    app = create_app(settings)
    app.state.voice_clients = voice_clients
    app.state.file_store = file_store
    app.state.generation_model = generation_model
    async with create_sessionmaker(app.state.engine)() as session:
        await conversations.sync_numbers(session, POOL, [], {})
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
                "TRUNCATE phone_numbers, conversations, runs, agent_versions, agents,"
                " persona_versions, personas, voices, scenario_versions, scenarios, workers,"
                " documents, scenario_generations"
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
