import hashlib
import io
from collections.abc import AsyncIterator

import pytest
from httpx import AsyncClient

from tests.conftest import FakeFileStore
from truman.api.app import MAX_REQUEST_BYTES
from truman.domain.documents import MAX_FILE_BYTES, MAX_NAME_CHARS, MAX_TEXT_CHARS
from truman.simulation import extraction


def pdf(*pages: str) -> bytes:
    """A minimal PDF with one page per string; an empty string makes a page with no text."""
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    kids = []
    for text in pages:
        stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET" if text else ""
        objects.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
        objects.append(
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]"
            f" /Resources << /Font << /F1 3 0 R >> >> /Contents {len(objects)} 0 R >>"
        )
        kids.append(f"{len(objects)} 0 R")
    objects[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>"
    out = io.BytesIO(b"%PDF-1.4\n")
    out.seek(0, io.SEEK_END)
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(out.tell())
        out.write(f"{number} 0 obj\n{body}\nendobj\n".encode())
    xref = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets:
        out.write(f"{offset:010d} 00000 n \n".encode())
    out.write(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return out.getvalue()


async def upload(client: AsyncClient, name: str, data: bytes) -> dict:
    response = await client.post("/api/v1/documents/upload", files={"file": (name, data)})
    return {"status": response.status_code, **response.json()}


async def test_an_uploaded_pdf_keeps_its_file_and_its_text(
    client: AsyncClient, file_store: FakeFileStore
) -> None:
    data = pdf("Clinic hours are 9 to 5.", "", "Walk-ins are welcome.")

    uploaded = await upload(client, "Clinic hours.pdf", data)
    read = (await client.get(f"/api/v1/documents/{uploaded['id']}")).json()
    download = await client.get(f"/api/v1/documents/{uploaded['id']}/file")

    assert uploaded["status"] == 201
    assert (uploaded["name"], uploaded["media_type"]) == ("Clinic hours.pdf", "application/pdf")
    assert (uploaded["pages"], uploaded["empty_pages"]) == (3, 1)
    assert read["text"] == "Clinic hours are 9 to 5.\n\nWalk-ins are welcome."
    assert uploaded["characters"] == len(read["text"])
    assert download.content == data and download.headers["content-type"] == "application/pdf"
    assert download.headers["content-disposition"] == (
        "attachment; filename*=UTF-8''Clinic%20hours.pdf"
    )
    assert list(file_store.files) == [f"documents/{hashlib.sha256(data).hexdigest()}"]


async def test_text_files_are_read_as_utf8_and_the_same_file_is_stored_once(
    client: AsyncClient, file_store: FakeFileStore
) -> None:
    data = "﻿# Refunds\n\nWithin 30 days, with a receipt.\n".encode()

    first = await upload(client, "refunds.md", data)
    second = await upload(client, "Refund policy.md", data)
    text = (await client.get(f"/api/v1/documents/{second['id']}")).json()["text"]

    assert first["id"] != second["id"]
    assert first["media_type"] == second["media_type"] == "text/markdown"
    assert text == "# Refunds\n\nWithin 30 days, with a receipt.\n"
    assert len(file_store.files) == 1


@pytest.mark.parametrize(
    ("name", "data", "message"),
    [
        ("notes.docx", b"PK\x03\x04", "only PDF, TXT and MD files are supported"),
        ("scan.pdf", pdf("", ""), "this PDF has no text; scanned PDFs are not supported"),
        ("fake.pdf", b"hello", "the file is not a PDF"),
        ("broken.pdf", b"%PDF-1.4\ngarbage", "the PDF could not be read"),
        ("latin.txt", "café".encode("latin-1"), "the file is not UTF-8 text"),
        ("blank.txt", b"  \n\x00 ", "the file has no text"),
        ("big.txt", b"a" * (MAX_FILE_BYTES + 1), "the file is larger than 20 MB"),
        ("long.pdf", pdf("a" * (MAX_TEXT_CHARS + 1)), "the file has more than 1,000,000"),
        ("n" * MAX_NAME_CHARS + ".txt", b"hi", "file name: the name is longer than 200"),
    ],
    ids=[
        "docx",
        "scanned",
        "not a pdf",
        "broken pdf",
        "not utf-8",
        "blank",
        "too large",
        "too much text",
        "long name",
    ],
)
async def test_files_truman_cannot_read_are_refused_and_not_stored(
    client: AsyncClient, file_store: FakeFileStore, name: str, data: bytes, message: str
) -> None:
    refused = await upload(client, name, data)

    assert refused["status"] == 422
    assert refused["error"]["message"].startswith(message)
    assert file_store.files == {}


async def test_pasted_text_is_a_document_without_a_file(client: AsyncClient) -> None:
    created = await client.post(
        "/api/v1/documents", json={"name": " F\u0000A\nQ ", "text": "Open\u0000 on Sundays."}
    )
    document_id = created.json()["id"]
    read = (await client.get(f"/api/v1/documents/{document_id}")).json()
    download = await client.get(f"/api/v1/documents/{document_id}/file")
    too_long = await client.post(
        "/api/v1/documents", json={"name": "Long", "text": "a" * (MAX_TEXT_CHARS + 1)}
    )

    assert created.status_code == 201
    assert (read["name"], read["text"], read["media_type"]) == ("FAQ", "Open on Sundays.", None)
    assert download.status_code == 404
    assert download.json()["error"]["message"] == "the document was pasted as text and has no file"
    assert too_long.status_code == 422


async def test_an_upload_fails_whole_when_storage_is_down(
    client: AsyncClient, file_store: FakeFileStore
) -> None:
    file_store.down = True

    refused = await upload(client, "hours.txt", b"9 to 5")

    assert refused["status"] == 503
    assert refused["error"]["message"] == "file storage refused the upload"


async def test_a_storage_failure_is_reported_before_a_download_starts(
    client: AsyncClient, file_store: FakeFileStore
) -> None:
    uploaded = await upload(client, "hours.txt", b"9 to 5")
    file_store.down = True

    download = await client.get(f"/api/v1/documents/{uploaded['id']}/file")

    assert download.status_code == 503
    assert download.json()["error"]["message"] == "file storage could not return the file"


async def test_an_oversized_body_is_refused_before_the_token_is_checked(
    client: AsyncClient,
) -> None:
    body = b"a" * (MAX_REQUEST_BYTES + 1)

    async def chunked() -> AsyncIterator[bytes]:
        for start in range(0, len(body), 1024 * 1024):
            yield body[start : start + 1024 * 1024]

    declared = await client.post(
        "/api/v1/documents/upload", content=body, headers={"Authorization": ""}
    )
    streamed = await client.post("/api/v1/documents", content=chunked())

    assert declared.status_code == streamed.status_code == 413
    assert declared.json()["error"]["message"] == "the request body is larger than 21 MB"


async def test_a_pdf_that_takes_too_long_to_read_is_refused(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(extraction, "PDF_DEADLINE_S", 0.001)

    refused = await upload(client, "slow.pdf", pdf("Clinic hours."))

    assert refused["status"] == 422
    assert refused["error"]["message"] == "the PDF took too long to read"
