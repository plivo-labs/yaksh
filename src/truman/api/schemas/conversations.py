import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from truman.domain.agents import Direction
from truman.domain.conversations import (
    CallerClaim,
    Channel,
    ConversationStatus,
    EndReason,
    Turn,
    Validity,
    WireEvent,
)
from truman.domain.languages import Language
from truman.domain.scenarios import ScenarioConfig


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
    scenario_id: uuid.UUID
    scenario_version_id: uuid.UUID
    scenario_version: int
    scenario_name: str
    direction: Direction
    language: Language
    channel: Channel
    caller_number: str | None
    agent_caller_id: str | None
    call_uuid: str | None
    max_duration_s: int
    status: ConversationStatus
    end_reason: EndReason | None
    failure_reason: str | None
    started_at: datetime | None
    ended_at: datetime | None
    talk_ms: int | None
    recording_url: str | None
    caller_claim: CallerClaim | None
    run_id: uuid.UUID | None
    repeat: int | None
    attempt: int
    retry_of: uuid.UUID | None
    created_at: datetime


class ConversationRead(ConversationSummary):
    instructions: str
    scenario: ScenarioConfig
    transcript: list[Turn]
    wire_events: list[WireEvent]
    validity: Validity | None
    retried_as: uuid.UUID | None
