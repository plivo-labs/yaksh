import asyncio
import uuid
from array import array
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable, Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient, Response
from pydantic import SecretStr
from sqlalchemy import ColumnElement, func, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.community.postgres import PostgresContainer

from yaksh.api import create_app
from yaksh.caller.audio import Clock
from yaksh.caller.plivo_server import PlivoServer
from yaksh.config import Settings
from yaksh.db.migrate import upgrade_to_head
from yaksh.db.models import Conversation, Voice
from yaksh.db.session import create_engine, create_sessionmaker
from yaksh.domain.agent_import import ElevenLabsRegion, VapiRegion
from yaksh.domain.conversations import (
    Admission,
    CallObserver,
    CallOutcome,
    CallRequest,
    EndReason,
    IncomingCall,
    Provenance,
    Role,
    StoredAudio,
    Transcript,
    Turn,
    WireEvent,
    WireEventKind,
)
from yaksh.domain.errors import UnavailableError
from yaksh.domain.evaluations import Metric, MetricKey
from yaksh.domain.files import FileStore
from yaksh.domain.language_models import ModelAnswer, ModelCallError
from yaksh.domain.languages import Language
from yaksh.domain.numbers import AccountNumber, PlivoApplication
from yaksh.domain.settings import AppSettings, Phone, SecretName, Secrets
from yaksh.domain.voices import ProviderVoice, VoiceGender, VoiceProvider, VoiceSettings
from yaksh.evaluation import evaluations
from yaksh.evaluation.evaluations import Evaluated
from yaksh.integrations.elevenlabs import ElevenLabsAgentsApi, as_wav
from yaksh.integrations.plivo import PlivoApi, PlivoError
from yaksh.integrations.plivo_signature import signature, signed_text
from yaksh.integrations.retell import RetellApi
from yaksh.integrations.vapi import VapiApi
from yaksh.settings import store
from yaksh.settings.cipher import Cipher
from yaksh.settings.store import SettingsSource
from yaksh.simulation import conversations, numbers
from yaksh.timings import Timings
from yaksh.worker.evaluator import Evaluator, JudgeClients
from yaksh.worker.phone_account import PhoneAccount
from yaksh.worker.worker import Worker

type Db = async_sessionmaker[AsyncSession]

TOKEN = "test-token"
PLIVO_AUTH_ID = "MAXXXX"
PLIVO_TOKEN = "token"
ENCRYPTION_KEY = "test-encryption-key-of-at-least-32-chars"
STORED_SECRETS: dict[str, str | None] = {
    SecretName.PLIVO_AUTH_ID: PLIVO_AUTH_ID,
    SecretName.PLIVO_AUTH_TOKEN: PLIVO_TOKEN,
    SecretName.LLM_API_KEY: "llm-test-key",
    SecretName.DEEPGRAM_API_KEY: "deepgram-test-key",
    SecretName.ELEVENLABS_API_KEY: "elevenlabs-test-key",
}
"""The secrets every API test starts with, so runs can start."""
FAST = Timings(worker_poll_s=0.05, worker_heartbeat_s=0.05, worker_lease_s=2, end_timeout_s=0.5)
"""Worker timings fast enough for tests."""
POOL_APP_ID = "10000000000000001"
"""The receiving application of the tests: the pool numbers are linked to it."""
APP_SETTINGS = AppSettings(
    phone=Phone(application_id=POOL_APP_ID),
    secrets=Secrets(
        plivo_auth_id=SecretStr(PLIVO_AUTH_ID),
        plivo_auth_token=SecretStr(PLIVO_TOKEN),
        llm_api_key=SecretStr("llm-test-key"),
        deepgram_api_key=SecretStr("deepgram-test-key"),
        elevenlabs_api_key=SecretStr("elevenlabs-test-key"),
    ),
)
"""Stored settings for a call request built without the database."""
POOL = [AccountNumber(number=f"+1555010{n:04d}", application_id=POOL_APP_ID) for n in range(8)]
OFFLINE_DATABASE_URL = "postgresql+asyncpg://yaksh:yaksh@localhost:5432/yaksh"
FINAL = {"completed", "failed", "invalid", "cancelled"}
YAKSH_FAILED = CallOutcome(connected=False, end_reason=EndReason.ERROR, caller_error="boom")
"""A call that failed on Yaksh's side, which a run tries again."""
LOCK_WAITERS = text(
    "SELECT count(*) FROM pg_stat_activity"
    " WHERE datname = current_database() AND wait_event_type = 'Lock'"
)


