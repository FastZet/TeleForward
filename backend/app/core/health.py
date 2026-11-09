
"""
TeleForward application health checks.

Provides liveness, readiness and detailed health information
for container orchestration and operational monitoring.
"""

from datetime import UTC, datetime
from typing import Any

import structlog
from fastapi import Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = structlog.get_logger(__name__)


def get_uptime_timestamp() -> str:
    """Return the current UTC timestamp."""
    return datetime.now(UTC).isoformat()


def get_liveness_status() -> dict[str, Any]:
    """
    Return the application's liveness status.

    This endpoint should remain lightweight and should not
    depend on database or external service availability.
    """
    return {
        "status": "alive",
        "timestamp": get_uptime_timestamp(),
    }


def get_readiness_status(request: Request) -> dict[str, Any]:
    """
    Return the application's readiness status.

    The lifecycle manager marks the application as ready
    after successful startup initialisation.
    """
    ready = getattr(request.app.state, "ready", False)

    return {
        "status": "ready" if ready else "not_ready",
        "timestamp": get_uptime_timestamp(),
    }


async def check_database_health(
    engine: AsyncEngine | None,
) -> dict[str, Any]:
    """
    Check database connectivity.

    Args:
        engine: Configured asynchronous SQLAlchemy engine.

    Returns:
        Database health information.
    """
    if engine is None:
        return {
            "status": "not_configured",
        }

    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

        return {
            "status": "healthy",
        }

    except Exception:
        logger.exception("database_health_check_failed")

        return {
            "status": "unhealthy",
        }


async def get_detailed_health(
    request: Request,
) -> dict[str, Any]:
    """
    Return detailed application health information.

    Checks the database if an engine has been registered
    in the FastAPI application state.
    """
    engine = getattr(request.app.state, "database_engine", None)

    database = await check_database_health(engine)

    components = {
        "database": database,
    }

    overall_healthy = all(
        component["status"] in ("healthy", "not_configured")
        for component in components.values()
    )

    return {
        "status": "healthy" if overall_healthy else "degraded",
        "timestamp": get_uptime_timestamp(),
        "components": components,
    }
