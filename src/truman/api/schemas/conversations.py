import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from truman.domain.conversations import (
    Channel,
    ConversationStatus,
    EndReason,
    Turn,
    Validity,
    WireEvent,
)


class ConversationSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agent_id: uuid.UUID
    agent_version_id: uuid.UUID
    agent_version: int
    channel: Channel
    persona_prompt: str
    caller_number: str
    max_duration_s: int
    status: ConversationStatus
    end_reason: EndReason | None
    failure_reason: str | None
    started_at: datetime | None
    ended_at: datetime | None
    duration_ms: int | None
    recording_url: str | None
    created_at: datetime


class ConversationRead(ConversationSummary):
    transcript: list[Turn]
    wire_events: list[WireEvent]
    validity: Validity | None
