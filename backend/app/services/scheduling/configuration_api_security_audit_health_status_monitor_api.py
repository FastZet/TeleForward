
"""REST API routes for the security-audit health-status monitor."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    HTTPException,
    Query,
    Request,
    status,
)
from fastapi.routing import APIRoute

from app.services.scheduling.configuration_api_security_audit_health_status_monitor_integration import (
    SecurityAuditHealthStatusMonitorIntegrationError,
    check_configuration_api_security_audit_health_status_monitor,
    get_configuration_api_security_audit_health_status_monitor_history,
    get_configuration_api_security_audit_health_status_monitor_status,
)


DEFAULT_MONITOR_API_PREFIX = (
    "/configuration/security/audit/monitor"
)

MONITOR_STATUS_PATH = "/status"
MONITOR_HISTORY_PATH = "/history"
MONITOR_CHECK_PATH = "/check"


class SecurityAuditHealthStatusMonitorApiError(RuntimeError):
    """Raised when monitor API registration fails."""


def _normalize_prefix(prefix: str) -> str:
    if not isinstance(prefix, str):
        raise TypeError("prefix must be a string")

    normalized = prefix.strip()

    if not normalized:
        raise ValueError("prefix cannot be empty")

    if "?" in normalized or "#" in normalized:
        raise ValueError("prefix cannot contain query or fragment parts")

    if not normalized.startswith("/"):
        normalized = f"/{normalized}"

    normalized = normalized.rstrip("/")

    if not normalized:
        raise ValueError("prefix cannot be the root path")

    if "//" in normalized:
        raise ValueError("prefix cannot contain consecutive slashes")

    return normalized


def _validate_dependencies(
    dependencies: Sequence[Depends] | None,
) -> list[Depends]:
    if dependencies is None:
        return []

    if isinstance(dependencies, (str, bytes)):
        raise TypeError("dependencies must be a sequence of Depends")

    result = list(dependencies)

    for dependency in result:
        if not isinstance(dependency, Depends):
            raise TypeError(
                "every dependency must be created with fastapi.Depends"
            )

    return result


def _validate_tags(tags: Sequence[str] | None) -> list[str]:
    if tags is None:
        return ["Security Audit Monitoring"]

    if isinstance(tags, (str, bytes)):
        raise TypeError("tags must be a sequence of strings")

    result = list(tags)

    if any(
        not isinstance(tag, str) or not tag.strip()
        for tag in result
    ):
        raise ValueError("every tag must be a non-empty string")

    return result


def _route_exists(
    app: FastAPI,
    path: str,
    method: str,
) -> bool:
    normalized_method = method.upper()

    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue

        if route.path == path and normalized_method in route.methods:
            return True

    return False


def _serialize_snapshot(snapshot: Any) -> dict[str, Any]:
    checked_at = snapshot.checked_at

    if not isinstance(checked_at, datetime):
        raise TypeError("snapshot.checked_at must be a datetime")

    return {
        "snapshot_id": snapshot.snapshot_id,
        "checked_at": checked_at.isoformat(),
        "status": snapshot.status.value,
        "duration_seconds": snapshot.duration_seconds,
        "error": snapshot.error,
    }


def create_security_audit_health_status_monitor_router(
    *,
    prefix: str = DEFAULT_MONITOR_API_PREFIX,
    dependencies: Sequence[Depends] | None = None,
    tags: Sequence[str] | None = None,
) -> APIRouter:
    """Create an API router for health-monitor operations."""

    normalized_prefix = _normalize_prefix(prefix)
    normalized_dependencies = _validate_dependencies(dependencies)
    normalized_tags = _validate_tags(tags)

    router = APIRouter(
        prefix=normalized_prefix,
        dependencies=normalized_dependencies,
        tags=normalized_tags,
    )

    @router.get(
        MONITOR_STATUS_PATH,
        name="security_audit_health_monitor_status",
        summary="Get security-audit health monitor status",
        response_description="Current monitor status and statistics",
    )
    async def get_monitor_status(
        request: Request,
    ) -> dict[str, Any]:
        """Return current monitor state and aggregate statistics."""

        try:
            return (
                get_configuration_api_security_audit_health_status_monitor_status(
                    request.app
                )
            )

        except SecurityAuditHealthStatusMonitorIntegrationError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Security-audit health monitor is unavailable",
            ) from exc

    @router.get(
        MONITOR_HISTORY_PATH,
        name="security_audit_health_monitor_history",
        summary="Get security-audit health monitor history",
        response_description="Retained health-check snapshots",
    )
    async def get_monitor_history(
        request: Request,
        limit: int = Query(
            default=50,
            ge=1,
            le=1000,
            description="Maximum number of newest snapshots to return",
        ),
    ) -> dict[str, Any]:
        """Return recent health-check snapshots."""

        try:
            snapshots = (
                get_configuration_api_security_audit_health_status_monitor_history(
                    request.app,
                    limit=limit,
                )
            )

            return {
                "count": len(snapshots),
                "items": [
                    _serialize_snapshot(snapshot)
                    for snapshot in snapshots
                ],
            }

        except SecurityAuditHealthStatusMonitorIntegrationError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Security-audit health monitor is unavailable",
            ) from exc

    @router.post(
        MONITOR_CHECK_PATH,
        name="security_audit_health_monitor_check",
        status_code=status.HTTP_200_OK,
        summary="Execute a security-audit health check",
        response_description="Result of the health check",
    )
    async def run_monitor_check(
        request: Request,
    ) -> dict[str, Any]:
        """Execute one immediate health check."""

        try:
            snapshot = (
                await check_configuration_api_security_audit_health_status_monitor(
                    request.app
                )
            )

            return _serialize_snapshot(snapshot)

        except SecurityAuditHealthStatusMonitorIntegrationError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Security-audit health check could not be executed",
            ) from exc

    return router


def register_security_audit_health_status_monitor_routes(
    app: FastAPI,
    *,
    prefix: str = DEFAULT_MONITOR_API_PREFIX,
    dependencies: Sequence[Depends] | None = None,
    tags: Sequence[str] | None = None,
) -> APIRouter:
    """Register health-monitor routes on a FastAPI application."""

    if not isinstance(app, FastAPI):
        raise TypeError("app must be a FastAPI instance")

    normalized_prefix = _normalize_prefix(prefix)

    expected_routes = (
        (f"{normalized_prefix}{MONITOR_STATUS_PATH}", "GET"),
        (f"{normalized_prefix}{MONITOR_HISTORY_PATH}", "GET"),
        (f"{normalized_prefix}{MONITOR_CHECK_PATH}", "POST"),
    )

    duplicates = [
        f"{method} {path}"
        for path, method in expected_routes
        if _route_exists(app, path, method)
    ]

    if duplicates:
        raise SecurityAuditHealthStatusMonitorApiError(
            "Monitor API routes already exist: "
            + ", ".join(duplicates)
        )

    try:
        router = create_security_audit_health_status_monitor_router(
            prefix=normalized_prefix,
            dependencies=dependencies,
            tags=tags,
        )

        app.include_router(router)

        return router

    except Exception as exc:
        if isinstance(exc, SecurityAuditHealthStatusMonitorApiError):
            raise

        raise SecurityAuditHealthStatusMonitorApiError(
            "Failed to register security-audit health monitor routes"
        ) from exc


__all__ = [
    "DEFAULT_MONITOR_API_PREFIX",
    "MONITOR_STATUS_PATH",
    "MONITOR_HISTORY_PATH",
    "MONITOR_CHECK_PATH",
    "SecurityAuditHealthStatusMonitorApiError",
    "create_security_audit_health_status_monitor_router",
    "register_security_audit_health_status_monitor_routes",
]
