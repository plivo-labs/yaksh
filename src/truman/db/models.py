import uuid
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
    true,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, MappedColumn, mapped_column

from truman.db.base import Base
from truman.domain.agents import Direction, Transport
from truman.domain.background_noise import NoiseLevel, NoiseSound
from truman.domain.conversations import Channel, ConversationStatus, EndReason
from truman.domain.generation import GenerationMode, GenerationStatus
from truman.domain.languages import Language
from truman.domain.scenarios import Category
from truman.domain.voices import VoiceGender, VoiceProvider


def pg_enum[E: StrEnum](enum: type[E], name: str) -> Enum:
    return Enum(enum, name=name, values_callable=lambda e: [member.value for member in e])


def uuid_primary_key() -> MappedColumn[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()"))


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[uuid.UUID] = uuid_primary_key()
    name: Mapped[str] = mapped_column(Text)
    external_id: Mapped[str | None] = mapped_column(Text)
    direction: Mapped[Direction] = mapped_column(pg_enum(Direction, "agent_direction"))
    transport: Mapped[Transport] = mapped_column(pg_enum(Transport, "agent_transport"))
    agent_number: Mapped[str | None] = mapped_column(Text)
    outbound: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    agent_speaks_first: Mapped[bool] = mapped_column(Boolean, default=True)
    language: Mapped[Language] = mapped_column(pg_enum(Language, "language"))
    brief: Mapped[str | None] = mapped_column(Text)
    config: Mapped[str | None] = mapped_column(Text)
    knowledge_base: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    current_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index(
            "ix_agents_external_id_live",
            "external_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )


class AgentVersion(Base):
    __tablename__ = "agent_versions"

    id: Mapped[uuid.UUID] = uuid_primary_key()
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agents.id"))
    version: Mapped[int] = mapped_column(Integer)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("agent_id", "version"),
        UniqueConstraint("id", "agent_id"),
    )


class Run(Base):
    """Conversations started together against one agent: each scenario, repeated."""

    __tablename__ = "runs"

    id: Mapped[uuid.UUID] = uuid_primary_key()
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agents.id"))
    agent_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    name: Mapped[str | None] = mapped_column(Text)
    repeats: Mapped[int] = mapped_column(Integer)
    max_duration_s: Mapped[int] = mapped_column(Integer)
    max_turns: Mapped[int] = mapped_column(Integer)
    max_parallel: Mapped[int | None] = mapped_column(Integer)
    """At most this many of its conversations on the line at once; None is no run limit."""
    start_interval_s: Mapped[int | None] = mapped_column(Integer)
    """The least time between two call starts of the run; None is no wait."""
    max_retries: Mapped[int] = mapped_column(Integer)
    """How many times a conversation that ends with an error is tried again."""
    background_noise_sound: Mapped[NoiseSound | None] = mapped_column(
        pg_enum(NoiseSound, "noise_sound")
    )
    """None plays each persona's own setting."""
    background_noise_level: Mapped[NoiseLevel | None] = mapped_column(
        pg_enum(NoiseLevel, "noise_level")
    )
    request_key: Mapped[str | None] = mapped_column(Text, unique=True)
    """The client's idempotency key: the same request with it returns this run."""
    request_hash: Mapped[str | None] = mapped_column(Text)
    """A hash of the validated request, so the key with another request is refused."""
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        ForeignKeyConstraint(
            ["agent_version_id", "agent_id"], ["agent_versions.id", "agent_versions.agent_id"]
        ),
        UniqueConstraint("id", "agent_id"),
        CheckConstraint("(request_key IS NULL) = (request_hash IS NULL)", name="request_together"),
        CheckConstraint(
            "(background_noise_sound IS NULL) = (background_noise_level IS NULL)",
            name="background_noise_together",
        ),
        Index("ix_runs_agent_created", "agent_id", text("created_at DESC")),
    )


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = uuid_primary_key()
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agents.id"))
    agent_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    channel: Mapped[Channel] = mapped_column(pg_enum(Channel, "channel"), default=Channel.VOICE)
    direction: Mapped[Direction] = mapped_column(
        pg_enum(Direction, "agent_direction"), default=Direction.INBOUND
    )
    persona_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("personas.id"))
    persona_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    scenario_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    scenario_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    language: Mapped[Language] = mapped_column(pg_enum(Language, "language"))
    instructions: Mapped[str] = mapped_column(Text)
    nudge: Mapped[str] = mapped_column(Text)
    today: Mapped[date] = mapped_column(Date)
    """The date the caller is told is today, in time_zone."""
    time_zone: Mapped[str] = mapped_column(Text)
    caller_number: Mapped[str | None] = mapped_column(Text)
    call_uuid: Mapped[str | None] = mapped_column(Text)
    dial_deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    """Outbound only: the time until which a call from the agent is accepted."""
    agent_caller_id: Mapped[str | None] = mapped_column(Text)
    """Outbound only: the number the agent called from."""
    max_duration_s: Mapped[int] = mapped_column(Integer)
    max_turns: Mapped[int] = mapped_column(Integer)
    background_noise_sound: Mapped[NoiseSound] = mapped_column(pg_enum(NoiseSound, "noise_sound"))
    background_noise_level: Mapped[NoiseLevel] = mapped_column(pg_enum(NoiseLevel, "noise_level"))
    status: Mapped[ConversationStatus] = mapped_column(
        pg_enum(ConversationStatus, "conversation_status"), default=ConversationStatus.QUEUED
    )
    end_reason: Mapped[EndReason | None] = mapped_column(pg_enum(EndReason, "end_reason"))
    failure_reason: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    talk_ms: Mapped[int | None] = mapped_column(Integer)
    recording_path: Mapped[str | None] = mapped_column(Text)
    caller_voice_path: Mapped[str | None] = mapped_column(Text)
    """The caller's own voice, each reply back to back (see the transcript's caller replies)."""
    transcript: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    caller_reason: Mapped[str | None] = mapped_column(Text)
    """Why the caller ended the call, in its own words: not a verdict."""
    caller_settings: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    """The models and voice the caller ran (`CallerSettings`); None before a call connects."""
    caller_usage: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    """What the caller's services consumed (`CallerUsage`)."""
    line_facts: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    """Plivo's hangup report for a connected call (`LineFacts`): who hung up."""
    claimed_by: Mapped[str | None] = mapped_column(Text)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    """The run that made the conversation; None for a single test call."""
    repeat: Mapped[int | None] = mapped_column(Integer)
    """Which repeat of its scenario in the run, from 1."""
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    """1 for the first try; a retry has the next number."""
    retry_of: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("conversations.id"))
    """The conversation this one tries again."""
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        ForeignKeyConstraint(
            ["agent_version_id", "agent_id"], ["agent_versions.id", "agent_versions.agent_id"]
        ),
        ForeignKeyConstraint(["run_id", "agent_id"], ["runs.id", "runs.agent_id"]),
        UniqueConstraint("run_id", "repeat", "scenario_id", "attempt"),
        CheckConstraint('(run_id IS NULL) = ("repeat" IS NULL)', name="run_has_repeat"),
        CheckConstraint(
            "attempt >= 1 AND (retry_of IS NULL) = (attempt = 1)"
            " AND (retry_of IS NULL OR run_id IS NOT NULL)",
            name="retry_is_later_attempt_in_run",
        ),
        ForeignKeyConstraint(
            ["persona_version_id", "persona_id"],
            ["persona_versions.id", "persona_versions.persona_id"],
        ),
        ForeignKeyConstraint(["scenario_id", "agent_id"], ["scenarios.id", "scenarios.agent_id"]),
        ForeignKeyConstraint(
            ["scenario_version_id", "scenario_id"],
            ["scenario_versions.id", "scenario_versions.scenario_id"],
        ),
        Index("ix_conversations_agent_created", "agent_id", text("created_at DESC")),
        Index("ix_conversations_status_created", "status", "created_at"),
        Index("ix_conversations_run_status", "run_id", "status"),
        Index("ix_conversations_run_started", "run_id", "started_at"),
        Index("ix_conversations_retry_of", "retry_of"),
    )


