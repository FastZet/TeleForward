
"""FastAPI integration for the security-audit health monitor API."""

from __future__ import annotations

import logging
from collections.abc import Sequence

from fastapi import Depends, FastAPI
from fastapi.params import Depends as DependsParameter
from fastapi.routing import APIRouter

from app.services.scheduling.configuration_api_security_audit_health_status_monitor_api import (
    DEFAULT_MONITOR_API_PREFIX,
    SecurityAuditHealthStatusMonitorApiError,
    register_security_audit_health_status_monitor_routes,
)


logger = logging.getLogger(__name__)


MONITOR_API_ROUTER_STATE_KEY = (
    "configuration_api_security_audit_health_status_monitor_api_router"
)

MONITOR_API_INSTALLED_STATE_KEY = (
    "configuration_api_security_audit_health_status_monitor_api_installed"
)

MONITOR_API_PREFIX_STATE_KEY = (
    "configuration_api_security_audit_health_status_monitor_api_prefix"
)


class SecurityAuditHealthStatusMonitorApiIntegrationError(RuntimeError):
    """Raised when monitor API integration operations fail."""


def _validate_app(app: FastAPI) -> None:
    if not isinstance(app, FastAPI):
        raise TypeError("app must be a FastAPI instance")


def _validate_dependencies(
    dependencies: Sequence[DependsParameter] | None,
) -> list[DependsParameter] | None:
    if dependencies is None:
        return None

    if isinstance(dependencies, (str, bytes)):
        raise TypeError("dependencies must be a sequence of Depends")

    result = list(dependencies)

    for dependency in result:
        if not isinstance(dependency, DependsParameter):
            raise TypeError(
                "every dependency must be created with fastapi.Depends"
            )

    return result


def install_configuration_api_security_audit_health_status_monitor_api(
    app: FastAPI,
    *,
    prefix: str = DEFAULT_MONITOR_API_PREFIX,
    dependencies: Sequence[DependsParameter] | None = None,
    tags: Sequence[str] | None = None,
) -> APIRouter:
    """Register the health-monitor API router on a FastAPI application."""

    _validate_app(app)

    if is_configuration_api_security_audit_health_status_monitor_api_installed(
        app
    ):
        raise SecurityAuditHealthStatusMonitorApiIntegrationError(
            "Security-audit health monitor API is already installed"
        )

    if getattr(app.state, MONITOR_API_ROUTER_STATE_KEY, None) is not None:
        raise SecurityAuditHealthStatusMonitorApiIntegrationError(
            "Monitor API state contains an unregistered router"
        )

    try:
        validated_dependencies = _validate_dependencies(dependencies)

        router = register_security_audit_health_status_monitor_routes(
            app,
            prefix=prefix,
            dependencies=validated_dependencies,
            tags=tags,
        )

        # Store integration state only after route registration succeeds.
        setattr(app.state, MONITOR_API_ROUTER_STATE_KEY, router)
        setattr(app.state, MONITOR_API_INSTALLED_STATE_KEY, True)
        setattr(app.state, MONITOR_API_PREFIX_STATE_KEY, router.prefix)

        logger.info(
            "Installed security-audit health monitor API at %s",
            router.prefix,
        )

        return router

    except SecurityAuditHealthStatusMonitorApiError as exc:
        raise SecurityAuditHealthStatusMonitorApiIntegrationError(
            "Security-audit health monitor API route registration failed"
        ) from exc

    except SecurityAuditHealthStatusMonitorApiIntegrationError:
        raise

    except Exception as exc:
        raise SecurityAuditHealthStatusMonitorApiIntegrationError(
            "Failed to install security-audit health monitor API"
        ) from exc


def get_configuration_api_security_audit_health_status_monitor_api_router(
    app: FastAPI,
) -> APIRouter:
    """Retrieve the registered monitor API router."""

    _validate_app(app)

    if not is_configuration_api_security_audit_health_status_monitor_api_installed(
        app
    ):
        raise SecurityAuditHealthStatusMonitorApiIntegrationError(
            "Security-audit health monitor API is not installed"
        )

    router = getattr(app.state, MONITOR_API_ROUTER_STATE_KEY, None)

    if not isinstance(router, APIRouter):
        raise SecurityAuditHealthStatusMonitorApiIntegrationError(
            "Registered monitor API router is invalid"
        )

    return router


def is_configuration_api_security_audit_health_status_monitor_api_installed(
    app: FastAPI,
) -> bool:
    """Return whether a valid monitor API router is registered."""

    _validate_app(app)

    if not getattr(app.state, MONITOR_API_INSTALLED_STATE_KEY, False):
        return False

    router = getattr(app.state, MONITOR_API_ROUTER_STATE_KEY, None)

    return isinstance(router, APIRouter)


def get_configuration_api_security_audit_health_status_monitor_api_prefix(
    app: FastAPI,
) -> str:
    """Return the registered monitor API prefix."""

    _validate_app(app)

    if not is_configuration_api_security_audit_health_status_monitor_api_installed(
        app
    ):
        raise SecurityAuditHealthStatusMonitorApiIntegrationError(
            "Security-audit health monitor API is not installed"
        )

    prefix = getattr(app.state, MONITOR_API_PREFIX_STATE_KEY, None)

    if not isinstance(prefix, str) or not prefix:
        raise SecurityAuditHealthStatusMonitorApiIntegrationError(
            "Registered monitor API prefix is invalid"
        )

    return prefix


def remove_configuration_api_security_audit_health_status_monitor_api(
    app: FastAPI,
) -> APIRouter:
    """Clear monitor API integration metadata.

    FastAPI does not provide a supported public operation to unregister
    individual routes after inclusion. Consequently, this function
    clears integration metadata but does not remove actual routes.
    """

    router = (
        get_configuration_api_security_audit_health_status_monitor_api_router(
            app
        )
    )

    setattr(app.state, MONITOR_API_ROUTER_STATE_KEY, None)
    setattr(app.state, MONITOR_API_INSTALLED_STATE_KEY, False)
    setattr(app.state, MONITOR_API_PREFIX_STATE_KEY, None)

    logger.info(
        "Cleared security-audit health monitor API integration metadata"
    )

    return router


__all__ = [
    "MONITOR_API_ROUTER_STATE_KEY",
    "MONITOR_API_INSTALLED_STATE_KEY",
    "MONITOR_API_PREFIX_STATE_KEY",
    "SecurityAuditHealthStatusMonitorApiIntegrationError",
    "install_configuration_api_security_audit_health_status_monitor_api",
    "get_configuration_api_security_audit_health_status_monitor_api_router",
    "is_configuration_api_security_audit_health_status_monitor_api_installed",
    "get_configuration_api_security_audit_health_status_monitor_api_prefix",
    "remove_configuration_api_security_audit_health_status_monitor_api",
]
