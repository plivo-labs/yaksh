from enum import StrEnum
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

from truman.domain.languages import Language
from truman.domain.numbers import E164
from truman.domain.triggers import OutboundConfig


class Direction(StrEnum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class Transport(StrEnum):
    """How Truman reaches an agent; phone only today, kept as the seam for other ways."""

    PHONE = "phone"


class AgentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    direction: Direction = Direction.INBOUND
    transport: Transport = Transport.PHONE
    agent_number: E164 | None = None
    """The number Truman dials; inbound agents only."""
    outbound: OutboundConfig | None = None
    agent_speaks_first: bool = True
    language: Language = Language.EN
    brief: str | None = None

    @model_validator(mode="after")
    def fits_direction(self) -> AgentConfig:
        if self.direction is Direction.INBOUND:
            if self.agent_number is None:
                raise ValueError("an inbound agent needs agent_number")
            if self.outbound is not None:
                raise ValueError("outbound settings are only for outbound agents")
        else:
            if self.outbound is None:
                raise ValueError("an outbound agent needs outbound settings with a trigger")
            if self.agent_number is not None:
                raise ValueError(
                    "an outbound agent has no agent_number; list the numbers it calls from "
                    "in outbound.calling_numbers"
                )
        return self


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
    outbound: OutboundConfig | None = None
    agent_speaks_first: bool | None = None
    language: Language | None = None
    brief: str | None = None

    @field_validator("name", "language")
    @classmethod
    def cannot_be_cleared(cls, value: str | None, info: ValidationInfo) -> str | None:
        if value is None:
            raise ValueError(f"{info.field_name} cannot be null")
        return value

    def changes(self) -> dict[str, Any]:
        return self.model_dump(exclude_unset=True)