class RefusedCall(Base):
    """A call to one of Truman's numbers that Truman did not take, and why. "No call came" can
    then be told from a call that Truman turned away."""

    __tablename__ = "refused_calls"

    id: Mapped[uuid.UUID] = uuid_primary_key()
    call_uuid: Mapped[str] = mapped_column(Text, unique=True)
    to_number: Mapped[str] = mapped_column(Text)
    from_number: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("conversations.id"))
    """The conversation that held the number, when one did."""
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Persona(Base):
    __tablename__ = "personas"

    id: Mapped[uuid.UUID] = uuid_primary_key()
    name: Mapped[str] = mapped_column(Text)
    builtin_key: Mapped[str | None] = mapped_column(Text, unique=True)
    prompt: Mapped[str] = mapped_column(Text)
    language: Mapped[Language] = mapped_column(pg_enum(Language, "language"))
    voice_provider: Mapped[VoiceProvider] = mapped_column(pg_enum(VoiceProvider, "voice_provider"))
    voice_id: Mapped[str] = mapped_column(Text)
    voice_speed: Mapped[float] = mapped_column(Float)
    voice_stability: Mapped[float] = mapped_column(Float)
    voice_gender: Mapped[VoiceGender | None] = mapped_column(pg_enum(VoiceGender, "voice_gender"))
    background_noise_sound: Mapped[NoiseSound] = mapped_column(pg_enum(NoiseSound, "noise_sound"))
    background_noise_level: Mapped[NoiseLevel] = mapped_column(pg_enum(NoiseLevel, "noise_level"))
    current_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index(
            "ix_personas_name_live",
            func.lower(text("name")),
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )


