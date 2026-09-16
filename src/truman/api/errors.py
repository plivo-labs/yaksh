from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from truman.domain.errors import ConflictError, NotFoundError, ValidationError

CODES = {
    status.HTTP_401_UNAUTHORIZED: "unauthorized",
    status.HTTP_404_NOT_FOUND: "not_found",
    status.HTTP_409_CONFLICT: "conflict",
    status.HTTP_422_UNPROCESSABLE_CONTENT: "validation_error",
    status.HTTP_429_TOO_MANY_REQUESTS: "at_capacity",
}


def error_response(
    status_code: int,
    message: str,
    *,
    details: Any = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    error: dict[str, Any] = {"code": CODES.get(status_code, "error"), "message": message}
    if details is not None:
        error["details"] = details
    return JSONResponse({"error": error}, status_code=status_code, headers=headers)


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

    @app.exception_handler(RequestValidationError)
    async def request_invalid(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {key: value for key, value in error.items() if key in {"loc", "msg", "type"}}
            for error in exc.errors()
        ]
        return error_response(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "request validation failed",
            details=jsonable_encoder(details),
        )

    @app.exception_handler(HTTPException)
    async def http_error(_: Request, exc: HTTPException) -> JSONResponse:
        message = exc.detail if isinstance(exc.detail, str) else "request failed"
        return error_response(exc.status_code, message, headers=exc.headers)
