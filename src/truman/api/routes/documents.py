import uuid
from urllib.parse import quote

from fastapi import APIRouter, Depends, UploadFile, status
from fastapi.responses import StreamingResponse
from starlette.types import Receive, Scope, Send

from truman.api.auth import require_token
from truman.api.deps import FileStoreDep, SessionDep
from truman.api.errors import UNAVAILABLE
from truman.api.schemas.documents import DocumentRead, DocumentSummary
from truman.domain.documents import MAX_FILE_BYTES, TextDocumentCreate
from truman.simulation import documents
from truman.simulation.documents import OpenedFile


class DocumentFileResponse(StreamingResponse):
    """Streams a document's original and always releases the storage stream: Starlette
    leaves an unfinished iterator to the garbage collector."""

    def __init__(self, opened: OpenedFile) -> None:
        document = opened.document
        super().__init__(
            opened.chunks(),
            media_type=document.media_type,
            headers={
                "Content-Disposition": f"attachment; filename*=UTF-8''{quote(document.name)}",
                "Content-Length": str(document.size_bytes),
            },
        )
        self._opened = opened

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            await self._opened.close()


router = APIRouter(prefix="/documents", tags=["documents"], dependencies=[Depends(require_token)])


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_text_document(command: TextDocumentCreate, session: SessionDep) -> DocumentSummary:
    """A document from pasted text."""
    return DocumentSummary.model_validate(await documents.create_text_document(session, command))


@router.post("/upload", status_code=status.HTTP_201_CREATED, responses=UNAVAILABLE)
async def upload_document(
    file: UploadFile, session: SessionDep, store: FileStoreDep
) -> DocumentSummary:
    """A document from a PDF, TXT or MD file. The file is kept and its text extracted."""
    data = await file.read(MAX_FILE_BYTES + 1)
    document = await documents.create_file_document(session, store, file.filename or "", data)
    return DocumentSummary.model_validate(document)


@router.get("/{document_id}")
async def get_document(document_id: uuid.UUID, session: SessionDep) -> DocumentRead:
    return DocumentRead.model_validate(await documents.get_document(session, document_id))


@router.get("/{document_id}/file", response_class=StreamingResponse, responses=UNAVAILABLE)
async def download_document(
    document_id: uuid.UUID, session: SessionDep, store: FileStoreDep
) -> StreamingResponse:
    return DocumentFileResponse(await documents.open_file(session, store, document_id))
