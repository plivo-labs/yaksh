from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import (
    AnyUrl,
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    StringConstraints,
    UrlConstraints,
    field_validator,
    model_validator,
)


class Direction(StrEnum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class Transport(StrEnum):
    PLIVO_WEBSOCKET = "plivo_websocket"
    PHONE = "phone"


class AgentChange(StrEnum):
    CREATED = "created"
    CHANGED = "changed"
    RESTORED = "restored"


E164 = Annotated[str, StringConstraints(pattern=r"^\+[1-9]\d{6,14}$")]
WebsocketUrl = Annotated[AnyUrl, UrlConstraints(allowed_schemes=["ws", "wss"])]
Headers = dict[str, str]


class Trigger(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    url: HttpUrl
    method: Literal["POST", "PUT"] = "POST"
    headers: Headers = Field(default_factory=dict)
    secret_env: str | None = None
    body: dict[str, Any] = Field(default_factory=dict)


class AgentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    direction: Direction = Direction.INBOUND
    transport: Transport = Transport.PLIVO_WEBSOCKET
    websocket_url: WebsocketUrl | None = None
    upgrade_headers: Headers = Field(default_factory=dict)
    extra_headers: Headers = Field(default_factory=dict)
    agent_number: E164 | None = None
    outbound_numbers: list[E164] = Field(default_factory=list)
    trigger: Trigger | None = None
    agent_speaks_first: bool = True
    brief: str | None = None

    @model_validator(mode="after")
    def address_required(self) -> "AgentConfig":
        if self.transport is Transport.PLIVO_WEBSOCKET and self.websocket_url is None:
            raise ValueError("websocket_url is required when transport is plivo_websocket")
        if self.transport is Transport.PHONE and self.agent_number is None:
            raise ValueError("agent_number is required when transport is phone")
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
    websocket_url: WebsocketUrl | None = None
    upgrade_headers: Headers | None = None
    extra_headers: Headers | None = None
    agent_number: E164 | None = None
    outbound_numbers: list[E164] | None = None
    trigger: Trigger | None = None
    agent_speaks_first: bool | None = None
    brief: str | None = None

    @field_validator("name")
    @classmethod
    def name_cannot_be_cleared(cls, value: str | None) -> str | None:
        if value is None:
            raise ValueError("name cannot be null")
        return value

    def changes(self) -> dict[str, Any]:
        return self.model_dump(exclude_unset=True)
