
"""FastAPI integration for consolidated security audit health-status API."""

from __future__ import annotations

from collections.abc import Sequence

from fastapi import FastAPI
from fastapi.params import Depends as DependsParameter

from app.services.scheduling.configuration_api_security_audit_health_status_api import (
    DEFAULT_STATUS_PREFIX,
    register_security_audit_health_status_routes,
)


STATUS_API_ROUTER_STATE_KEY = (
    "configuration_api_security_audit_health_status_api_router"
)
STATUS_API_INSTALLATION_STATE_KEY = (
    "configuration_api_security_audit_health_status_api_installed"
)
STATUS_API_PREFIX_STATE_KEY = (
    "configuration_api_security_audit_health_status_api_prefix"
)


class SecurityAuditHealthStatusApiIntegrationError(RuntimeError):
    """Raised when consolidated health-status API integration fails."""


def install_configuration_api_security_audit_health_status_api(
    app: FastAPI,
    *,
    prefix: str = DEFAULT_STATUS_PREFIX,
    dependencies: Sequence[DependsParameter] | None = None,
    tags: list[str] | None = None,
):
    """Install the consolidated security audit health-status API.

    The consolidated health-status service must be installed separately.

    Args:
        app: FastAPI application.
        prefix: URL prefix for the status endpoint.
        dependencies: Optional authentication and authorization dependencies.
        tags: Optional OpenAPI tags.

    Returns:
        The registered APIRouter.

    Raises:
        TypeError: If app is not a FastAPI application.
        SecurityAuditHealthStatusApiIntegrationError:
            If installation fails or the API is already installed.
    """
    if not isinstance(app, FastAPI):
        raise TypeError("app must be a FastAPI application")

    if is_configuration_api_security_audit_health_status_api_installed(
        app
    ):
        raise SecurityAuditHealthStatusApiIntegrationError(
            "Consolidated security audit health-status API is already installed"
        )

    try:
        router = register_security_audit_health_status_routes(
            app,
            prefix=prefix,
            dependencies=dependencies,
            tags=tags,
        )

        # Record integration state only after successful route registration.
        setattr(app.state, STATUS_API_ROUTER_STATE_KEY, router)
        setattr(app.state, STATUS_API_PREFIX_STATE_KEY, router.prefix)
        setattr(app.state, STATUS_API_INSTALLATION_STATE_KEY, True)

        return router

    except Exception as exc:
        raise SecurityAuditHealthStatusApiIntegrationError(
            "Could not install consolidated security audit health-status API"
        ) from exc


def get_configuration_api_security_audit_health_status_api_router(
    app: FastAPI,
):
    """Return the registered consolidated health-status router."""
    if not isinstance(app, FastAPI):
        raise TypeError("app must be a FastAPI application")

    if not is_configuration_api_security_audit_health_status_api_installed(
        app
    ):
        raise SecurityAuditHealthStatusApiIntegrationError(
            "Consolidated security audit health-status API is not installed"
        )

    router = getattr(
        app.state,
        STATUS_API_ROUTER_STATE_KEY,
        None,
    )

    if router is None:
        raise SecurityAuditHealthStatusApiIntegrationError(
            "Consolidated health-status API router is unavailable"
        )

    return router


def is_configuration_api_security_audit_health_status_api_installed(
    app: FastAPI,
) -> bool:
    """Return whether the consolidated health-status API is installed."""
    if not isinstance(app, FastAPI):
        raise TypeError("app must be a FastAPI application")

    installed = getattr(
        app.state,
        STATUS_API_INSTALLATION_STATE_KEY,
        False,
    )

    router = getattr(
        app.state,
        STATUS_API_ROUTER_STATE_KEY,
        None,
    )

    return installed is True and router is not None


def get_configuration_api_security_audit_health_status_api_prefix(
    app: FastAPI,
) -> str:
    """Return the registered consolidated health-status API prefix."""
    if not isinstance(app, FastAPI):
        raise TypeError("app must be a FastAPI application")

    if not is_configuration_api_security_audit_health_status_api_installed(
        app
    ):
        raise SecurityAuditHealthStatusApiIntegrationError(
            "Consolidated security audit health-status API is not installed"
        )

    prefix = getattr(
        app.state,
        STATUS_API_PREFIX_STATE_KEY,
        None,
    )

    if not isinstance(prefix, str) or not prefix:
        raise SecurityAuditHealthStatusApiIntegrationError(
            "Consolidated health-status API prefix is unavailable"
        )

    return prefix


def remove_configuration_api_security_audit_health_status_api(
    app: FastAPI,
):
    """Remove consolidated health-status API integration metadata.

    FastAPI does not provide a supported public mechanism for removing
    an already included router. This function therefore clears the
    integration metadata without unregistering the actual endpoint.

    Recreate the FastAPI application if actual route removal is required.

    Args:
        app: FastAPI application.

    Returns:
        The previously registered router.
    """
    if not isinstance(app, FastAPI):
        raise TypeError("app must be a FastAPI application")

    router = (
        get_configuration_api_security_audit_health_status_api_router(
            app
        )
    )

    setattr(app.state, STATUS_API_ROUTER_STATE_KEY, None)
    setattr(app.state, STATUS_API_PREFIX_STATE_KEY, None)
    setattr(app.state, STATUS_API_INSTALLATION_STATE_KEY, False)

    return router
