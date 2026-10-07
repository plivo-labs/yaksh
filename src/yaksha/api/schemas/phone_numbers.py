from enum import StrEnum

from pydantic import BaseModel


class NumberState(StrEnum):
    IN_USE = "in_use"
    RESTING = "resting"
    """Released within the number rest in Settings; no new outbound test uses it yet."""
    FREE = "free"


class PhoneNumberRead(BaseModel):
    number: str
    alias: str | None
    region: str | None
    application_id: str | None
    application_name: str | None
    on_outbound_application: bool
    """Linked to YAKSHA_PLIVO_APP_ID. The worker also checks that application's URLs before it
    runs outbound tests; its log says why when it does not."""
    state: NumberState


class PhoneNumbers(BaseModel):
    items: list[PhoneNumberRead]
    outbound_problem: str | None
    """Why an outbound test could not get its call now; None when it could."""
    rest_s: int
    """How long a released number rests before an outbound test may use it."""
