
"""FastAPI application-state integration for bootstrap health."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import FastAPI

from app.services.scheduling.integration_bootstrap import (
    SchedulingIntegrationBootstrap,
)
from app.services.scheduling.integration_bootstrap_health import (
    BootstrapHealthReport,
    BootstrapHealthStatus,
    SchedulingBootstrapHealthService,
)


if TYPE_CHECKING:
    from types import ModuleType


BOOTSTRAP_HEALTH_STATE_KEY = (
    "scheduling_bootstrap_health_service"
)


class BootstrapHealthIntegrationError(RuntimeError):
    """Raised when bootstrap health integration fails."""


def _validate_app(app: FastAPI) -> None:
    if not isinstance(app, FastAPI):
        raise TypeError("app must be a FastAPI instance")


def _validate_service(
    service: SchedulingBootstrapHealthService,
) -> None:
    if not isinstance(service, SchedulingBootstrapHealthService):
        raise TypeError(
            "service must be a SchedulingBootstrapHealthService"
        )


def install_bootstrap_health(
    app: FastAPI,
    service: SchedulingBootstrapHealthService | None = None,
    *,
    bootstrap: SchedulingIntegrationBootstrap | None = None,
    replace: bool = False,
) -> SchedulingBootstrapHealthService:
    """Install the bootstrap health service on a FastAPI application.

    Args:
        app: FastAPI application receiving the integration.
        service: Existing health service to install.
        bootstrap: Optional bootstrap instance used to construct a
            health service when service is not supplied.
        replace: Whether an existing service may be replaced.

    Returns:
        The installed health service.
    """
    _validate_app(app)

    if service is not None and bootstrap is not None:
        raise ValueError(
            "Provide either service or bootstrap, not both"
        )

    if service is not None:
        _validate_service(service)

    existing = getattr(
        app.state,
        BOOTSTRAP_HEALTH_STATE_KEY,
        None,
    )

    if existing is not None:
        _validate_service(existing)

        if existing is service and service is not None:
            return existing

        if not replace:
            raise BootstrapHealthIntegrationError(
                "Bootstrap health service is already installed"
            )

    if service is None:
        service = SchedulingBootstrapHealthService(
            bootstrap=bootstrap
        )

    _validate_service(service)

    setattr(
        app.state,
        BOOTSTRAP_HEALTH_STATE_KEY,
        service,
    )

    return service


def get_bootstrap_health(
    app: FastAPI,
) -> SchedulingBootstrapHealthService:
    """Retrieve the installed bootstrap health service."""
    _validate_app(app)

    service = getattr(
        app.state,
        BOOTSTRAP_HEALTH_STATE_KEY,
        None,
    )

    if service is None:
        raise BootstrapHealthIntegrationError(
            "Bootstrap health service is not installed"
        )

    _validate_service(service)

    return service


def get_bootstrap_health_optional(
    app: FastAPI,
) -> SchedulingBootstrapHealthService | None:
    """Retrieve the installed service, returning None if absent."""
    _validate_app(app)

    service = getattr(
        app.state,
        BOOTSTRAP_HEALTH_STATE_KEY,
        None,
    )

    if service is None:
        return None

    _validate_service(service)

    return service


def is_bootstrap_health_installed(app: FastAPI) -> bool:
    """Return whether a valid bootstrap health service is installed."""
    service = get_bootstrap_health_optional(app)
    return service is not None


def get_bootstrap_health_report(
    app: FastAPI,
) -> BootstrapHealthReport:
    """Return the current bootstrap health report."""
    service = get_bootstrap_health(app)
    return service.inspect()


def get_bootstrap_health_status(
    app: FastAPI,
) -> BootstrapHealthStatus:
    """Return the current bootstrap health classification."""
    service = get_bootstrap_health(app)
    return service.get_status()


def is_bootstrap_healthy(app: FastAPI) -> bool:
    """Return whether the installed bootstrap is healthy."""
    service = get_bootstrap_health(app)
    return service.is_healthy()


def remove_bootstrap_health(
    app: FastAPI,
    *,
    expected_service: SchedulingBootstrapHealthService | None = None,
) -> SchedulingBootstrapHealthService:
    """Remove the installed bootstrap health service.

    When expected_service is supplied, removal succeeds only if the
    installed service is the exact same object. This prevents stale
    cleanup code from removing a replacement service.
    """
    _validate_app(app)

    service = get_bootstrap_health(app)

    if expected_service is not None:
        _validate_service(expected_service)

        if service is not expected_service:
            raise BootstrapHealthIntegrationError(
                "Installed bootstrap health service does not match "
                "the expected service"
            )

    delattr(app.state, BOOTSTRAP_HEALTH_STATE_KEY)

    return service
