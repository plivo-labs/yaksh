from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException

from truman.domain.errors import ConflictError, NotFoundError, UnavailableError, ValidationError

REQUEST_PARTS = frozenset({"body", "query", "path", "header", "cookie"})

CODES = {
    status.HTTP_401_UNAUTHORIZED: "unauthorized",
    status.HTTP_404_NOT_FOUND: "not_found",
    status.HTTP_409_CONFLICT: "conflict",
    status.HTTP_413_CONTENT_TOO_LARGE: "too_large",
    status.HTTP_422_UNPROCESSABLE_CONTENT: "validation_error",
    status.HTTP_503_SERVICE_UNAVAILABLE: "unavailable",
}


class FieldError(BaseModel):
    loc: list[str | int]
    msg: str
    type: str


class ErrorBody(BaseModel):
    code: str
    message: str
    details: list[FieldError] | None = None
    """Each field that is not valid, when the request failed validation."""


class ErrorResponse(BaseModel):
    """The body of every error response."""

    error: ErrorBody


CLIENT_ERRORS: dict[int | str, dict[str, Any]] = {
    "4XX": {"model": ErrorResponse, "description": "The request failed. The error tells why."}
}
UNAVAILABLE: dict[int | str, dict[str, Any]] = {
    status.HTTP_503_SERVICE_UNAVAILABLE: {
        "model": ErrorResponse,
        "description": "An outside service is not set up, or it did not answer.",
    }
}


def json_errors(
    responses: Mapping[int | str, Mapping[str, Any]],
) -> dict[int | str, dict[str, Any]]:
    """These error responses for a route whose own body is not JSON, such as an event stream: the
    model shorthand would declare the error body under the route's media type."""
    schema = {"$ref": f"#/components/schemas/{ErrorResponse.__name__}"}
    return {
        code: {
            "description": response["description"],
            "content": {"application/json": {"schema": schema}},
        }
        for code, response in responses.items()
    }


def error_response(
    status_code: int,
    message: str,
    *,
    details: Any = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    body = ErrorResponse.model_validate(
        {"error": {"code": CODES.get(status_code, "error"), "message": message, "details": details}}
    )
    return JSONResponse(
        body.model_dump(mode="json", exclude_none=True), status_code=status_code, headers=headers
    )


def validation_summary(error: Mapping[str, Any]) -> str:
    """One readable line for a validation error: the field path, then the reason."""
    loc = list(error.get("loc", ()))
    if loc and loc[0] in REQUEST_PARTS and not (len(loc) == 1 and error.get("type") == "missing"):
        loc = loc[1:]
    if error.get("type") == "json_invalid":
        loc = []
    path = [str(part) for part in loc]
    reason = str(error.get("msg", "not valid")).removeprefix("Value error, ")
    return f"{'.'.join(path)}: {reason}" if path else reason


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(NotFoundError)
    async def not_found(_: Request, exc: NotFoundError) -> JSONResponse:
        return error_response(status.HTTP_404_NOT_FOUND, str(exc))

    @app.exception_handler(ConflictError)
    async def conflict(_: Request, exc: ConflictError) -> JSONResponse:
        return error_response(status.HTTP_409_CONFLICT, str(exc))

    @app.exception_handler(ValidationError)
    async def invalid(_: Request, exc: ValidationError) -> JSONResponse:
        return error_response(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))

    @app.exception_handler(UnavailableError)
    async def unavailable(_: Request, exc: UnavailableError) -> JSONResponse:
        return error_response(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc))

    @app.exception_handler(RequestValidationError)
    async def request_invalid(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {key: value for key, value in error.items() if key in {"loc", "msg", "type"}}
            for error in exc.errors()
        ]
        more = f" (and {len(details) - 1} more errors)" if len(details) > 1 else ""
        return error_response(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"{validation_summary(details[0])}{more}" if details else "the request is not valid",
            details=jsonable_encoder(details),
        )

    @app.exception_handler(HTTPException)
    async def http_error(_: Request, exc: HTTPException) -> JSONResponse:
        message = exc.detail if isinstance(exc.detail, str) else "request failed"
        return error_response(exc.status_code, message, headers=exc.headers)