AGENT = {
    "name": "Front desk",
    "agent_number": "+14155550100",
    "brief": "Answers the front desk line and books rooms for hotel guests.",
}
OUTBOUND_AGENT: dict[str, Any] = {
    "name": "Payment reminders",
    "brief": "Calls customers about overdue payments and takes a payment date.",
    "direction": "outbound",
    "agent_number": None,
    "outbound": {
        "trigger": {
            "url": "https://agents.example.com/calls",
            "headers": [{"name": "Authorization", "value": "Bearer {{secrets.KEY}}"}],
            "body": {
                "to": "{{yaksh.number}}",
                "customer": {"name": "{{agent_data.Customer name}}"},
                "tags": ["yaksh", "{{yaksh.conversation_id}}"],
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
    listed_languages=(Language.EN, Language.HI),
)
UNLISTED_VOICE = ProviderVoice(
    id="voice-new", name="Riya", gender=VoiceGender.FEMALE, accent="indian"
)
"""On the provider account but not in the voices list until a test adds it."""
SPOKEN = as_wav(array("h", [8000, -8000] * 2000).tobytes())
"""What the fake voice says: half a second of call audio, a loud square wave."""
CALLER = {
    "instructions": "You want to book a room.",
    "first_words": "Hello",
    "nudge": "Hello? Are you still there?",
    "caller_language": Language.EN,
    "voice": VoiceSettings(provider=VoiceProvider.ELEVENLABS, id=ENGLISH_VOICE.id),
    "max_turns": 20,
    "goodbye": "Okay, thanks. I have to go now. Bye.",
}
PERSONA = {
    "name": "Rushed caller",
    "prompt": "You are in a hurry.",
    "voice": {"provider": "elevenlabs", "id": ENGLISH_VOICE.id},
}


def data_sets(**fields: Any) -> list[dict[str, Any]]:
    """The test scenario's one data set, with these fields changed."""
    return [{**SCENARIO["data_sets"][0], **fields}]


SCENARIO: dict[str, Any] = {
    "name": "Reschedule a cleaning",
    "instructions": (
        "Move your cleaning to an evening next week; if none is free, keep the current one."
    ),
    "unknown_facts": ["Patient ID"],
    "criteria": ["Reads the new date and time back before it moves the appointment."],
    "data_sets": [
        {
            "name": "Data set 1",
            "known_facts": [
                {"name": "Name", "value": "Priya Raman"},
                {"name": "Current appointment", "value": "next Thursday, 10:30 am"},
            ],
        }
    ],
}


async def create_agent(client: AsyncClient, **overrides: Any) -> dict[str, Any]:
    body = {"write_scenarios": False, **AGENT, **overrides}
    response = await client.post("/api/v1/agents", json=body)
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


async def new_persona_id(client: AsyncClient) -> str:
    return (await create_persona(client, name=f"Caller {uuid.uuid4()}"))["id"]


async def create_scenario(client: AsyncClient, agent_id: str, **overrides: Any) -> dict[str, Any]:
    if "persona_id" not in overrides:
        overrides["persona_id"] = await new_persona_id(client)
    response = await client.post(
        f"/api/v1/agents/{agent_id}/scenarios", json={**SCENARIO, **overrides}
    )
    assert response.status_code == 201, response.text
    return response.json()


async def start(
    client: AsyncClient,
    agent_id: str,
    *,
    persona_id: str | None = None,
    scenario_id: str | None = None,
) -> dict[str, Any]:
    """The conversation of a new run of one scenario, without retries. Without a scenario, a new
    one of the agent with persona_id, or with a new persona, is started."""
    if scenario_id is None:
        scenario = await create_scenario(
            client,
            agent_id,
            name=f"Scenario {uuid.uuid4()}",
            persona_id=persona_id or await new_persona_id(client),
        )
        scenario_id = str(scenario["id"])
    else:
        assert persona_id is None, "a scenario runs with its own persona"
    response = await start_run(client, agent_id, [scenario_id], max_retries=0)
    assert response.status_code == 202, response.text
    (conversation,) = await run_conversations(client, response.json()["id"])
    return conversation


async def start_run(
    client: AsyncClient,
    agent_id: str,
    scenarios: list[str | dict[str, Any]],
    *,
    key: str | None = None,
    **fields: Any,
) -> Response:
    """A scenario given by its id runs with its own persona."""
    listed = [{"scenario_id": item} if isinstance(item, str) else item for item in scenarios]
    return await client.post(
        "/api/v1/runs",
        json={"agent_id": agent_id, "scenarios": listed, **fields},
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


async def claim(
    db: Db,
    *,
    worker_id: str = "w1",
    pool_app_id: str | None = POOL_APP_ID,
    receiving_app_id: str | None = None,
) -> str | None:
    """The id of the conversation a worker claims next, if any."""
    async with db() as session:
        claimed = await conversations.claim_next(
            session, worker_id, 30, pool_app_id, receiving_app_id
        )
    return None if claimed is None else str(claimed.id)


async def reap(db: Db, rest_s: int = 0) -> int:
    async with db() as session:
        return await conversations.reap_expired(session, rest_s)


async def finish(
    db: Db,
    conversation_id: str,
    outcome: CallOutcome,
    worker_id: str = "w1",
    transcript: Transcript | None = None,
    audio: StoredAudio | None = None,
) -> bool:
    """Record the outcome of a conversation the worker claimed, as the worker does."""
    async with db() as session:
        return await conversations.finalize(
            session,
            uuid.UUID(conversation_id),
            worker_id,
            outcome,
            transcript or Transcript(),
            audio or StoredAudio(),
            0,
        )


async def evaluate_queued(db: Db, metrics: dict[str, dict[MetricKey, Metric]]) -> list[str]:
    """Finish every queued evaluation as an evaluator would, with the metrics given for its
    conversation (none for the others); return the conversations it evaluated."""
    done = []
    while True:
        async with db() as session:
            evaluation = await evaluations.claim(session, "e1", 60)
        if evaluation is None:
            return done
        conversation_id = str(evaluation.conversation_id)
        async with db() as session:
            assert await evaluations.finish(
                session,
                evaluation.id,
                evaluation.claim_seq,
                Evaluated(metrics=metrics.get(conversation_id, {})),
                audit=False,
            )
        done.append(conversation_id)


async def expire_leases(db: Db, which: ColumnElement[bool]) -> None:
    """End the leases of these conversations, as if their workers had stopped."""
    async with db.begin() as session:
        await session.execute(
            update(Conversation)
            .where(which)
            .values(lease_expires_at=func.now() - timedelta(seconds=1))
        )


async def eventually[T](
    probe: Callable[[], Awaitable[T]], done: Callable[[T], bool], timeout: float = 5.0
) -> T:
    """Probe until done holds for the value, and fail with the last value after timeout
    seconds."""
    deadline = asyncio.get_running_loop().time() + timeout
    while not done(value := await probe()):
        assert asyncio.get_running_loop().time() < deadline, value
        await asyncio.sleep(0.05)
    return value


async def wait_for_run(
    client: AsyncClient, run_id: str, status: str, timeout: float = 10.0
) -> dict[str, Any]:
    async def run() -> dict[str, Any]:
        return (await client.get(f"/api/v1/runs/{run_id}")).json()

    return await eventually(run, lambda found: found["status"] == status, timeout)


async def wait_for(
    client: AsyncClient, conversation_id: str, statuses: set[str], timeout: float = 5.0
) -> dict[str, Any]:
    async def conversation() -> dict[str, Any]:
        return (await client.get(f"/api/v1/conversations/{conversation_id}")).json()

    return await eventually(conversation, lambda found: found["status"] in statuses, timeout)


async def wait_for_lock_waiters(db: Db, count: int, timeout: float = 5.0) -> None:
    """Wait until `count` database sessions wait on a lock, so a test releases a lock it holds
    only after every request it races has reached that lock. Each read is its own
    transaction, because Postgres reads pg_stat_activity once per transaction."""
    async with db() as session:
        connection = await session.connection(execution_options={"isolation_level": "AUTOCOMMIT"})
        await eventually(lambda: connection.scalar(LOCK_WAITERS), lambda n: n >= count, timeout)


async def wait_until(condition: Callable[[], bool], timeout: float = 5.0) -> None:
    async def check() -> bool:
        return condition()

    await eventually(check, bool, timeout)


async def checked_counts(client: AsyncClient, run_id: str) -> dict[str, int]:
    """The run's counts by outcome group, each checked against the list of the group's latest
    attempts."""
    counts = (await client.get(f"/api/v1/runs/{run_id}")).json()["counts"]
    for group, count in counts.items():
        listed = await run_conversations(client, run_id, group=group, latest_attempts=True)
        assert len(listed) == count, group
    return counts


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


POOL_APPLICATION = PlivoApplication(
    app_id=POOL_APP_ID,
    name="Yaksh-Test",
    answer_url="http://yaksh.test/incoming",
    answer_method="POST",
    hangup_url="http://yaksh.test/incoming/hangup",
    hangup_method="POST",
)
"""The receiving application, sending calls to the public URL of make_settings."""


class FakePlivoAccount:
    """A Plivo account held in memory: its numbers, each with the application it is linked to,
    and its applications. down makes every call fail as when Plivo cannot be reached."""

    def __init__(
        self,
        numbers: list[AccountNumber] | None = None,
        applications: list[PlivoApplication] | None = None,
    ) -> None:
        self.numbers = {entry.number: entry for entry in (POOL if numbers is None else numbers)}
        self.applications = {
            app.app_id: app
            for app in ([POOL_APPLICATION] if applications is None else applications)
        }
        self.down = False
        self.links: list[tuple[str, str | None]] = []

    def _reach(self) -> None:
        if self.down:
            raise PlivoError("plivo is down", status=503, reason="Plivo is down")

    async def list_numbers(self) -> list[AccountNumber]:
        self._reach()
        return list(self.numbers.values())

    async def get_application(self, app_id: str) -> PlivoApplication:
        self._reach()
        if app_id not in self.applications:
            raise PlivoError(f"no application {app_id}", status=404, reason="not found")
        return self.applications[app_id]

    async def list_applications(self) -> list[PlivoApplication]:
        self._reach()
        return list(self.applications.values())

    async def create_application(self, name: str, answer_url: str, hangup_url: str) -> str:
        self._reach()
        app_id = str(20_000_000_000_000_000 + len(self.applications))
        self.applications[app_id] = PlivoApplication(
            app_id=app_id,
            name=name,
            answer_url=answer_url,
            answer_method="POST",
            hangup_url=hangup_url,
            hangup_method="POST",
        )
        return app_id

    async def update_application(self, app_id: str, answer_url: str, hangup_url: str) -> None:
        self._reach()
        self.applications[app_id] = self.applications[app_id].model_copy(
            update={"answer_url": answer_url, "hangup_url": hangup_url}
        )

    async def link_number(self, number: str, app_id: str | None) -> None:
        self._reach()
        self.links.append((number, app_id))
        self.numbers[number] = self.numbers[number].model_copy(update={"application_id": app_id})


class FakeProviders:
    """The API's provider clients, whatever the stored settings say."""

    def __init__(self, voice_clients: Any, generation_model: Any) -> None:
        self.voice_clients_ = voice_clients
        self.generation_model_ = generation_model
        self.account = FakePlivoAccount()

    def phone_account(self, _auth_id: str, _auth_token: str) -> FakePlivoAccount:
        return self.account

    def voice_clients(self, _settings: AppSettings) -> Any:
        return self.voice_clients_

    def generation_model(self, _settings: AppSettings) -> Any:
        return self.generation_model_

    def brief_model(self, _settings: AppSettings) -> Any:
        return self.generation_model_

    plivo_api_url = "http://127.0.0.1:9"
    """Where plivo_cx clients go: nowhere, until a test points it at its stand-in for Plivo."""

    def plivo_cx(self, auth_id: str, auth_token: str) -> PlivoApi:
        return PlivoApi(auth_id, auth_token, base_url=self.plivo_api_url)

    elevenlabs_api_url = "http://127.0.0.1:9"
    """Where elevenlabs_agents clients go, whatever the region: nowhere, until a test points it at
    its stand-in for ElevenLabs."""

    def elevenlabs_agents(self, api_key: str, region: ElevenLabsRegion) -> ElevenLabsAgentsApi:
        return ElevenLabsAgentsApi(api_key, base_url=self.elevenlabs_api_url)

    retell_api_url = "http://127.0.0.1:9"
    """Where retell clients go: nowhere, until a test points it at its stand-in for Retell."""

    def retell(self, api_key: str) -> RetellApi:
        return RetellApi(api_key, base_url=self.retell_api_url)

    vapi_api_url = "http://127.0.0.1:9"
    """Where vapi clients go, whatever the region: nowhere, until a test points it at its
    stand-in for Vapi."""

    def vapi(self, api_key: str, region: VapiRegion) -> VapiApi:
        return VapiApi(api_key, base_url=self.vapi_api_url)

    async def close(self) -> None:
        pass


class FixedAccount(PhoneAccount):
    """A Plivo account that is never asked: the worker leases the numbers of pool_app_id and
    receives on receiving_app_id."""

    def __init__(
        self,
        sessionmaker: Db,
        settings: Settings,
        pool_app_id: str | None,
        receiving_app_id: str | None,
        problem: str | None,
    ) -> None:
        super().__init__(sessionmaker, settings)
        self.pool_app_id = pool_app_id
        self.receiving_app_id = receiving_app_id
        self.outbound_problem = problem

    async def refresh(self, app: AppSettings) -> None:
        pass


class FixedSource(SettingsSource):
    """Stored settings that never change, for a worker without a database."""

    def __init__(self, settings: AppSettings = APP_SETTINGS) -> None:
        self._fixed = settings

    async def current(self) -> AppSettings:
        return self._fixed


def make_worker(
    sessionmaker: Db,
    caller: Any,
    settings: Settings,
    *,
    worker_id: str | None = None,
    pool_app_id: str | None = POOL_APP_ID,
    receiving_app_id: str | None = None,
    outbound_problem: str | None = None,
    source: SettingsSource | None = None,
    store: FileStore | None = None,
    timings: Timings = FAST,
) -> Worker:
    return Worker(
        sessionmaker,
        caller,
        settings,
        source or SettingsSource(sessionmaker, Cipher(ENCRYPTION_KEY)),
        FixedAccount(sessionmaker, settings, pool_app_id, receiving_app_id, outbound_problem),
        store or FakeFileStore(),
        worker_id=worker_id,
        timings=timings,
    )


def make_evaluator(
    sessionmaker: Db,
    settings: Settings,
    model: Any = None,
    *,
    sources_model: Any = None,
    jev: Any = None,
    store: FileStore | None = None,
) -> Evaluator:
    """An evaluator that judges with these clients, whatever the stored settings say."""
    return Evaluator(
        sessionmaker,
        settings,
        SettingsSource(sessionmaker, Cipher(ENCRYPTION_KEY)),
        store or FakeFileStore(),
        clients=lambda _settings: JudgeClients(model, sources_model, jev),
    )


async def save_settings(
    sessionmaker: Db,
    values: dict[str, Any] | None = None,
    secrets: dict[str, str | None] | None = None,
) -> AppSettings:
    """Change the stored settings, as the Settings page does."""
    async with sessionmaker() as session:
        return await store.change(session, Cipher(ENCRYPTION_KEY), values=values, secrets=secrets)


def make_settings(tmp_path: Path, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "api_token": TOKEN,
        "database_url": OFFLINE_DATABASE_URL,
        "frontend_dist": tmp_path / "missing",
        "public_url": "http://yaksh.test",
        "encryption_key": ENCRYPTION_KEY,
    }
    return Settings.model_validate({**values, **overrides})


async def first(*events: asyncio.Event) -> asyncio.Event:
    waiters = {asyncio.ensure_future(event.wait()): event for event in events}
    done, pending = await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)
    for waiter in pending:
        waiter.cancel()
    return waiters[next(iter(done))]


class FixedClock(Clock):
    def __init__(self) -> None:
        super().__init__()
        self.now = 0

    def ms(self) -> int:
        return self.now


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
        self.recording: bytes | None = None
        self.caller_voice: bytes | None = None

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
                recording=self.recording,
                caller_voice=self.caller_voice,
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
                caller_reason="the room is booked",
            )
        return CallOutcome(
            connected=True,
            end_reason=EndReason.AGENT_HANGUP,
            recording=self.recording,
            caller_voice=self.caller_voice,
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
        self.changes: list[str] = []
        """The fork planner's answer."""
        self.brief = "Books, moves and cancels dental appointments for callers."
        self.persona: dict[str, Any] = {
            "name": "Asha Rao",
            "prompt": "You are tired and short of time. Give brief answers, and sigh often.",
            "language": "hi",
            "voice_gender": "female",
            "speed": "fast",
            "noise": "street",
            "noise_level": "normal",
            "speaker": None,
            "left_out": [],
        }
        self.down = False

    async def complete_json(
        self, *, system: str, user: str, name: str, schema: dict[str, Any]
    ) -> ModelAnswer:
        self.calls.append((name, user))
        if self.down:
            raise ModelCallError("the model call failed: timed out", temporary=True)
        if name == "capabilities":
            data = {"capabilities": self.capabilities}
        elif name == "questions":
            data = self.questions
        elif name == "brief":
            data = {"brief": self.brief}
        elif name == "persona":
            data = self.persona
        elif name == "changes":
            data = {"changes": self.changes}
        else:
            data = self.write(user)
        return ModelAnswer(data=data, model="fake", input_tokens=None, output_tokens=None)

    async def close(self) -> None:
        pass


class Scripted:
    """A judge model that gives its answers in order, or raises the error in their place."""

    def __init__(self, *answers: dict[str, Any] | Exception) -> None:
        self.answers = list(answers)
        self.requests: list[str] = []

    async def complete_json(
        self, *, system: str, user: str, name: str, schema: dict[str, Any]
    ) -> ModelAnswer:
        self.requests.append(user)
        found = self.answers.pop(0)
        if isinstance(found, Exception):
            raise found
        return ModelAnswer(data=found, model="judge-1", input_tokens=100, output_tokens=20)

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
        "instructions": "Get the request done, then end the call.",
        "known_facts": [{"name": "Name", "value": "Priya Raman"}],
        "unknown_facts": [],
        "criteria": ["The agent confirms the name Priya Raman."],
        "agent_data": [],
    }


class FakeFileStore:
    def __init__(self) -> None:
        self.files: dict[str, tuple[bytes, str]] = {}
        self.down = False

    async def put(self, key: str, data: bytes, media_type: str) -> None:
        if self.down:
            raise UnavailableError("file storage refused the upload")
        self.files[key] = (data, media_type)

    async def close(self) -> None:
        pass

    async def get(self, key: str) -> bytes:
        if self.down or key not in self.files:
            raise UnavailableError("file storage could not return the file")
        return self.files[key][0]

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
        return SPOKEN if voice.id in self.voices else None

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
async def db(settings: Settings) -> AsyncIterator[Db]:
    """Sessions on the test database, for steps the API does not offer."""
    engine = create_engine(settings.database_url.encoded_string())
    yield create_sessionmaker(engine)
    await engine.dispose()


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
def providers(
    voice_clients: dict[VoiceProvider, FakeVoiceClient], generation_model: FakeJsonModel
) -> FakeProviders:
    return FakeProviders(voice_clients, generation_model)


@pytest.fixture
async def client(
    settings: Settings, providers: FakeProviders, file_store: FakeFileStore
) -> AsyncIterator[AsyncClient]:
    """An API client whose voices list holds the English and the Hindi test voice."""
    app = create_app(settings)
    app.state.providers = providers
    app.state.file_store = file_store
    async with create_sessionmaker(app.state.engine)() as session:
        await store.change(
            session,
            app.state.source.cipher,
            values={"phone": {"application_id": POOL_APP_ID}},
            secrets=STORED_SECRETS,
        )
    async with create_sessionmaker(app.state.engine)() as session:
        await numbers.sync_numbers(session, POOL, {})
        session.add(listed_voice(ENGLISH_VOICE, Language.EN))
        session.add(listed_voice(HINDI_VOICE, Language.EN, Language.HI))
        await session.commit()
    transport = ASGITransport(app=app)
    headers = {"Authorization": f"Bearer {TOKEN}"}
    async with AsyncClient(transport=transport, base_url="http://test", headers=headers) as client:
        yield client
    await app.state.generations.close()
    await app.state.engine.dispose()
    engine = create_async_engine(settings.database_url.encoded_string())
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "TRUNCATE phone_numbers, refused_calls, labels, labelers, judge_calls,"
                " evaluation_items, judge_versions, metric_values, evaluations, conversations,"
                " runs, agent_versions, agents, persona_versions, personas, voices,"
                " scenario_versions, scenarios, workers, documents, scenario_generations"
            )
        )
        await connection.execute(
            text("UPDATE app_settings SET values = '{}', secrets = '{}', version = version + 1")
        )
        await connection.execute(
            text("UPDATE phone_checks SET checked_at = NULL, error = NULL, claimed_until = NULL")
        )
    await engine.dispose()


