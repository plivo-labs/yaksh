"""The agent's own record of one call, as its provider stored it, and the reader that finds it.

The record says what the agent heard, the values it saved and the tools it called. Every
provider's record is read into the same shape, so nothing past the reader knows the provider.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from yaksh.domain.agents import Direction
from yaksh.domain.conversations import Role
from yaksh.domain.record_sources import RecordProvider, RecordSource

MAX_TURNS = 500
MAX_TEXT_CHARS = 4000
MAX_VALUE_CHARS = 2000


def clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else f"{text[: limit - 1]}…"


class RecordTurn(BaseModel):
    """One line of the call as the agent recorded it: its own words, or what its
    speech-to-text heard from the caller."""

    model_config = ConfigDict(frozen=True)

    role: Role
    text: str
    at: datetime | None = None


class SavedValue(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    value: str
    """Text as the provider gave it; a value of another type as JSON."""


class RecordTool(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    arguments: str
    output: str | None = None
    failed: bool = False
    at: datetime | None = None


class AgentRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: RecordProvider
    external_id: str
    """The record's ID at its provider."""
    status: str
    """The provider's own word for the state of the call."""
    complete: bool
    """The provider says the record is final."""
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
    """What Yaksh keeps of a call's record: the record, or why there is none."""

    model_config = ConfigDict(frozen=True)

    state: RecordState
    record: AgentRecord | None = None
    reason: str | None = None
    """Why there is no record; or, for a found one, why it can be incomplete."""


@dataclass(frozen=True)
class CallRef:
    """What a reader knows of a test call to find the agent's record of it."""

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
