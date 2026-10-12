import uuid
from collections import Counter
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

MAX_FORKS = 5


class ForkRequest(BaseModel):
    """What the forks of a scenario or a persona change, and how many to write."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    instruction: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)
    ]
    count: int = Field(ge=1, le=MAX_FORKS)


class ScenarioFork(BaseModel):
    """The data sets a fork of a scenario keeps; None keeps them all."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    data_set_ids: list[uuid.UUID] | None = Field(default=None, min_length=1)

    @field_validator("data_set_ids")
    @classmethod
    def each_data_set_once(cls, ids: list[uuid.UUID] | None) -> list[uuid.UUID] | None:
        repeated = [item for item, n in Counter(ids or []).items() if n > 1]
        if repeated:
            raise ValueError(f"data set {repeated[0]} is listed more than once")
        return ids


class ScenarioForkRequest(ForkRequest, ScenarioFork):
    """Forks written from a scenario, each with the data sets it keeps."""
