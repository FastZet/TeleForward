
"""
TeleForward HTTP middleware.

Provides request correlation, request timing, security headers,
and structured HTTP request logging.
"""

import re
import time
import uuid
from collections.abc import Callable

import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.core.config import get_settings


logger = structlog.get_logger(__name__)

# Accept only simple, bounded request identifiers.
REQUEST_ID_PATTERN = re.compile(r"^[a-zA-Z0-9._-]{1,128}$")


class RequestContextMiddleware(BaseHTTPMiddleware):
    """
    Attach a unique request ID to each HTTP request.

    A valid incoming X-Request-ID is preserved. Otherwise,
    a new UUID is generated.

    The identifier is returned in the response header and
    bound to the logging context for request correlation.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable,
    ) -> Response:
        incoming_id = request.headers.get("X-Request-ID", "")

        if REQUEST_ID_PATTERN.fullmatch(incoming_id):
            request_id = incoming_id
        else:
            request_id = str(uuid.uuid4())

        request.state.request_id = request_id

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
        )

        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            structlog.contextvars.clear_contextvars()


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Log HTTP request completion and processing duration.

    Request bodies, query parameters, cookies, authorization
    headers and other potentially sensitive values are omitted.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable,
    ) -> Response:
        start_time = time.perf_counter()

        try:
            response = await call_next(request)

        except Exception:
            duration_ms = round(
                (time.perf_counter() - start_time) * 1000,
                2,
            )

            logger.exception(
                "http_request_failed",
                method=request.method,
                path=request.url.path,
                duration_ms=duration_ms,
            )

            raise

        duration_ms = round(
            (time.perf_counter() - start_time) * 1000,
            2,
        )

        logger.info(
            "http_request_completed",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
        )

        response.headers["X-Process-Time-Ms"] = str(duration_ms)

        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Add baseline browser security headers.

    Content Security Policy is intentionally not imposed here.
    It will be configured alongside the frontend deployment
    once the actual asset and API requirements are established.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable,
    ) -> Response:
        response = await call_next(request)

        settings = get_settings()

        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=()"
        )

        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"

        if settings.is_production:
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )

        return response


def get_middleware_stack() -> list[tuple[type, dict]]:
    """
    Return the application's custom middleware configuration.

    Middleware is applied by the FastAPI application factory.

    RequestContextMiddleware is listed before request logging
    so request IDs can be attached to log entries.
    """
    return [
        (RequestContextMiddleware, {}),
        (RequestLoggingMiddleware, {}),
        (SecurityHeadersMiddleware, {}),
    ]
