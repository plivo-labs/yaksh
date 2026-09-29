from typing import Any, Protocol


class JsonModel(Protocol):
    """A language model that answers with one JSON object matching a strict schema."""

    async def complete_json(
        self, *, system: str, user: str, name: str, schema: dict[str, Any]
    ) -> dict[str, Any]: ...

    async def close(self) -> None: ...
