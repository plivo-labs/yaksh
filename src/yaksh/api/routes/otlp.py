"""The endpoint that receives agents' traces: OTLP over HTTP with protobuf, the format that the
OTel exporters send by default. It keeps the spans and links nothing: the evaluator links a
trace to its call after the call."""

import asyncio
import zlib

from fastapi import APIRouter, HTTPException, Request, Response, status
from google.protobuf.message import DecodeError
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTracePartialSuccess,
    ExportTraceServiceRequest,
    ExportTraceServiceResponse,
)

from yaksh.api.auth import TraceTokenDep
from yaksh.api.deps import SessionDep
from yaksh.domain.traces import MAX_SPANS, sort_spans, span_count
from yaksh.evaluation import trace_store

PROTOBUF = "application/x-protobuf"
MAX_BODY_BYTES = 8 * 1024 * 1024
"""Below the 21 MB that the app accepts on any route, which an upload needs."""
MAX_UNZIPPED_BYTES = 32 * 1024 * 1024
READ_BODY_S = 30.0
"""An exporter stops a send after 10 s by default; a slower upload only holds memory."""

router = APIRouter(prefix="/otlp", tags=["traces"])


@router.post("/v1/traces", include_in_schema=False)
async def export_traces(request: Request, token: TraceTokenDep, session: SessionDep) -> Response:
    if media_type(request.headers.get("content-type")) != PROTOBUF:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, f"send OTLP as {PROTOBUF}")
    encoding = (request.headers.get("content-encoding") or "identity").strip().lower()
    if encoding not in ("identity", "gzip"):
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "send gzip or no compression")
    body = await read_body(request)
    if encoding == "gzip":
        body = gunzip(body)
    try:
        export = ExportTraceServiceRequest.FromString(body)
    except DecodeError:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "the body is not an OTLP trace export"
        ) from None
    if span_count(export) > MAX_SPANS:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE, f"send {MAX_SPANS} spans or fewer in one request"
        )
    found = sort_spans(export, await request.app.state.yaksh_numbers.get(session))
    await trace_store.store_spans(session, token, found.kept)
    answer = ExportTraceServiceResponse()
    if found.rejected:
        answer.partial_success.CopyFrom(
            ExportTracePartialSuccess(
                rejected_spans=found.rejected, error_message="; ".join(found.reasons)
            )
        )
    return Response(answer.SerializeToString(), media_type=PROTOBUF)


def media_type(content_type: str | None) -> str:
    return (content_type or "").split(";")[0].strip().lower()


async def read_body(request: Request) -> bytes:
    too_large = HTTPException(
        status.HTTP_413_CONTENT_TOO_LARGE,
        f"the request body is larger than {MAX_BODY_BYTES // (1024 * 1024)} MB",
    )
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise too_large
    chunks, size = [], 0
    try:
        async with asyncio.timeout(READ_BODY_S):
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_BODY_BYTES:
                    raise too_large
                chunks.append(chunk)
    except TimeoutError:
        raise HTTPException(
            status.HTTP_408_REQUEST_TIMEOUT, f"send the body within {READ_BODY_S:.0f} s"
        ) from None
    return b"".join(chunks)


def gunzip(body: bytes) -> bytes:
    unzip = zlib.decompressobj(16 + zlib.MAX_WBITS)
    try:
        data = unzip.decompress(body, MAX_UNZIPPED_BYTES + 1)
    except zlib.error:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "the gzip body is broken") from None
    if len(data) > MAX_UNZIPPED_BYTES:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            f"the body is larger than {MAX_UNZIPPED_BYTES // (1024 * 1024)} MB after unzipping",
        )
    if not unzip.eof:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "the gzip body is cut short")
    return data
