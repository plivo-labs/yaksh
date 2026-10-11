from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

MAX_FORKS = 5


class ForkRequest(BaseModel):
    """What the forks of a scenario or a persona change, and how many to write."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    instruction: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)
    ]
    count: int = Field(ge=1, le=MAX_FORKS)
