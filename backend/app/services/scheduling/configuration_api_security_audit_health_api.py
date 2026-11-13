
"""FastAPI routes for security audit health monitoring."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.services.scheduling.configuration_api_security_audit_health_integration import (
    SecurityAuditHealthIntegrationError,
    get_configuration_api_security_audit_health_status,
)


DEFAULT_HEALTH_ROUTE = "/health"
DEFAULT_HEALTH_PREFIX = "/configuration/security/audit"


def create_security_audit_health_router(
    *,
    prefix: str = DEFAULT_HEALTH_PREFIX,
    dependencies: Sequence[Depends] | None = None,
    tags: list[str] | None = None,
) -> APIRouter:
    """Create the security audit health API router.

    Args:
        prefix: URL prefix for the health endpoint.
        dependencies: Optional router-level FastAPI dependencies.
            Use these to enforce authentication and authorization.
        tags: Optional OpenAPI tags.

    Returns:
        An APIRouter exposing GET /health.

    Raises:
        TypeError: If an argument has an invalid type.
        ValueError: If the route prefix is empty or invalid.
    """
    if not isinstance(prefix, str):
        raise TypeError("prefix must be a string")

    normalized_prefix = prefix.strip()

    if not normalized_prefix:
        raise ValueError("prefix must not be empty")

    if not normalized_prefix.startswith("/"):
        normalized_prefix = f"/{normalized_prefix}"

    normalized_prefix = normalized_prefix.rstrip("/")

    if "//" in normalized_prefix:
        raise ValueError("prefix must not contain consecutive slashes")

    if dependencies is not None:
        if not isinstance(dependencies, Sequence):
            raise TypeError("dependencies must be a sequence or None")

        if any(not isinstance(item, Depends) for item in dependencies):
            raise TypeError("dependencies must contain FastAPI Depends objects")

    if tags is not None:
        if not isinstance(tags, list) or any(
            not isinstance(tag, str) or not tag.strip()
            for tag in tags
        ):
            raise TypeError("tags must be a list of non-empty strings")

    router = APIRouter(
        prefix=normalized_prefix,
        dependencies=list(dependencies or []),
        tags=tags or ["Security Audit Health"],
    )

    @router.get(
        DEFAULT_HEALTH_ROUTE,
        name="security_audit_health",
        summary="Get security audit subsystem health",
        description=(
            "Returns the health status of the security audit logger "
            "and its configured storage."
        ),
        response_model=dict[str, Any],
        responses={
            status.HTTP_503_SERVICE_UNAVAILABLE: {
                "description": (
                    "The security audit health service is unavailable "
                    "or could not complete its health check."
                )
            }
        },
    )
    async def get_security_audit_health(
        request: Request,
    ) -> dict[str, Any]:
        """Return the current security audit health report."""
        try:
            return get_configuration_api_security_audit_health_status(
                request.app
            )
        except SecurityAuditHealthIntegrationError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "error": "security_audit_health_unavailable",
                    "message": str(exc),
                },
            ) from exc

    return router


def register_security_audit_health_routes(
    app: Any,
    *,
    prefix: str = DEFAULT_HEALTH_PREFIX,
    dependencies: Sequence[Depends] | None = None,
    tags: list[str] | None = None,
) -> APIRouter:
    """Register security audit health routes on a FastAPI application.

    Args:
        app: FastAPI application instance.
        prefix: URL prefix for the health endpoint.
        dependencies: Optional router-level dependencies.
        tags: Optional OpenAPI tags.

    Returns:
        The registered APIRouter.

    Raises:
        TypeError: If app is not a FastAPI application.
        RuntimeError: If the router has already been registered.
    """
    from fastapi import FastAPI

    if not isinstance(app, FastAPI):
        raise TypeError("app must be a FastAPI application")

    route_name = "security_audit_health"

    existing_routes = {
        getattr(route, "name", None)
        for route in app.routes
    }

    if route_name in existing_routes:
        raise RuntimeError(
            "Security audit health routes are already registered"
        )

    router = create_security_audit_health_router(
        prefix=prefix,
        dependencies=dependencies,
        tags=tags,
    )

    app.include_router(router)

    return router
