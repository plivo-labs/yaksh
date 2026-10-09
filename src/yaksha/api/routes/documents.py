import uuid
from urllib.parse import quote

from fastapi import APIRouter, Depends, UploadFile, status
from fastapi.responses import StreamingResponse

from yaksha.api.auth import require_token
from yaksha.api.deps import FileStoreDep, SessionDep
from yaksha.api.errors import UNAVAILABLE
from yaksha.api.files import StoredFileResponse
from yaksha.api.schemas.documents import DocumentRead, DocumentSummary
from yaksha.domain.documents import MAX_FILE_BYTES, TextDocumentCreate
from yaksha.simulation import documents

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
    document, opened = await documents.open_original(session, store, document_id)
    return StoredFileResponse(
        opened,
        document.media_type,
        {
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(document.name)}",
            "Content-Length": str(document.size_bytes),
        },
    )
