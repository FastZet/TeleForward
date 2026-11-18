
"""Integration management for the scheduler health API lifespan."""

from __future__ import annotations

import logging
from typing import Any, Callable

from fastapi import FastAPI

from app.services.scheduling.scheduler_runtime_lifespan_health import (
    SchedulerRuntimeLifespanHealthService,
)
from app.services.scheduling.scheduler_runtime_lifespan_health_api_lifespan import (
    LifespanFactory,
    SchedulerHealthAPILifespanError,
    get_scheduler_health_api_lifespan,
    install_scheduler_health_api_lifespan,
    is_scheduler_health_api_lifespan_registered,
)

logger = logging.getLogger(__name__)

INTEGRATION_STATE_KEY = (
    "scheduler_health_api_lifespan_integration"
)


class SchedulerHealthAPILifespanIntegrationError(RuntimeError):
    """Raised when lifespan integration operations fail."""


def _validate_app(app: FastAPI) -> None:
    """Validate the FastAPI application."""

    if not isinstance(app, FastAPI):
        raise TypeError("app must be a FastAPI instance")


def _get_integration_state(
    app: FastAPI,
) -> dict[str, Any] | None:
    """Return the stored integration metadata."""

    state = getattr(
        app.state,
        INTEGRATION_STATE_KEY,
        None,
    )

    if state is None:
        return None

    if not isinstance(state, dict):
        raise SchedulerHealthAPILifespanIntegrationError(
            "Scheduler health lifespan integration state is invalid"
        )

    return state


def install_scheduler_health_api_lifespan_integration(
    app: FastAPI,
    *,
    existing_lifespan: LifespanFactory | None = None,
    service: SchedulerRuntimeLifespanHealthService | None = None,
    replace: bool = False,
) -> LifespanFactory:
    """
    Register the scheduler health API lifespan integration.

    The returned lifespan must still be supplied to FastAPI during
    application construction. This function does not dynamically
    replace the application's active lifespan.
    """

    _validate_app(app)

    if not isinstance(replace, bool):
        raise TypeError("replace must be a boolean")

    if service is not None and not isinstance(
        service,
        SchedulerRuntimeLifespanHealthService,
    ):
        raise TypeError(
            "service must be a SchedulerRuntimeLifespanHealthService"
        )

    existing_state = _get_integration_state(app)

    if existing_state is not None:
        if not replace:
            raise SchedulerHealthAPILifespanIntegrationError(
                "Scheduler health API lifespan integration is already installed"
            )

        raise SchedulerHealthAPILifespanIntegrationError(
            "Replacing a registered lifespan integration is unsupported; "
            "construct a new FastAPI application instead"
        )

    if is_scheduler_health_api_lifespan_registered(app):
        raise SchedulerHealthAPILifespanIntegrationError(
            "A scheduler health API lifespan is already registered "
            "outside this integration"
        )

    try:
        lifespan = install_scheduler_health_api_lifespan(
            app,
            existing_lifespan=existing_lifespan,
            service=service,
        )

        setattr(
            app.state,
            INTEGRATION_STATE_KEY,
            {
                "installed": True,
                "lifespan": lifespan,
                "service_supplied": service is not None,
            },
        )

        logger.info(
            "Scheduler health API lifespan integration registered"
        )

        return lifespan

    except Exception as exc:
        logger.exception(
            "Failed to register scheduler health API lifespan integration"
        )

        raise SchedulerHealthAPILifespanIntegrationError(
            "Unable to register scheduler health API lifespan integration"
        ) from exc


def get_scheduler_health_api_lifespan_integration(
    app: FastAPI,
) -> LifespanFactory:
    """Return the lifespan registered by this integration."""

    _validate_app(app)

    state = _get_integration_state(app)

    if state is None or not state.get("installed"):
        raise SchedulerHealthAPILifespanIntegrationError(
            "Scheduler health API lifespan integration is not installed"
        )

    lifespan = state.get("lifespan")

    if not callable(lifespan):
        raise SchedulerHealthAPILifespanIntegrationError(
            "Registered scheduler health API lifespan is invalid"
        )

    return lifespan


def get_scheduler_health_api_lifespan_integration_status(
    app: FastAPI,
) -> dict[str, Any]:
    """Return the lifespan integration status."""

    _validate_app(app)

    state = _get_integration_state(app)

    registered = (
        state is not None
        and state.get("installed") is True
    )

    underlying_registered = (
        is_scheduler_health_api_lifespan_registered(app)
    )

    lifespan_valid = (
        registered
        and callable(state.get("lifespan"))
    )

    return {
        "integrated": registered,
        "lifespan_registered": underlying_registered,
        "lifespan_valid": lifespan_valid,
        "consistent": (
            registered
            and underlying_registered
            and lifespan_valid
        )
        or (
            not registered
            and not underlying_registered
        ),
        "service_supplied": (
            bool(state.get("service_supplied"))
            if state is not None
            else False
        ),
    }


def is_scheduler_health_api_lifespan_integrated(
    app: FastAPI,
) -> bool:
    """Return whether this integration is registered."""

    _validate_app(app)

    state = _get_integration_state(app)

    return (
        state is not None
        and state.get("installed") is True
        and callable(state.get("lifespan"))
    )


def remove_scheduler_health_api_lifespan_integration(
    app: FastAPI,
) -> None:
    """
    Remove lifespan integration registration metadata.

    This does not modify an already-created FastAPI application's
    active lifespan or stop a running application.
    """

    _validate_app(app)

    state = _get_integration_state(app)

    if state is None:
        logger.debug(
            "Scheduler health API lifespan integration is absent"
        )
        return

    setattr(
        app.state,
        INTEGRATION_STATE_KEY,
        None,
    )

    # Clear the registration created by File #330 so that the
    # application state does not advertise a stale lifespan factory.
    setattr(
        app.state,
        "scheduler_health_api_lifespan",
        None,
    )

    logger.info(
        "Scheduler health API lifespan integration metadata removed"
    )
