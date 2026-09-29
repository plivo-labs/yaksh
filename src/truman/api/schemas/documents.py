import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DocumentSummary(BaseModel):
    """A document without its text, for lists and upload results."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    media_type: str | None
    """None for pasted text, which has no file."""
    size_bytes: int | None
    characters: int
    pages: int | None
    empty_pages: int | None
    """PDF pages with no text layer, such as scanned pages."""
    created_at: datetime


class DocumentRead(DocumentSummary):
    text: str
