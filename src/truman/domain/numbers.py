from pydantic import BaseModel, ConfigDict

from truman.domain.agents import E164


class AccountNumber(BaseModel):
    """A number on the Plivo account, as its Number API lists it."""

    model_config = ConfigDict(frozen=True)

    number: E164
    alias: str | None = None
    region: str | None = None
    voice: bool = True
