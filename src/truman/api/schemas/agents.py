import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from truman.domain.agents import AgentConfig, Direction, Transport
from truman.domain.languages import Language
from truman.domain.triggers import OutboundConfig


class AgentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    external_id: str | None
    direction: Direction
    transport: Transport
    agent_number: str | None
    outbound: OutboundConfig | None
    agent_speaks_first: bool
    language: Language
    brief: str | None
    current_version: int
    created_at: datetime
    updated_at: datetime


class AgentVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agent_id: uuid.UUID
    version: int
    config: AgentConfig
    created_at: datetime