class PersonaVersion(Base):
    __tablename__ = "persona_versions"

    id: Mapped[uuid.UUID] = uuid_primary_key()
    persona_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("personas.id"))
    version: Mapped[int] = mapped_column(Integer)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("persona_id", "version"),
        UniqueConstraint("id", "persona_id"),
    )


class Voice(Base):
    """A voice personas can use. Personas keep their own copy of the voice settings, so no
    change here reaches a persona version or a call."""

    __tablename__ = "voices"

    id: Mapped[uuid.UUID] = uuid_primary_key()
    provider: Mapped[VoiceProvider] = mapped_column(pg_enum(VoiceProvider, "voice_provider"))
    provider_voice_id: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    gender: Mapped[VoiceGender | None] = mapped_column(pg_enum(VoiceGender, "voice_gender"))
    accent: Mapped[str | None] = mapped_column(Text)
    languages: Mapped[list[Language]] = mapped_column(ARRAY(pg_enum(Language, "language")))
    listed_languages: Mapped[list[Language]] = mapped_column(ARRAY(pg_enum(Language, "language")))
    builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index(
            "ix_voices_provider_voice_live",
            "provider",
            "provider_voice_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        CheckConstraint("cardinality(languages) > 0", name="languages_not_empty"),
    )


class ScenarioGeneration(Base):
    """One request to write scenarios, and the agent version whose context it read."""

    __tablename__ = "scenario_generations"

    id: Mapped[uuid.UUID] = uuid_primary_key()
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agents.id"))
    agent_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_versions.id"))
    mode: Mapped[GenerationMode] = mapped_column(pg_enum(GenerationMode, "generation_mode"))
    count: Mapped[int] = mapped_column(Integer)
    instructions: Mapped[str] = mapped_column(Text)
    document_ids: Mapped[list[str]] = mapped_column(JSONB)
    status: Mapped[GenerationStatus] = mapped_column(
        pg_enum(GenerationStatus, "generation_status"), default=GenerationStatus.RUNNING
    )
    saved: Mapped[int] = mapped_column(Integer, default=0)
    dropped: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Scenario(Base):
    __tablename__ = "scenarios"

    id: Mapped[uuid.UUID] = uuid_primary_key()
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agents.id"))
    persona_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("personas.id"))
    """The persona the scenario runs with. Not versioned: each conversation pins the persona
    and its version."""
    name: Mapped[str] = mapped_column(Text)
    category: Mapped[Category] = mapped_column(
        pg_enum(Category, "scenario_category"),
        default=Category.HAPPY_PATH,
        server_default=Category.HAPPY_PATH.value,
    )
    description: Mapped[str | None] = mapped_column(Text)
    generation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("scenario_generations.id"))
    """The generation that wrote the scenario; None for one written by hand."""
    config: Mapped[dict[str, Any]] = mapped_column(JSONB)
    current_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index(
            "ix_scenarios_agent_name_live",
            "agent_id",
            func.lower(text("name")),
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        UniqueConstraint("id", "agent_id"),
    )


class ScenarioVersion(Base):
    __tablename__ = "scenario_versions"

    id: Mapped[uuid.UUID] = uuid_primary_key()
    scenario_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("scenarios.id"))
    version: Mapped[int] = mapped_column(Integer)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("scenario_id", "version"),
        UniqueConstraint("id", "scenario_id"),
    )


class PhoneNumber(Base):
    """A number on the Plivo account; when enabled, leased to one conversation at a time and
    rotated by last use."""

    __tablename__ = "phone_numbers"

    number: Mapped[str] = mapped_column(Text, primary_key=True)
    alias: Mapped[str | None] = mapped_column(Text)
    region: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    application_id: Mapped[str | None] = mapped_column(Text)
    application_name: Mapped[str | None] = mapped_column(Text)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("conversations.id"))
    leased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    available_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Document(Base):
    """Text about an agent, from an uploaded file or pasted. Never changed after creation;
    the original file, when there is one, is in the file store under storage_key."""

    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = uuid_primary_key()
    name: Mapped[str] = mapped_column(Text)
    media_type: Mapped[str | None] = mapped_column(Text)
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    sha256: Mapped[str | None] = mapped_column(Text)
    storage_key: Mapped[str | None] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
    characters: Mapped[int] = mapped_column(Integer)
    pages: Mapped[int | None] = mapped_column(Integer)
    empty_pages: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "(storage_key IS NULL) = (media_type IS NULL)"
            " AND (storage_key IS NULL) = (size_bytes IS NULL)"
            " AND (storage_key IS NULL) = (sha256 IS NULL)",
            name="file_fields_together",
        ),
    )


class RunningWorker(Base):
    """A running worker as it last reported itself; one not seen for a lease has stopped."""

    __tablename__ = "workers"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    receiving_app_id: Mapped[str | None] = mapped_column(Text)
    """The Plivo application whose calls the worker receives, so it runs outbound tests."""
    outbound_problem: Mapped[str | None] = mapped_column(Text)
    """Why the worker runs no outbound tests, when it was set up for them."""
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
