from enum import StrEnum

from pydantic import BaseModel


class NumberState(StrEnum):
    IN_USE = "in_use"
    RESTING = "resting"
    """Released less than TRUMAN_NUMBER_REST_S ago; no new outbound test uses it yet."""
    FREE = "free"


class PhoneNumberRead(BaseModel):
    number: str
    alias: str | None
    region: str | None
    application_id: str | None
    application_name: str | None
    on_outbound_application: bool
    """Linked to TRUMAN_PLIVO_APP_ID. The worker also checks that application's URLs before it
    runs outbound tests; its log says why when it does not."""
    state: NumberState


class PhoneNumbers(BaseModel):
    items: list[PhoneNumberRead]
    outbound_application_id: str | None
    """TRUMAN_PLIVO_APP_ID; outbound tests are off without it."""
