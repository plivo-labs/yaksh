"""Text from uploaded files. A PDF is parsed in a child process with a deadline and, where the
system allows, a memory cap: a hostile or broken PDF can take unbounded work, and a thread
cannot be stopped. Run as `python -m yaksha.simulation.extraction`, it reads a PDF on stdin
and writes the result as JSON."""

import asyncio
import contextlib
import io
import json
import resource
import sys
from dataclasses import asdict, dataclass

from pypdf import PdfReader

from yaksha.domain.documents import MAX_TEXT_CHARS, FileType, usable_text
from yaksha.domain.errors import ValidationError

PDF_DEADLINE_S = 60.0
PDF_MEMORY_BYTES = 1024 * 1024 * 1024


@dataclass(frozen=True)
class Extracted:
    text: str
    pages: int | None = None
    empty_pages: int | None = None


async def extract_file(kind: FileType, data: bytes) -> Extracted:
    extracted = await extract_pdf_in_child(data) if kind is FileType.PDF else extract_plain(data)
    try:
        text = usable_text(extracted.text)
    except ValueError as error:
        raise ValidationError("the file has no text") from error
    if len(text) > MAX_TEXT_CHARS:
        raise ValidationError(f"the file has more than {MAX_TEXT_CHARS:,} characters of text")
    return Extracted(text, extracted.pages, extracted.empty_pages)


def extract_plain(data: bytes) -> Extracted:
    try:
        return Extracted(data.decode("utf-8-sig"))
    except UnicodeDecodeError as error:
        raise ValidationError("the file is not UTF-8 text") from error


async def extract_pdf_in_child(data: bytes) -> Extracted:
    if not data.startswith(b"%PDF-"):
        raise ValidationError("the file is not a PDF")
    child = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        __name__,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        out, _ = await asyncio.wait_for(child.communicate(data), PDF_DEADLINE_S)
    except TimeoutError as error:
        raise ValidationError("the PDF took too long to read") from error
    finally:
        if child.returncode is None:
            child.kill()
            # A killed child's unread output keeps wait() from returning until it is drained.
            assert child.stdout is not None
            await child.stdout.read()
            await child.wait()
    if child.returncode != 0:
        raise ValidationError("the PDF could not be read")
    result = json.loads(out)
    if "error" in result:
        raise ValidationError(result["error"])
    return Extracted(**result)


def extract_pdf(data: bytes) -> Extracted:
    try:
        reader = PdfReader(io.BytesIO(data))
        locked = reader.is_encrypted and not reader.decrypt("")
        pages = [] if locked else pdf_pages(reader)
    except ValidationError:
        raise
    except Exception as error:  # an uploaded file: pypdf raises many types on malformed input
        raise ValidationError(f"the PDF could not be read: {error}") from error
    if locked:
        raise ValidationError("password-protected PDFs are not supported")
    text = "\n\n".join(page for page in pages if page)
    if not text:
        raise ValidationError("this PDF has no text; scanned PDFs are not supported")
    return Extracted(text, len(pages), sum(1 for page in pages if not page))


def pdf_pages(reader: PdfReader) -> list[str]:
    """Each page's text, stopping as soon as the total is over the limit."""
    pages: list[str] = []
    total = 0
    for page in reader.pages:
        pages.append((page.extract_text() or "").strip())
        total += len(pages[-1])
        if total > MAX_TEXT_CHARS:
            raise ValidationError(f"the file has more than {MAX_TEXT_CHARS:,} characters of text")
    return pages


def main() -> None:
    # macOS refuses an address-space limit; the deadline still applies there.
    with contextlib.suppress(ValueError, OSError):
        resource.setrlimit(resource.RLIMIT_AS, (PDF_MEMORY_BYTES, PDF_MEMORY_BYTES))
    try:
        result = asdict(extract_pdf(sys.stdin.buffer.read()))
    except ValidationError as error:
        result = {"error": str(error)}
    json.dump(result, sys.stdout)


if __name__ == "__main__":
    main()
