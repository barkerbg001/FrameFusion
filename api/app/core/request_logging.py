import logging
import time
import uuid
from collections.abc import AsyncIterator
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse

logger = logging.getLogger("app.request")

CORRELATION_ID_HEADER = "X-Request-ID"

correlation_id_ctx: ContextVar[str | None] = ContextVar("correlation_id", default=None)


def get_correlation_id() -> str | None:
    return correlation_id_ctx.get()


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        correlation_id = request.headers.get(CORRELATION_ID_HEADER) or str(uuid.uuid4())
        correlation_id_ctx.set(correlation_id)
        start = time.perf_counter()
        method = request.method
        path = request.url.path

        try:
            response = await call_next(request)
        except Exception:
            self._log(
                correlation_id=correlation_id,
                method=method,
                path=path,
                status_code=500,
                duration_ms=(time.perf_counter() - start) * 1000,
                output_size_bytes=0,
                failed=True,
            )
            raise

        response.headers[CORRELATION_ID_HEADER] = correlation_id
        original_iterator = response.body_iterator

        async def counted_body() -> AsyncIterator[bytes]:
            output_size_bytes = 0
            try:
                async for chunk in original_iterator:
                    output_size_bytes += len(chunk)
                    yield chunk
            finally:
                self._log(
                    correlation_id=correlation_id,
                    method=method,
                    path=path,
                    status_code=response.status_code,
                    duration_ms=(time.perf_counter() - start) * 1000,
                    output_size_bytes=output_size_bytes,
                )

        return StreamingResponse(
            counted_body(),
            status_code=response.status_code,
            headers=response.headers,
            media_type=response.media_type,
            background=response.background,
        )

    @staticmethod
    def _log(
        *,
        correlation_id: str,
        method: str,
        path: str,
        status_code: int,
        duration_ms: float,
        output_size_bytes: int,
        failed: bool = False,
    ) -> None:
        payload = {
            "correlation_id": correlation_id,
            "method": method,
            "path": path,
            "status_code": status_code,
            "duration_ms": round(duration_ms, 2),
            "output_size_bytes": output_size_bytes,
        }
        if failed:
            logger.error("request failed", extra=payload)
        else:
            logger.info("request completed", extra=payload)
