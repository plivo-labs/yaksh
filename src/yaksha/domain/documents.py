"""Documents: text Yaksha reads about an agent, from an uploaded file or pasted by the user.
A document never changes once created: agent versions and past conversations refer to it."""

import unicodedata
from collections.abc import AsyncGenerator
from enum import StrEnum
from pathlib import PurePath
from typing import Annotated, Protocol

from pydantic import AfterValidator, BaseModel, ConfigDict, StringConstraints

MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_TEXT_CHARS = 1_000_000
MAX_NAME_CHARS = 200


def usable_text(value: str) -> str:
    """Postgres text cannot hold NUL, so it is dropped."""
    value = value.replace("\x00", "")
    if not value.strip():
        raise ValueError("the text is empty")
    return value


def document_name(value: str) -> str:
    """A pasted document's name or an uploaded file's name, without control characters."""
    name = "".join(c for c in value if unicodedata.category(c) != "Cc").strip()
    if not name:
        raise ValueError("the name is empty")
    if len(name) > MAX_NAME_CHARS:
        raise ValueError(f"the name is longer than {MAX_NAME_CHARS} characters")
    return name


DocumentName = Annotated[str, AfterValidator(document_name)]
DocumentText = Annotated[
    str, StringConstraints(max_length=MAX_TEXT_CHARS), AfterValidator(usable_text)
]


class FileType(StrEnum):
    PDF = "application/pdf"
    TEXT = "text/plain"
    MARKDOWN = "text/markdown"


FILE_TYPES = {".pdf": FileType.PDF, ".txt": FileType.TEXT, ".md": FileType.MARKDOWN}


def file_type(file_name: str) -> FileType | None:
    return FILE_TYPES.get(PurePath(file_name).suffix.lower())


class TextDocumentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: DocumentName
    text: DocumentText


class FileStore(Protocol):
    """Keeps the original files. Keys are content hashes, so a put of the same bytes again
    changes nothing."""

    async def put(self, key: str, data: bytes, media_type: str) -> None: ...

    def stream(self, key: str) -> AsyncGenerator[bytes]: ...
