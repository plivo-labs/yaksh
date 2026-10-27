"""Every provider's record is read into these shapes, so nothing past the reader knows the
provider."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Protocol

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from yaksh.domain.agents import Direction, without_nul
from yaksh.domain.conversations import Role
from yaksh.domain.record_sources import RecordProvider, RecordSource

MAX_TURNS = 500
MAX_TEXT_CHARS = 4000
MAX_VALUE_CHARS = 2000


RecordText = Annotated[str, AfterValidator(without_nul)]


def clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else f"{text[: limit - 1]}…"


class RecordTurn(BaseModel):
    model_config = ConfigDict(frozen=True)

    role: Role
    text: RecordText
    at: datetime | None = None
    """When the provider logged the line: for Plivo CX, when its speech ended."""
    started_at: datetime | None = None
    """When its speech started, if the provider logs it."""


class SavedValue(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: RecordText
    value: RecordText
    """Text as the provider gave it; a value of another type as JSON."""


class RecordTool(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: RecordText
    arguments: RecordText
    output: RecordText | None = None
    failed: bool = False
    at: datetime | None = None


class AgentRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: RecordProvider
    external_id: RecordText
    status: RecordText
    """The provider's own word for the state of the call."""
    complete: bool
    """The provider has finished writing the record."""
    turns: list[RecordTurn] = Field(default_factory=list)
    saved: list[SavedValue] = Field(default_factory=list)
    tools: list[RecordTool] = Field(default_factory=list)


class RecordState(StrEnum):
    FOUND = "found"
    MISSING = "missing"


class RecordStatus(StrEnum):
    """Where a call's agent record is, as the console shows it."""

    WAITING = "waiting"
    FOUND = "found"
    MISSING = "missing"


class StoredRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    state: RecordState
    record: AgentRecord | None = None
    reason: str | None = None
    """Why there is no record; or, for a found one, why it can be incomplete."""


@dataclass(frozen=True)
class CallRef:
    direction: Direction
    yaksh_number: str
    started_at: datetime
    """When Yaksh started the conversation, before it dialed or sent the trigger."""
    connected_at: datetime
    ended_at: datetime
    trigger_response: str | None
    """The body of the trigger's response, for an outbound call."""


@dataclass(frozen=True)
class Found:
    record: AgentRecord


@dataclass(frozen=True)
class Pending:
    """No final record yet: the provider is still writing it, or could not answer now."""

    reason: str
    partial: AgentRecord | None = None
    retry_after_s: float | None = None


@dataclass(frozen=True)
class Missing:
    """There is no record to read, and waiting does not change that."""

    reason: str


type Lookup = Found | Pending | Missing


class RecordReader(Protocol):
    async def find(
        self, source: RecordSource, headers: Mapping[str, str], call: CallRef
    ) -> Lookup: ...
