import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from truman.db.base import Base
from truman.domain.agents import AgentChange, Direction, Transport
from truman.domain.conversations import Channel, ConversationStatus, EndReason


def pg_enum[E: StrEnum](enum: type[E], name: str) -> Enum:
    return Enum(enum, name=name, values_callable=lambda e: [member.value for member in e])


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(Text)
    external_id: Mapped[str | None] = mapped_column(Text)
    direction: Mapped[Direction] = mapped_column(pg_enum(Direction, "agent_direction"))
    transport: Mapped[Transport] = mapped_column(pg_enum(Transport, "agent_transport"))
    websocket_url: Mapped[str | None] = mapped_column(Text)
    upgrade_headers: Mapped[dict[str, str]] = mapped_column(JSONB, default=dict)
    extra_headers: Mapped[dict[str, str]] = mapped_column(JSONB, default=dict)
    agent_number: Mapped[str | None] = mapped_column(Text)
    outbound_numbers: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    trigger: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    agent_speaks_first: Mapped[bool] = mapped_column(Boolean, default=True)
    brief: Mapped[str | None] = mapped_column(Text)
    current_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "transport <> 'plivo_websocket' OR websocket_url IS NOT NULL",
            name="websocket_url_required",
        ),
        Index(
            "ix_agents_external_id_live",
            "external_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )


class AgentVersion(Base):
    __tablename__ = "agent_versions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agents.id"))
    version: Mapped[int] = mapped_column(Integer)
    change: Mapped[AgentChange] = mapped_column(pg_enum(AgentChange, "agent_change"))
    label: Mapped[str | None] = mapped_column(Text)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("agent_id", "version"),
        UniqueConstraint("id", "agent_id"),
    )


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agents.id"))
    agent_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    channel: Mapped[Channel] = mapped_column(pg_enum(Channel, "channel"), default=Channel.VOICE)
    persona_prompt: Mapped[str] = mapped_column(Text)
    caller_number: Mapped[str] = mapped_column(Text)
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
        Index("ix_conversations_agent_created", "agent_id", text("created_at DESC")),
        Index("ix_conversations_status_created", "status", "created_at"),
    )
