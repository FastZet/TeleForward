
"""
TeleForward application health monitoring.

Provides:
- Application liveness checks.
- Application readiness checks.
- Detailed dependency health diagnostics.
"""

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import Request

from app import __app_name__, __version__
from app.database.health import (
    check_database_connection,
    get_database_diagnostics,
)


logger = logging.getLogger(__name__)


def get_liveness_status() -> dict[str, Any]:
    """
    Return application liveness information.

    Liveness does not depend on database availability.
    """
    return {
        "status": "alive",
        "application": __app_name__,
        "version": __version__,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def get_readiness_status(request: Request) -> dict[str, Any]:
    """
    Check whether the application has completed startup.

    The lifecycle manager must explicitly set app.state.ready
    after all critical startup operations succeed.
    """
    ready = bool(
        getattr(request.app.state, "ready", False)
    )

    return {
        "status": "ready" if ready else "not_ready",
        "application": __app_name__,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


async def get_detailed_health() -> dict[str, Any]:
    """
    Return detailed application dependency diagnostics.

    Database availability is considered a critical dependency.
    """
    database_health = await check_database_connection()
    database_diagnostics = await get_database_diagnostics()

    dependencies = {
        "database": {
            **database_health,
            "diagnostics": database_diagnostics,
        }
    }

    dependency_statuses = [
        dependency.get("status")
        for dependency in dependencies.values()
    ]

    healthy = all(
        status == "healthy"
        for status in dependency_statuses
    )

    return {
        "status": "healthy" if healthy else "degraded",
        "application": __app_name__,
        "version": __version__,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "dependencies": dependencies,
    }


async def get_application_health(
    request: Request,
) -> dict[str, Any]:
    """
    Combine application readiness and dependency health.

    This is intended for administrative diagnostics rather
    than the lightweight container liveness probe.
    """
    readiness = get_readiness_status(request)
    detailed_health = await get_detailed_health()

    ready = readiness["status"] == "ready"
    healthy = detailed_health["status"] == "healthy"

    if ready and healthy:
        overall_status = "healthy"
    elif not ready:
        overall_status = "not_ready"
    else:
        overall_status = "degraded"

    return {
        "status": overall_status,
        "readiness": readiness,
        "health": detailed_health,
    }
