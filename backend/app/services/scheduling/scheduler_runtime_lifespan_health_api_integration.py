
"""Integration of scheduler lifespan health services and HTTP API."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI

from app.services.scheduling.scheduler_runtime_lifespan_health import (
    SchedulerRuntimeLifespanHealthService,
)
from app.services.scheduling.scheduler_runtime_lifespan_health_api import (
    install_scheduler_health_api,
)
from app.services.scheduling.scheduler_runtime_lifespan_health_integration import (
    SchedulerLifespanHealthIntegrationError,
    get_scheduler_lifespan_health_optional,
    install_scheduler_lifespan_health,
    remove_scheduler_lifespan_health,
)

logger = logging.getLogger(__name__)

INTEGRATION_STATE_KEY = (
    "scheduler_runtime_lifespan_health_api_integration"
)


class SchedulerHealthAPIIntegrationError(RuntimeError):
    """Raised when scheduler health API integration fails."""


def is_scheduler_health_api_integrated(
    app: FastAPI,
) -> bool:
    """Return whether the combined integration is installed."""

    if not isinstance(app, FastAPI):
        raise TypeError("app must be a FastAPI instance")

    return bool(
        getattr(app.state, INTEGRATION_STATE_KEY, False)
    )


def install_scheduler_health_api_integration(
    app: FastAPI,
    *,
    service: SchedulerRuntimeLifespanHealthService | None = None,
    replace: bool = False,
) -> SchedulerRuntimeLifespanHealthService:
    """
    Install the scheduler health service and its HTTP API.

    The health service is installed first. If API installation fails,
    a newly installed health service is removed as a rollback.

    Existing services are preserved if API installation fails.
    """

    if not isinstance(app, FastAPI):
        raise TypeError("app must be a FastAPI instance")

    if service is not None and not isinstance(
        service,
        SchedulerRuntimeLifespanHealthService,
    ):
        raise TypeError(
            "service must be a SchedulerRuntimeLifespanHealthService"
        )

    if not isinstance(replace, bool):
        raise TypeError("replace must be a boolean")

    if is_scheduler_health_api_integrated(app):
        if not replace:
            raise SchedulerHealthAPIIntegrationError(
                "Scheduler health API integration is already installed"
            )

        existing_service = get_scheduler_lifespan_health_optional(
            app
        )

        if existing_service is None:
            raise SchedulerHealthAPIIntegrationError(
                "Integration state is inconsistent: "
                "health service is missing"
            )

        if service is not None and service is not existing_service:
            raise SchedulerHealthAPIIntegrationError(
                "Replacing an installed health service is not supported "
                "because the HTTP router is already registered"
            )

        return existing_service

    existing_service = get_scheduler_lifespan_health_optional(
        app
    )

    service_was_installed = existing_service is not None

    selected_service = service or existing_service

    if selected_service is None:
        selected_service = SchedulerRuntimeLifespanHealthService(
            app=app
        )

    if service_was_installed and service is not None:
        if service is not existing_service:
            if not replace:
                raise SchedulerHealthAPIIntegrationError(
                    "A different scheduler health service is already installed"
                )

            raise SchedulerHealthAPIIntegrationError(
                "Replacing an existing health service is not supported "
                "by this integration"
            )

    try:
        if not service_was_installed:
            install_scheduler_lifespan_health(
                app,
                service=selected_service,
            )

        install_scheduler_health_api(
            app,
            replace=False,
        )

        setattr(
            app.state,
            INTEGRATION_STATE_KEY,
            True,
        )

        logger.info(
            "Scheduler health API integration installed"
        )

        return selected_service

    except Exception as exc:
        logger.exception(
            "Failed to install scheduler health API integration"
        )

        if not service_was_installed:
            try:
                remove_scheduler_lifespan_health(app)
            except Exception:
                logger.exception(
                    "Failed to roll back scheduler health service installation"
                )

        raise SchedulerHealthAPIIntegrationError(
            "Unable to install scheduler health API integration"
        ) from exc


def get_scheduler_health_api_integration(
    app: FastAPI,
) -> SchedulerRuntimeLifespanHealthService:
    """Return the installed health service for this integration."""

    if not isinstance(app, FastAPI):
        raise TypeError("app must be a FastAPI instance")

    if not is_scheduler_health_api_integrated(app):
        raise SchedulerHealthAPIIntegrationError(
            "Scheduler health API integration is not installed"
        )

    service = get_scheduler_lifespan_health_optional(app)

    if service is None:
        raise SchedulerHealthAPIIntegrationError(
            "Scheduler health API integration is inconsistent: "
            "health service is missing"
        )

    return service


def get_scheduler_health_api_integration_status(
    app: FastAPI,
) -> dict[str, Any]:
    """Return a diagnostic snapshot of the integration state."""

    if not isinstance(app, FastAPI):
        raise TypeError("app must be a FastAPI instance")

    integrated = is_scheduler_health_api_integrated(app)

    service = get_scheduler_lifespan_health_optional(app)

    return {
        "integrated": integrated,
        "health_service_installed": service is not None,
        "api_installed": bool(
            getattr(
                app.state,
                "scheduler_health_api_installed",
                False,
            )
        ),
        "consistent": (
            integrated
            and service is not None
            and bool(
                getattr(
                    app.state,
                    "scheduler_health_api_installed",
                    False,
                )
            )
        )
        or (
            not integrated
            and service is None
            and not bool(
                getattr(
                    app.state,
                    "scheduler_health_api_installed",
                    False,
                )
            )
        ),
    }


def remove_scheduler_health_api_integration(
    app: FastAPI,
) -> None:
    """
    Remove the integration's health-service state.

    FastAPI does not support safely unregistering an included router
    at runtime. The HTTP route therefore remains registered, but it
    will return HTTP 503 when its health service is absent.
    """

    if not isinstance(app, FastAPI):
        raise TypeError("app must be a FastAPI instance")

    try:
        remove_scheduler_lifespan_health(app)
    except SchedulerLifespanHealthIntegrationError:
        logger.debug(
            "Scheduler health service was already absent"
        )

    setattr(
        app.state,
        INTEGRATION_STATE_KEY,
        False,
    )

    logger.info(
        "Scheduler health API integration state removed"
    )
