
"""FastAPI integration for the security audit health API."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from fastapi import Depends, FastAPI
from fastapi.params import Depends as DependsParameter

from app.services.scheduling.configuration_api_security_audit_health_api import (
    DEFAULT_HEALTH_PREFIX,
    register_security_audit_health_routes,
)


HEALTH_API_ROUTER_STATE_KEY = (
    "configuration_api_security_audit_health_router"
)
HEALTH_API_INSTALLATION_STATE_KEY = (
    "configuration_api_security_audit_health_api_installed"
)
HEALTH_API_PREFIX_STATE_KEY = (
    "configuration_api_security_audit_health_api_prefix"
)


class SecurityAuditHealthApiIntegrationError(RuntimeError):
    """Raised when security audit health API integration fails."""


def install_configuration_api_security_audit_health_api(
    app: FastAPI,
    *,
    prefix: str = DEFAULT_HEALTH_PREFIX,
    dependencies: Sequence[DependsParameter] | None = None,
    tags: list[str] | None = None,
) -> Any:
    """Install the security audit health API on a FastAPI application.

    The health service itself must be installed separately using
    install_configuration_api_security_audit_health().

    Args:
        app: FastAPI application.
        prefix: API route prefix.
        dependencies: Optional authentication and authorization dependencies.
        tags: Optional OpenAPI tags.

    Returns:
        The registered APIRouter.

    Raises:
        TypeError: If the application is invalid.
        SecurityAuditHealthApiIntegrationError: If installation fails
            or the API is already installed.
    """
    if not isinstance(app, FastAPI):
        raise TypeError("app must be a FastAPI application")

    if is_configuration_api_security_audit_health_api_installed(app):
        raise SecurityAuditHealthApiIntegrationError(
            "Security audit health API is already installed"
        )

    try:
        router = register_security_audit_health_routes(
            app,
            prefix=prefix,
            dependencies=dependencies,
            tags=tags,
        )
    except Exception as exc:
        raise SecurityAuditHealthApiIntegrationError(
            "Could not install security audit health API"
        ) from exc

    setattr(app.state, HEALTH_API_ROUTER_STATE_KEY, router)
    setattr(app.state, HEALTH_API_INSTALLATION_STATE_KEY, True)
    setattr(app.state, HEALTH_API_PREFIX_STATE_KEY, router.prefix)

    return router


def get_configuration_api_security_audit_health_api_router(
    app: FastAPI,
) -> Any:
    """Return the registered health API router."""
    if not isinstance(app, FastAPI):
        raise TypeError("app must be a FastAPI application")

    if not is_configuration_api_security_audit_health_api_installed(app):
        raise SecurityAuditHealthApiIntegrationError(
            "Security audit health API is not installed"
        )

    router = getattr(
        app.state,
        HEALTH_API_ROUTER_STATE_KEY,
        None,
    )

    if router is None:
        raise SecurityAuditHealthApiIntegrationError(
            "Security audit health API router is missing"
        )

    return router


def is_configuration_api_security_audit_health_api_installed(
    app: FastAPI,
) -> bool:
    """Return whether the health API is installed."""
    if not isinstance(app, FastAPI):
        raise TypeError("app must be a FastAPI application")

    installed = getattr(
        app.state,
        HEALTH_API_INSTALLATION_STATE_KEY,
        False,
    )

    router = getattr(
        app.state,
        HEALTH_API_ROUTER_STATE_KEY,
        None,
    )

    return installed is True and router is not None


def get_configuration_api_security_audit_health_api_prefix(
    app: FastAPI,
) -> str:
    """Return the registered health API prefix."""
    if not isinstance(app, FastAPI):
        raise TypeError("app must be a FastAPI application")

    if not is_configuration_api_security_audit_health_api_installed(app):
        raise SecurityAuditHealthApiIntegrationError(
            "Security audit health API is not installed"
        )

    prefix = getattr(
        app.state,
        HEALTH_API_PREFIX_STATE_KEY,
        None,
    )

    if not isinstance(prefix, str) or not prefix:
        raise SecurityAuditHealthApiIntegrationError(
            "Security audit health API prefix is unavailable"
        )

    return prefix


def remove_configuration_api_security_audit_health_api(
    app: FastAPI,
) -> Any:
    """Remove integration state for the health API.

    FastAPI does not support safely removing included routes after
    registration. This function therefore removes the integration
    metadata only. It does not unregister the actual endpoint.

    For actual route removal, construct a new application instance
    without registering this router.

    Returns:
        The previously registered router.

    Raises:
        TypeError: If app is not a FastAPI application.
        SecurityAuditHealthApiIntegrationError: If not installed.
    """
    if not isinstance(app, FastAPI):
        raise TypeError("app must be a FastAPI application")

    router = get_configuration_api_security_audit_health_api_router(app)

    setattr(app.state, HEALTH_API_ROUTER_STATE_KEY, None)
    setattr(app.state, HEALTH_API_INSTALLATION_STATE_KEY, False)
    setattr(app.state, HEALTH_API_PREFIX_STATE_KEY, None)

    return router
