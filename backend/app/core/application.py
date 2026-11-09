
"""
TeleForward FastAPI application factory.

Creates and configures the application instance, middleware,
exception handlers, health endpoints, and application lifespan.
"""

import logging
from contextlib import AbstractAsyncContextManager
from typing import Any, Callable

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app import __app_name__, __version__
from app.core.config import get_settings
from app.core.csrf import (
    CSRFMiddleware,
)
from app.core.exception_handlers import register_exception_handlers
from app.core.health import (
    get_application_health,
    get_detailed_health,
    get_liveness_status,
    get_readiness_status,
)
from app.core.lifecycle import application_lifespan
from app.core.middleware import (
    RequestContextMiddleware,
    RequestLoggingMiddleware,
    SecurityHeadersMiddleware,
)
from app.core.rate_limiter import limiter


logger = logging.getLogger(__name__)


async def rate_limit_exception_handler(
    request: Request,
    exc: RateLimitExceeded,
) -> JSONResponse:
    """Return a consistent JSON response for rate-limit violations."""
    retry_after = getattr(exc, "retry_after", None)

    headers: dict[str, str] = {}

    if retry_after is not None:
        headers["Retry-After"] = str(retry_after)

    return JSONResponse(
        status_code=429,
        content={
            "success": False,
            "error": {
                "code": "RATE_LIMIT_EXCEEDED",
                "message": "Too many requests. Please try again later.",
            },
        },
        headers=headers,
    )


def create_application(
    lifespan: Callable[
        [FastAPI],
        AbstractAsyncContextManager[Any],
    ] | None = None,
) -> FastAPI:
    """
    Construct and configure a TeleForward application instance.

    A lifespan can be supplied explicitly for testing. Otherwise,
    the production application lifespan is used.
    """
    settings = get_settings()

    application = FastAPI(
        title=__app_name__,
        description=(
            "Self-hosted Telegram automation and message-forwarding platform."
        ),
        version=__version__,
        lifespan=lifespan or application_lifespan,
        docs_url="/docs" if settings.environment != "production" else None,
        redoc_url="/redoc" if settings.environment != "production" else None,
        openapi_url=(
            "/openapi.json"
            if settings.environment != "production"
            else None
        ),
    )

    # Application state.
    application.state.ready = False
    application.state.settings = settings
    application.state.limiter = limiter

    # Exception handlers.
    register_exception_handlers(application)
    application.add_exception_handler(
        RateLimitExceeded,
        rate_limit_exception_handler,
    )

    # Request and security middleware.
    application.add_middleware(SecurityHeadersMiddleware)
    application.add_middleware(RequestLoggingMiddleware)
    application.add_middleware(RequestContextMiddleware)

    # CSRF protection is enabled for browser-facing requests.
    # The middleware implementation must be compatible with
    # the application's authentication/session implementation.
    application.add_middleware(CSRFMiddleware)

    # Rate limiting.
    application.add_middleware(SlowAPIMiddleware)

    # Trusted host validation.
    if settings.trusted_hosts:
        application.add_middleware(
            TrustedHostMiddleware,
            allowed_hosts=settings.trusted_hosts,
        )

    # Cross-origin access.
    if settings.cors_origins:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=[
                "Authorization",
                "Content-Type",
                "X-Request-ID",
                "X-CSRF-Token",
            ],
        )

    # Health endpoints.
    @application.get(
        "/health",
        tags=["Health"],
        summary="Application liveness",
        include_in_schema=False,
    )
    async def health() -> dict[str, Any]:
        """Lightweight liveness endpoint for container monitoring."""
        return get_liveness_status()

    @application.get(
        "/health/live",
        tags=["Health"],
        summary="Application liveness",
    )
    async def health_live() -> dict[str, Any]:
        return get_liveness_status()

    @application.get(
        "/health/ready",
        tags=["Health"],
        summary="Application readiness",
    )
    async def health_ready(request: Request) -> Response:
        result = get_readiness_status(request)

        status_code = (
            200 if result["status"] == "ready" else 503
        )

        return JSONResponse(
            status_code=status_code,
            content=result,
        )

    @application.get(
        "/health/details",
        tags=["Health"],
        summary="Detailed dependency health",
    )
    async def health_details() -> Response:
        result = await get_detailed_health()

        status_code = (
            200 if result["status"] == "healthy" else 503
        )

        return JSONResponse(
            status_code=status_code,
            content=result,
        )

    @application.get(
        "/health/application",
        tags=["Health"],
        summary="Combined application health",
        include_in_schema=False,
    )
    async def health_application(request: Request) -> Response:
        result = await get_application_health(request)

        status_code = (
            200 if result["status"] == "healthy" else 503
        )

        return JSONResponse(
            status_code=status_code,
            content=result,
        )

    logger.info(
        "TeleForward application instance created",
        extra={
            "environment": settings.environment,
            "version": __version__,
        },
    )

    return application
