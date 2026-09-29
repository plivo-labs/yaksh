from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

E164 = Annotated[str, StringConstraints(pattern=r"^\+[1-9]\d{6,14}$")]


class AccountNumber(BaseModel):
    """A number on the Plivo account, as its Number API lists it."""

    model_config = ConfigDict(frozen=True)

    number: E164
    alias: str | None = None
    region: str | None = None
    voice: bool = True
