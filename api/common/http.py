"""Shared HTTP helpers: consistent JSON errors and request validation."""

from __future__ import annotations

import logging
from typing import Any

from django.http import Http404, HttpRequest, JsonResponse
from pydantic import BaseModel, ValidationError
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from engine.llm import LLMError

logger = logging.getLogger(__name__)

LLM_ERROR_STATUS = {
    "not_configured": status.HTTP_409_CONFLICT,
    "encryption_unavailable": status.HTTP_503_SERVICE_UNAVAILABLE,
    "invalid_credentials": status.HTTP_502_BAD_GATEWAY,
    "permission_denied": status.HTTP_502_BAD_GATEWAY,
    "rate_limited": status.HTTP_429_TOO_MANY_REQUESTS,
    "quota_exceeded": status.HTTP_402_PAYMENT_REQUIRED,
    "model_unavailable": status.HTTP_502_BAD_GATEWAY,
    "bad_request": status.HTTP_502_BAD_GATEWAY,
    "timeout": status.HTTP_504_GATEWAY_TIMEOUT,
    "network": status.HTTP_502_BAD_GATEWAY,
    "provider_error": status.HTTP_502_BAD_GATEWAY,
    "unsupported": status.HTTP_400_BAD_REQUEST,
}


class ApiError(Exception):
    def __init__(
        self,
        message: str,
        *,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        code: str = "bad_request",
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code
        self.extra = extra or {}


def error_response(
    message: str,
    *,
    status_code: int = status.HTTP_400_BAD_REQUEST,
    code: str = "bad_request",
    **extra: Any,
) -> Response:
    return Response({"detail": message, "code": code, **extra}, status=status_code)


def llm_error_payload(exc: LLMError) -> dict[str, Any]:
    return {"detail": exc.message, "code": exc.kind, "llm": exc.to_dict()}


def find_llm_error(exc: BaseException | None) -> LLMError | None:
    seen = 0
    while exc is not None and seen < 10:
        if isinstance(exc, LLMError):
            return exc
        exc = exc.__cause__ or exc.__context__
        seen += 1
    return None


def validate[ModelT: BaseModel](model: type[ModelT], data: Any) -> ModelT:
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        errors = [
            {
                "field": ".".join(str(part) for part in error["loc"]) or "body",
                "message": error["msg"],
            }
            for error in exc.errors()
        ]
        first = errors[0] if errors else {"field": "body", "message": "Invalid request."}
        raise ApiError(
            f"{first['field']}: {first['message']}",
            status_code=status.HTTP_400_BAD_REQUEST,
            code="validation_error",
            extra={"errors": errors},
        ) from exc


def csrf_failure(request: HttpRequest, reason: str = "") -> JsonResponse:
    return JsonResponse(
        {
            "detail": "The security token is missing or expired. Reload the page and try again.",
            "code": "csrf_failed",
        },
        status=403,
    )


def exception_handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    if isinstance(exc, ApiError):
        return error_response(exc.message, status_code=exc.status_code, code=exc.code, **exc.extra)
    if isinstance(exc, LLMError):
        return Response(
            llm_error_payload(exc),
            status=LLM_ERROR_STATUS.get(exc.kind, status.HTTP_502_BAD_GATEWAY),
        )
    if isinstance(exc, Http404):
        return error_response(str(exc) or "Not found.", status_code=404, code="not_found")

    response = drf_exception_handler(exc, context)
    if response is None:
        logger.exception("Unhandled API error", exc_info=exc)
        return error_response("Unexpected server error.", status_code=500, code="server_error")

    if isinstance(response.data, dict) and "detail" in response.data:
        detail = response.data["detail"]
        response.data = {
            "detail": str(detail),
            "code": getattr(detail, "code", "error"),
        }
    else:
        response.data = {"detail": "Invalid request.", "code": "invalid", "errors": response.data}
    return response
