import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.request_logging import get_correlation_id

logger = logging.getLogger(__name__)


class ErrorDetail(BaseModel):
    field: str | None = None
    message: str


class ErrorBody(BaseModel):
    code: str
    message: str
    status: int
    details: list[ErrorDetail] | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


class AppError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: list[ErrorDetail] | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details
        super().__init__(message)


def error_response(
    status_code: int,
    code: str,
    message: str,
    details: list[ErrorDetail] | None = None,
) -> JSONResponse:
    payload = ErrorResponse(
        error=ErrorBody(
            code=code,
            message=message,
            status=status_code,
            details=details or None,
        )
    )
    return JSONResponse(
        status_code=status_code,
        content=payload.model_dump(exclude_none=True),
    )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(_request: Request, exc: AppError) -> JSONResponse:
        return error_response(
            exc.status_code,
            exc.code,
            exc.message,
            exc.details,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_request_validation_error(
        _request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        details = [
            ErrorDetail(
                field=_format_error_location(error.get("loc", ())),
                message=str(error.get("msg", "Invalid value")),
            )
            for error in exc.errors()
        ]
        return error_response(
            422,
            "validation_error",
            "Request validation failed",
            details,
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(
        _request: Request,
        exc: StarletteHTTPException,
    ) -> JSONResponse:
        if isinstance(exc.detail, dict) and "error" in exc.detail:
            return JSONResponse(status_code=exc.status_code, content=exc.detail)

        message = exc.detail if isinstance(exc.detail, str) else "Request failed"
        code = _default_code_for_status(exc.status_code)
        return error_response(exc.status_code, code, message)

    @app.exception_handler(Exception)
    async def handle_unhandled_exception(
        request: Request,
        exc: Exception,
    ) -> JSONResponse:
        correlation_id = get_correlation_id()
        logger.exception(
            "Unhandled error processing %s",
            request.url.path,
            extra={"correlation_id": correlation_id},
        )
        return error_response(
            500,
            "internal_error",
            "An unexpected error occurred while processing the request",
        )


def _format_error_location(location: tuple[Any, ...]) -> str | None:
    parts = [str(part) for part in location if part != "body"]
    return ".".join(parts) or None


def _default_code_for_status(status_code: int) -> str:
    if status_code == 413:
        return "file_too_large"
    if status_code == 422:
        return "validation_error"
    if status_code >= 500:
        return "internal_error"
    return "http_error"
