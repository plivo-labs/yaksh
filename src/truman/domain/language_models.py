from dataclasses import dataclass
from typing import Any, Protocol

from truman.domain.errors import UnavailableError


@dataclass(frozen=True)
class ModelAnswer:
    data: dict[str, Any]
    model: str
    """The model that answered, as the provider named it."""
    input_tokens: int | None
    output_tokens: int | None


class ModelCallError(UnavailableError):
    """A model call that gave no usable answer. A temporary failure, such as a timeout or a
    rate limit, can succeed when it is tried again later; a refusal or a rejected request
    cannot."""

    def __init__(self, message: str, *, temporary: bool) -> None:
        super().__init__(message)
        self.temporary = temporary


class JsonModel(Protocol):
    """A language model that answers with one JSON object matching a strict schema."""

    async def complete_json(
        self, *, system: str, user: str, name: str, schema: dict[str, Any]
    ) -> ModelAnswer: ...

    async def close(self) -> None: ...
