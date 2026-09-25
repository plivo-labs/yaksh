import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
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
from truman.domain.conversations import Channel, ConversationStatus, EndReason
from truman.domain.languages import Language
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
    agent_number: Mapped[str] = mapped_column(Text)
    agent_speaks_first: Mapped[bool] = mapped_column(Boolean, default=True)
    brief: Mapped[str | None] = mapped_column(Text)
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


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = uuid_primary_key()
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agents.id"))
    agent_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    channel: Mapped[Channel] = mapped_column(pg_enum(Channel, "channel"), default=Channel.VOICE)
    persona_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("personas.id"))
    persona_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    goal: Mapped[str] = mapped_column(Text)
    language: Mapped[Language] = mapped_column(pg_enum(Language, "language"))
    instructions: Mapped[str] = mapped_column(Text)
    nudge: Mapped[str] = mapped_column(Text)
    caller_number: Mapped[str | None] = mapped_column(Text)
    call_uuid: Mapped[str | None] = mapped_column(Text)
    max_duration_s: Mapped[int] = mapped_column(Integer)
    status: Mapped[ConversationStatus] = mapped_column(
        pg_enum(ConversationStatus, "conversation_status"), default=ConversationStatus.QUEUED
    )
    end_reason: Mapped[EndReason | None] = mapped_column(pg_enum(EndReason, "end_reason"))
    failure_reason: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    recording_path: Mapped[str | None] = mapped_column(Text)
    transcript: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    claimed_by: Mapped[str | None] = mapped_column(Text)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        ForeignKeyConstraint(
            ["agent_version_id", "agent_id"], ["agent_versions.id", "agent_versions.agent_id"]
        ),
        ForeignKeyConstraint(
            ["persona_version_id", "persona_id"],
            ["persona_versions.id", "persona_versions.persona_id"],
        ),
        Index("ix_conversations_agent_created", "agent_id", text("created_at DESC")),
        Index("ix_conversations_status_created", "status", "created_at"),
    )


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


class PhoneNumber(Base):
    """A number on the Plivo account; when enabled, leased to one conversation at a time and
    rotated by last use."""

    __tablename__ = "phone_numbers"

    number: Mapped[str] = mapped_column(Text, primary_key=True)
    alias: Mapped[str | None] = mapped_column(Text)
    region: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("conversations.id"))
    leased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
