from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel

from yaksh.domain.numbers import Owner


class NumberState(StrEnum):
    IN_USE = "in_use"
    RESTING = "resting"
    """Released within the number rest in Settings; no new outbound test uses it yet."""
    READY = "ready"


class PhoneNumberRead(BaseModel):
    number: str
    alias: str | None
    region: str | None
    owner: Owner
    application_id: str | None
    application_name: str | None
    state: NumberState | None
    """A test number's state; None for every other number."""
    rests_until: datetime | None
    """When a resting test number may take an outbound test again."""


class PhoneNumbers(BaseModel):
    items: list[PhoneNumberRead]
    """Every number of the phone account, as the last check found it."""
    application_id: str | None
    """The receiving application: its numbers are the test numbers."""
    refreshed_at: datetime | None
    """When Yaksh last read the account's numbers from Plivo."""
    refresh_error: str | None
    """Why the last read failed; the numbers before it stand."""
    problem: str | None
    """Why no test can get a number now; None when one can."""
    outbound_problem: str | None
    """Why an outbound test could not get its call now; None when it could."""
    rest_s: int
    """How long a released number rests before an outbound test may use it."""


class ApplicationRead(BaseModel):
    id: str
    name: str | None
    answer_url: str | None
    problems: list[str]
    """Why the application does not send calls to this install; empty when it does."""


class PhoneAccountRead(BaseModel):
    provider: str
    credentials_saved: bool
    application: ApplicationRead | None
    test_numbers: int


class ApplicationChoice(BaseModel):
    application_id: str
