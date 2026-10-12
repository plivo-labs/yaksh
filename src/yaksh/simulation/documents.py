import hashlib
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from yaksh.db.models import Document
from yaksh.domain.documents import (
    MAX_FILE_BYTES,
    TextDocumentCreate,
    document_name,
    file_type,
)
from yaksh.domain.errors import NotFoundError, ValidationError
from yaksh.domain.files import FileStore
from yaksh.simulation.extraction import extract_file
from yaksh.simulation.files import OpenedFile, open_file


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


async def open_original(
    session: AsyncSession, store: FileStore, document_id: uuid.UUID
) -> tuple[Document, OpenedFile]:
    document = await get_document(session, document_id)
    if document.storage_key is None:
        raise NotFoundError("the document was pasted as text and has no file")
    return document, await open_file(store, document.storage_key)
