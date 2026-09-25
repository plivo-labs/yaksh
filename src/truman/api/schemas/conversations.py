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
from truman.domain.personas import Language


class ConversationSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agent_id: uuid.UUID
    agent_version_id: uuid.UUID
    agent_version: int
    agent_name: str
    persona_id: uuid.UUID
    persona_version_id: uuid.UUID
    persona_version: int
    persona_name: str
    goal: str
    language: Language
    channel: Channel
    caller_number: str | None
    call_uuid: str | None
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
    instructions: str
    transcript: list[Turn]
    wire_events: list[WireEvent]
    validity: Validity | None