@pytest.fixture
def caller() -> FakeCaller:
    return FakeCaller()


@pytest.fixture
async def worker(
    client: AsyncClient, settings: Settings, caller: FakeCaller, file_store: FakeFileStore
) -> AsyncIterator[Worker]:
    engine = create_engine(settings.database_url.encoded_string())
    worker = make_worker(
        create_sessionmaker(engine), caller, settings, worker_id="test-worker", store=file_store
    )
    stop = asyncio.Event()
    task = asyncio.create_task(worker.run(stop))
    yield worker
    stop.set()
    await task
    await engine.dispose()


def response_body(
    text: str, *, refusal: str | None = None, incomplete: str | None = None
) -> dict[str, Any]:
    """A Responses API answer: `text`, or a refusal, or `text` cut short for `incomplete`."""
    part = (
        {"type": "refusal", "refusal": refusal}
        if refusal
        else {"type": "output_text", "text": text, "annotations": []}
    )
    return {
        "id": "resp-1",
        "object": "response",
        "created_at": 0,
        "model": "gpt-4.1",
        "status": "incomplete" if incomplete else "completed",
        "incomplete_details": {"reason": incomplete} if incomplete else None,
        "output": [
            {
                "type": "message",
                "id": "msg-1",
                "role": "assistant",
                "status": "completed",
                "content": [part],
            }
        ],
        "usage": {
            "input_tokens": 12,
            "output_tokens": 3,
            "total_tokens": 15,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 0},
        },
    }


