from enum import StrEnum
from typing import Annotated, Protocol

from pydantic import BaseModel, ConfigDict, StringConstraints

E164 = Annotated[str, StringConstraints(pattern=r"^\+[1-9]\d{6,14}$")]


class AccountNumber(BaseModel):
    """A number on the Plivo account, as its Number API lists it."""

    model_config = ConfigDict(frozen=True)

    number: E164
    alias: str | None = None
    region: str | None = None
    voice: bool = True
    application_id: str | None = None


class PlivoApplication(BaseModel):
    """The Plivo Application that receives the calls to the numbers linked to it."""

    model_config = ConfigDict(frozen=True)

    app_id: str
    name: str
    answer_url: str
    answer_method: str
    hangup_url: str
    hangup_method: str

    def problems(self, public_url: str) -> list[str]:
        """Why this Application cannot send test calls to a worker at public_url; empty when
        it can."""
        answer_url, hangup_url = receiving_urls(public_url)
        expected = {
            "answer URL": (self.answer_url, answer_url),
            "hangup URL": (self.hangup_url, hangup_url),
            "answer method": (self.answer_method.upper(), "POST"),
            "hangup method": (self.hangup_method.upper(), "POST"),
        }
        return [
            f"Plivo application {self.name} has {label} {actual!r}; set it to {wanted!r}"
            for label, (actual, wanted) in expected.items()
            if actual != wanted
        ]


def receiving_urls(public_url: str) -> tuple[str, str]:
    """The answer and hangup URLs of an application that sends calls to a worker at
    public_url."""
    base = public_url.rstrip("/")
    return f"{base}/incoming", f"{base}/incoming/hangup"


CX_AGENT_PREFIX = "agent_flow_"
"""Plivo names the application of a Plivo CX agent's number with this prefix."""


class Owner(StrEnum):
    """Who receives the calls of a number on the account."""

    TEST = "test"
    """The receiving application in the settings: a test number."""
    FREE = "free"
    """No application."""
    CX_AGENT = "cx_agent"
    OTHER = "other"
    """Another application, such as another Yaksh install."""
    NO_VOICE = "no_voice"
    """The number cannot take calls."""


def owner(
    application_id: str | None,
    application_name: str | None,
    voice: bool,
    receiving_app_id: str | None,
) -> Owner:
    if not voice:
        return Owner.NO_VOICE
    if application_id is None:
        return Owner.FREE
    if application_id == receiving_app_id:
        return Owner.TEST
    if (application_name or "").startswith(CX_AGENT_PREFIX):
        return Owner.CX_AGENT
    return Owner.OTHER


class PhoneAccountApi(Protocol):
    """What Yaksh reads and changes on the phone account: its numbers and the application
    that receives their calls."""

    async def list_numbers(self) -> list[AccountNumber]: ...

    async def get_application(self, app_id: str) -> PlivoApplication: ...

    async def list_applications(self) -> list[PlivoApplication]: ...

    async def create_application(self, name: str, answer_url: str, hangup_url: str) -> str: ...

    async def update_application(self, app_id: str, answer_url: str, hangup_url: str) -> None: ...

    async def link_number(self, number: str, app_id: str | None) -> None:
        """Link the number to the application, or to none."""
        ...
