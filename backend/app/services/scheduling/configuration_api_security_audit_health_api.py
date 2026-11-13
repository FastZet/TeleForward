
"""FastAPI routes for security audit health monitoring."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, status
from fastapi.params import Depends as DependsParameter

from app.services.scheduling.configuration_api_security_audit_health_integration import (
    SecurityAuditHealthIntegrationError,
    get_configuration_api_security_audit_health_status,
)


DEFAULT_HEALTH_ROUTE = "/health"
DEFAULT_HEALTH_PREFIX = "/configuration/security/audit"


def _normalize_prefix(prefix: str) -> str:
    """Validate and normalize an API route prefix."""
    if not isinstance(prefix, str):
        raise TypeError("prefix must be a string")

    normalized = prefix.strip()

    if not normalized:
        raise ValueError("prefix must not be empty")

    if not normalized.startswith("/"):
        normalized = f"/{normalized}"

    normalized = normalized.rstrip("/")

    if not normalized:
        raise ValueError("prefix must not resolve to the root path")

    if "//" in normalized:
        raise ValueError("prefix must not contain consecutive slashes")

    if "{" in normalized or "}" in normalized:
        raise ValueError("prefix must not contain path parameters")

    return normalized


def _validate_dependencies(
    dependencies: Sequence[DependsParameter] | None,
) -> list[DependsParameter]:
    """Validate router-level FastAPI dependencies."""
    if dependencies is None:
        return []

    if isinstance(dependencies, (str, bytes)) or not isinstance(
        dependencies,
        Sequence,
    ):
        raise TypeError("dependencies must be a sequence or None")

    if any(
        not isinstance(dependency, DependsParameter)
        for dependency in dependencies
    ):
        raise TypeError(
            "dependencies must contain FastAPI Depends objects"
        )

    return list(dependencies)


def _validate_tags(tags: list[str] | None) -> list[str]:
    """Validate OpenAPI tags."""
    if tags is None:
        return ["Security Audit Health"]

    if not isinstance(tags, list):
        raise TypeError("tags must be a list of non-empty strings")

    if any(
        not isinstance(tag, str) or not tag.strip()
        for tag in tags
    ):
        raise TypeError("tags must be a list of non-empty strings")

    return [tag.strip() for tag in tags]


def create_security_audit_health_router(
    *,
    prefix: str = DEFAULT_HEALTH_PREFIX,
    dependencies: Sequence[DependsParameter] | None = None,
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
    """
    normalized_prefix = _normalize_prefix(prefix)
    validated_dependencies = _validate_dependencies(dependencies)
    validated_tags = _validate_tags(tags)

    router = APIRouter(
        prefix=normalized_prefix,
        dependencies=validated_dependencies,
        tags=validated_tags,
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
    app: FastAPI,
    *,
    prefix: str = DEFAULT_HEALTH_PREFIX,
    dependencies: Sequence[DependsParameter] | None = None,
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
        RuntimeError: If the health route is already registered.
    """
    if not isinstance(app, FastAPI):
        raise TypeError("app must be a FastAPI application")

    # Validate arguments before modifying the application.
    normalized_prefix = _normalize_prefix(prefix)
    validated_dependencies = _validate_dependencies(dependencies)
    validated_tags = _validate_tags(tags)

    expected_path = f"{normalized_prefix}{DEFAULT_HEALTH_ROUTE}"

    for route in app.routes:
        if (
            getattr(route, "path", None) == expected_path
            and "GET" in (getattr(route, "methods", None) or set())
        ):
            raise RuntimeError(
                f"Security audit health route already exists: "
                f"GET {expected_path}"
            )

    router = create_security_audit_health_router(
        prefix=normalized_prefix,
        dependencies=validated_dependencies,
        tags=validated_tags,
    )

    app.include_router(router)

    return router