UNSUPPORTED = {
    "error": {
        "message": "Unsupported parameter: 'reasoning.effort' is not supported with this model.",
        "type": "invalid_request_error",
        "param": "reasoning.effort",
        "code": "unsupported_parameter",
    }
}
OUTAGE = {"error": {"message": "The service is temporarily unavailable.", "type": "server_error"}}


class FakeProvider:
    """An OpenAI-compatible Responses API that records each request."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, dict[str, str], dict[str, Any]]] = []
        self.reply: tuple[int, dict[str, Any]] = (200, response_body('{"answer": "yes"}'))
        self.reasoning = True
        """Whether the model takes a reasoning effort; gpt-4.1 refuses it with a 400."""
        self.outages = 0
        """How many of the next requests fail with a 503."""

    def efforts(self) -> list[str | None]:
        return [body.get("reasoning", {}).get("effort") for _, _, body in self.requests]


@pytest.fixture
async def provider() -> AsyncIterator[tuple[str, FakeProvider]]:
    fake = FakeProvider()
    app = FastAPI()

    @app.post("/{path:path}")
    async def respond(path: str, request: Request) -> JSONResponse:
        sent = await request.json()
        fake.requests.append((f"/{path}", dict(request.query_params), sent))
        if fake.outages:
            fake.outages -= 1
            return JSONResponse(OUTAGE, status_code=503)
        if not fake.reasoning and "reasoning" in sent:
            return JSONResponse(UNSUPPORTED, status_code=400)
        status, body = fake.reply
        return JSONResponse(body, status_code=status)

    server = PlivoServer(app, port=0)
    await server.start()
    yield f"http://127.0.0.1:{server.port}", fake
    await server.stop(2.0)
