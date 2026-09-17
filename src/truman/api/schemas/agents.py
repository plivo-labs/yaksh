import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from truman.domain.agents import AgentChange, AgentConfig, Direction, Transport, Trigger


class AgentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    external_id: str | None
    direction: Direction
    transport: Transport
    agent_number: str
    outbound_numbers: list[str]
    trigger: Trigger | None
    agent_speaks_first: bool
    brief: str | None
    current_version: int
    created_at: datetime
    updated_at: datetime


class AgentVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agent_id: uuid.UUID
    version: int
    change: AgentChange
    config: AgentConfig
    created_at: datetime
