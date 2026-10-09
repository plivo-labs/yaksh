import hashlib
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from yaksha.db.models import Document
from yaksha.domain.documents import (
    MAX_FILE_BYTES,
    TextDocumentCreate,
    document_name,
    file_type,
)
from yaksha.domain.errors import NotFoundError, ValidationError
from yaksha.domain.files import FileStore
from yaksha.simulation.extraction import extract_file


async def create_file_document(
    session: AsyncSession, store: FileStore, name: str, data: bytes
) -> Document:
    """Keep the original under its content hash, then record its text. A failure between
    the two leaves an unused object, never a document without its file."""
    try:
        name = document_name(name)
    except ValueError as error:
        raise ValidationError(f"file name: {error}") from error
    kind = file_type(name)
    if kind is None:
        raise ValidationError("only PDF, TXT and MD files are supported")
    if len(data) > MAX_FILE_BYTES:
        raise ValidationError(f"the file is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB")
    extracted = await extract_file(kind, data)
    sha256 = hashlib.sha256(data).hexdigest()
    storage_key = f"documents/{sha256}"
    await store.put(storage_key, data, kind.value)
    document = Document(
        name=name,
        media_type=kind.value,
        size_bytes=len(data),
        sha256=sha256,
        storage_key=storage_key,
        text=extracted.text,
        characters=len(extracted.text),
        pages=extracted.pages,
        empty_pages=extracted.empty_pages,
    )
    session.add(document)
    await session.commit()
    return document


async def create_text_document(session: AsyncSession, command: TextDocumentCreate) -> Document:
    document = Document(name=command.name, text=command.text, characters=len(command.text))
    session.add(document)
    await session.commit()
    return document


async def get_document(session: AsyncSession, document_id: uuid.UUID) -> Document:
    document = await session.get(Document, document_id)
    if document is None:
        raise NotFoundError("document not found")
    return document


@dataclass(frozen=True)
class OpenedFile:
    """A document's original, with its first chunk already fetched so a storage failure is
    reported before a download starts. close() releases the storage stream however the
    download ends."""

    document: Document
    first: bytes
    rest: AsyncGenerator[bytes]

    async def chunks(self) -> AsyncGenerator[bytes]:
        yield self.first
        async for chunk in self.rest:
            yield chunk

    async def close(self) -> None:
        await self.rest.aclose()


async def open_file(session: AsyncSession, store: FileStore, document_id: uuid.UUID) -> OpenedFile:
    document = await get_document(session, document_id)
    if document.storage_key is None:
        raise NotFoundError("the document was pasted as text and has no file")
    rest = store.stream(document.storage_key)
    return OpenedFile(document, await anext(rest, b""), rest)
