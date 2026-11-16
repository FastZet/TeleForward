
"""FastAPI integration for scheduler runtime lifespan health."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI

from app.services.scheduling.scheduler_runtime_lifespan_health import (
    SchedulerRuntimeLifespanHealthService,
)

logger = logging.getLogger(__name__)

SCHEDULER_LIFESPAN_HEALTH_STATE_KEY = (
    "scheduler_runtime_lifespan_health"
)


class SchedulerLifespanHealthIntegrationError(RuntimeError):
    """Raised when scheduler lifespan health integration fails."""


def _validate_app(app: FastAPI) -> None:
    """Validate the FastAPI application."""

    if not isinstance(app, FastAPI):
        raise TypeError("app must be a FastAPI instance")


def install_scheduler_lifespan_health(
    app: FastAPI,
    service: SchedulerRuntimeLifespanHealthService | None = None,
    *,
    replace: bool = False,
) -> SchedulerRuntimeLifespanHealthService:
    """
    Install a scheduler lifespan health service.

    If no service is supplied, a service bound to the application
    is created automatically.
    """

    _validate_app(app)

    if not isinstance(replace, bool):
        raise TypeError("replace must be a boolean")

    if service is None:
        service = SchedulerRuntimeLifespanHealthService(app=app)

    elif not isinstance(
        service,
        SchedulerRuntimeLifespanHealthService,
    ):
        raise TypeError(
            "service must be a SchedulerRuntimeLifespanHealthService"
        )

    existing = getattr(
        app.state,
        SCHEDULER_LIFESPAN_HEALTH_STATE_KEY,
        None,
    )

    if existing is not None and not replace:
        raise SchedulerLifespanHealthIntegrationError(
            "Scheduler lifespan health service is already installed"
        )

    setattr(
        app.state,
        SCHEDULER_LIFESPAN_HEALTH_STATE_KEY,
        service,
    )

    logger.info("Scheduler lifespan health service installed")

    return service


def get_scheduler_lifespan_health(
    app: FastAPI,
) -> SchedulerRuntimeLifespanHealthService:
    """Retrieve the registered scheduler lifespan health service."""

    _validate_app(app)

    service = getattr(
        app.state,
        SCHEDULER_LIFESPAN_HEALTH_STATE_KEY,
        None,
    )

    if service is None:
        raise SchedulerLifespanHealthIntegrationError(
            "Scheduler lifespan health service is not installed"
        )

    if not isinstance(
        service,
        SchedulerRuntimeLifespanHealthService,
    ):
        raise SchedulerLifespanHealthIntegrationError(
            "Registered scheduler lifespan health service is invalid"
        )

    return service


def get_scheduler_lifespan_health_optional(
    app: FastAPI,
) -> SchedulerRuntimeLifespanHealthService | None:
    """Retrieve the service or return None when not installed."""

    _validate_app(app)

    service = getattr(
        app.state,
        SCHEDULER_LIFESPAN_HEALTH_STATE_KEY,
        None,
    )

    if service is None:
        return None

    if not isinstance(
        service,
        SchedulerRuntimeLifespanHealthService,
    ):
        raise SchedulerLifespanHealthIntegrationError(
            "Registered scheduler lifespan health service is invalid"
        )

    return service


def is_scheduler_lifespan_health_installed(
    app: FastAPI,
) -> bool:
    """Check whether scheduler lifespan health is installed."""

    return get_scheduler_lifespan_health_optional(app) is not None


def remove_scheduler_lifespan_health(
    app: FastAPI,
) -> SchedulerRuntimeLifespanHealthService:
    """
    Remove the health service registration.

    This does not stop the scheduler runtime.
    """

    _validate_app(app)

    service = get_scheduler_lifespan_health(app)

    delattr(
        app.state,
        SCHEDULER_LIFESPAN_HEALTH_STATE_KEY,
    )

    logger.info("Scheduler lifespan health service removed")

    return service


def get_scheduler_lifespan_health_status(
    app: FastAPI,
) -> dict[str, Any]:
    """Return the current scheduler lifespan health status."""

    service = get_scheduler_lifespan_health(app)

    try:
        return service.get_status(app)

    except Exception as exc:
        logger.exception(
            "Failed to retrieve scheduler lifespan health status"
        )

        raise SchedulerLifespanHealthIntegrationError(
            "Failed to retrieve scheduler lifespan health status"
        ) from exc


def is_scheduler_lifespan_healthy(
    app: FastAPI,
) -> bool:
    """Return whether the scheduler runtime is healthy."""

    service = get_scheduler_lifespan_health(app)

    try:
        return service.is_healthy(app)

    except Exception as exc:
        logger.exception(
            "Failed to evaluate scheduler lifespan health"
        )

        raise SchedulerLifespanHealthIntegrationError(
            "Failed to evaluate scheduler lifespan health"
        ) from exc
