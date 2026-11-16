
"""FastAPI application-state integration for composition health monitoring."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI

from app.services.scheduling.scheduler_runtime_lifespan_health_api_lifespan_composition_health import (
    CompositionHealthReport,
    CompositionHealthStatus,
    SchedulerHealthAPILifespanCompositionHealthService,
)


logger = logging.getLogger(__name__)

COMPOSITION_HEALTH_STATE_KEY = (
    "scheduler_health_api_lifespan_composition_health"
)


class SchedulerHealthAPILifespanCompositionHealthIntegrationError(
    RuntimeError
):
    """Raised when composition health integration fails."""


def _validate_app(app: FastAPI) -> None:
    if not isinstance(app, FastAPI):
        raise TypeError("app must be a FastAPI instance")


def _get_service_from_state(
    app: FastAPI,
) -> SchedulerHealthAPILifespanCompositionHealthService | None:
    service = getattr(
        app.state,
        COMPOSITION_HEALTH_STATE_KEY,
        None,
    )

    if service is None:
        return None

    if not isinstance(
        service,
        SchedulerHealthAPILifespanCompositionHealthService,
    ):
        raise SchedulerHealthAPILifespanCompositionHealthIntegrationError(
            "Invalid composition health service stored in application state"
        )

    return service


def install_scheduler_health_api_lifespan_composition_health(
    app: FastAPI,
    service: SchedulerHealthAPILifespanCompositionHealthService | None = None,
    *,
    replace: bool = False,
) -> SchedulerHealthAPILifespanCompositionHealthService:
    """Install the composition health service into application state.

    If no service is supplied, a new service bound to the application is
    created. Installing the same service again is idempotent.
    """
    _validate_app(app)

    existing = _get_service_from_state(app)

    if existing is not None:
        if service is existing:
            return existing

        if not replace:
            raise SchedulerHealthAPILifespanCompositionHealthIntegrationError(
                "Composition health service is already installed"
            )

    selected_service = (
        service
        if service is not None
        else SchedulerHealthAPILifespanCompositionHealthService()
    )

    if not isinstance(
        selected_service,
        SchedulerHealthAPILifespanCompositionHealthService,
    ):
        raise TypeError(
            "service must be a SchedulerHealthAPILifespanCompositionHealthService"
        )

    try:
        selected_service.bind(app)
    except Exception as exc:
        raise SchedulerHealthAPILifespanCompositionHealthIntegrationError(
            "Failed to bind composition health service to application"
        ) from exc

    setattr(
        app.state,
        COMPOSITION_HEALTH_STATE_KEY,
        selected_service,
    )

    logger.info(
        "Installed scheduler composition health service"
    )

    return selected_service


def get_scheduler_health_api_lifespan_composition_health(
    app: FastAPI,
) -> SchedulerHealthAPILifespanCompositionHealthService:
    """Return the installed composition health service."""
    _validate_app(app)

    service = _get_service_from_state(app)

    if service is None:
        raise SchedulerHealthAPILifespanCompositionHealthIntegrationError(
            "Composition health service is not installed"
        )

    return service


def get_optional_scheduler_health_api_lifespan_composition_health(
    app: FastAPI,
) -> SchedulerHealthAPILifespanCompositionHealthService | None:
    """Return the installed service, or None if it is absent."""
    _validate_app(app)
    return _get_service_from_state(app)


def is_scheduler_health_api_lifespan_composition_health_installed(
    app: FastAPI,
) -> bool:
    """Check whether a valid composition health service is installed."""
    _validate_app(app)
    return _get_service_from_state(app) is not None


def get_scheduler_health_api_lifespan_composition_health_status(
    app: FastAPI,
) -> dict[str, Any]:
    """Return installation and composition health information."""
    _validate_app(app)

    service = _get_service_from_state(app)

    if service is None:
        return {
            "installed": False,
            "healthy": False,
            "status": CompositionHealthStatus.UNAVAILABLE.value,
            "report": None,
        }

    try:
        report: CompositionHealthReport = service.inspect()

        return {
            "installed": True,
            "healthy": report.status is CompositionHealthStatus.HEALTHY,
            "status": report.status.value,
            "report": report.to_dict(),
        }

    except Exception as exc:
        logger.exception(
            "Failed to inspect scheduler composition health"
        )

        return {
            "installed": True,
            "healthy": False,
            "status": CompositionHealthStatus.FAILED.value,
            "report": None,
            "error": str(exc),
        }


def is_scheduler_health_api_lifespan_composition_healthy(
    app: FastAPI,
) -> bool:
    """Return whether the installed composition currently reports healthy."""
    status = (
        get_scheduler_health_api_lifespan_composition_health_status(app)
    )
    return status["healthy"]


def remove_scheduler_health_api_lifespan_composition_health(
    app: FastAPI,
    *,
    required: bool = False,
) -> SchedulerHealthAPILifespanCompositionHealthService | None:
    """Remove the composition health service from application state.

    This removes only the integration reference. It does not shut down the
    application, alter its lifespan, or unregister any API routes.
    """
    _validate_app(app)

    service = _get_service_from_state(app)

    if service is None:
        if required:
            raise SchedulerHealthAPILifespanCompositionHealthIntegrationError(
                "Composition health service is not installed"
            )
        return None

    try:
        delattr(app.state, COMPOSITION_HEALTH_STATE_KEY)
    except AttributeError as exc:
        raise SchedulerHealthAPILifespanCompositionHealthIntegrationError(
            "Failed to remove composition health service"
        ) from exc

    logger.info(
        "Removed scheduler composition health service"
    )

    return service
