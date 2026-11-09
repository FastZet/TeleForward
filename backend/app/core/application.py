
"""
TeleForward FastAPI application factory.

Creates and configures the main FastAPI application, including
middleware, exception handlers, health endpoints and API metadata.
"""

from fastapi import APIRouter, FastAPI, Request, Response, status
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.core.config import get_settings
from app.core.exception_handlers import register_exception_handlers
from app.core.health import (
    get_detailed_health,
    get_liveness_status,
    get_readiness_status,
)
from app.core.lifecycle import application_lifespan
from app.core.middleware import get_middleware_stack
from app.core.rate_limiter import limiter


# ============================================================
# Health router
# ============================================================

health_router = APIRouter(tags=["Health"])


@health_router.get(
    "/health",
    summary="Application health check",
    description="Lightweight liveness endpoint for container monitoring.",
    status_code=status.HTTP_200_OK,
)
async def health_check() -> dict:
    """
    Return application liveness status.

    This endpoint intentionally avoids database and external
    service checks so Docker can use it as a lightweight probe.
    """
    return get_liveness_status()


@health_router.get(
    "/health/live",
    summary="Application liveness",
    status_code=status.HTTP_200_OK,
)
async def liveness_check() -> dict:
    """Return whether the application process is alive."""
    return get_liveness_status()


@health_router.get(
    "/health/ready",
    summary="Application readiness",
)
async def readiness_check(request: Request) -> Response:
    """Return whether the application is ready to accept requests."""
    result = get_readiness_status(request)

    response_status = (
        status.HTTP_200_OK
        if result["status"] == "ready"
        else status.HTTP_503_SERVICE_UNAVAILABLE
    )

    from fastapi.responses import JSONResponse

    return JSONResponse(
        status_code=response_status,
        content=result,
    )


@health_router.get(
    "/health/details",
    summary="Detailed application health",
)
async def detailed_health_check(request: Request) -> Response:
    """
    Return the health status of registered infrastructure.

    Internal component details are intended for operational
    monitoring and should not be exposed publicly without
    appropriate access controls.
    """
    result = await get_detailed_health(request)

    response_status = (
        status.HTTP_200_OK
        if result["status"] == "healthy"
        else status.HTTP_503_SERVICE_UNAVAILABLE
    )

    from fastapi.responses import JSONResponse

    return JSONResponse(
        status_code=response_status,
        content=result,
    )


# ============================================================
# Application factory
# ============================================================

def create_application() -> FastAPI:
    """
    Create and configure the TeleForward FastAPI application.

    Returns:
        Configured FastAPI application instance.
    """
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        description=(
            "Self-hosted Telegram automation, message forwarding "
            "and workflow management platform."
        ),
        version=settings.app_version,
        debug=settings.debug,
        lifespan=application_lifespan,
        docs_url="/api/docs" if not settings.is_production else None,
        redoc_url="/api/redoc" if not settings.is_production else None,
        openapi_url="/api/openapi.json" if not settings.is_production else None,
    )

    # --------------------------------------------------------
    # Application state
    # --------------------------------------------------------

    app.state.ready = False
    app.state.database_engine = None
    app.state.database_session_factory = None

    # --------------------------------------------------------
    # Rate limiting
    # --------------------------------------------------------

    app.state.limiter = limiter

    app.add_exception_handler(
        RateLimitExceeded,
        lambda request, exc: __import__(
            "fastapi.responses",
            fromlist=["JSONResponse"],
        ).JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={
                "success": False,
                "message": "Too many requests. Please try again later.",
                "error_code": "RATE_LIMIT_EXCEEDED",
                "details": {},
            },
        ),
    )

    app.add_middleware(SlowAPIMiddleware)

    # --------------------------------------------------------
    # Custom middleware
    # --------------------------------------------------------

    for middleware_class, middleware_options in get_middleware_stack():
        app.add_middleware(
            middleware_class,
            **middleware_options,
        )

    # --------------------------------------------------------
    # Exception handlers
    # --------------------------------------------------------

    register_exception_handlers(app)

    # --------------------------------------------------------
    # Routers
    # --------------------------------------------------------

    app.include_router(health_router)

    # Versioned API router will be registered here when the
    # API modules are implemented.

    return app


# ============================================================
# Application instance
# ============================================================

app = create_application()
