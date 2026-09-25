from enum import StrEnum
from typing import Annotated, Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationInfo,
    field_validator,
)


class Direction(StrEnum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class Transport(StrEnum):
    """How Truman reaches an agent; phone only today, kept as the seam for other ways."""

    PHONE = "phone"


E164 = Annotated[str, StringConstraints(pattern=r"^\+[1-9]\d{6,14}$")]


class AgentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    direction: Direction = Direction.INBOUND
    transport: Transport = Transport.PHONE
    agent_number: E164
    agent_speaks_first: bool = True
    brief: str | None = None


class AgentCreate(AgentConfig):
    name: str = Field(min_length=1)
    external_id: str | None = None

    def config(self) -> AgentConfig:
        return AgentConfig.model_validate(self.model_dump(exclude={"name", "external_id"}))


class AgentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str | None = Field(default=None, min_length=1)
    external_id: str | None = None
    direction: Direction | None = None
    transport: Transport | None = None
    agent_number: E164 | None = None
    agent_speaks_first: bool | None = None
    brief: str | None = None

    @field_validator("name", "agent_number")
    @classmethod
    def cannot_be_cleared(cls, value: str | None, info: ValidationInfo) -> str | None:
        if value is None:
            raise ValueError(f"{info.field_name} cannot be null")
        return value

    def changes(self) -> dict[str, Any]:
        return self.model_dump(exclude_unset=True)
