
"""Integration management for composed scheduler health API lifespans."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI

from app.services.scheduling.scheduler_runtime_lifespan_health_api_lifespan import (
    LifespanFactory,
)
from app.services.scheduling.scheduler_runtime_lifespan_health_api_lifespan_composition import (
    compose_scheduler_health_api_lifespans,
)

logger = logging.getLogger(__name__)

COMPOSITION_STATE_KEY = (
    "scheduler_health_api_lifespan_composition"
)


class SchedulerHealthAPILifespanCompositionIntegrationError(
    RuntimeError
):
    """Raised when composed lifespan integration fails."""


def _validate_app(app: FastAPI) -> None:
    """Validate the FastAPI application."""

    if not isinstance(app, FastAPI):
        raise TypeError("app must be a FastAPI instance")


def _get_state(
    app: FastAPI,
) -> dict[str, Any] | None:
    """Retrieve and validate composition metadata."""

    state = getattr(
        app.state,
        COMPOSITION_STATE_KEY,
        None,
    )

    if state is None:
        return None

    if not isinstance(state, dict):
        raise SchedulerHealthAPILifespanCompositionIntegrationError(
            "Scheduler lifespan composition state is invalid"
        )

    return state


def install_scheduler_health_api_lifespan_composition(
    app: FastAPI,
    *,
    existing_lifespan: LifespanFactory | None = None,
    scheduler_runtime_lifespan: LifespanFactory | None = None,
    health_api_lifespan: LifespanFactory | None = None,
) -> LifespanFactory:
    """
    Compose and register application lifespan factories.

    The returned factory must be supplied to FastAPI during application
    construction. This function does not dynamically replace the
    application's active lifespan.
    """

    _validate_app(app)

    if _get_state(app) is not None:
        raise SchedulerHealthAPILifespanCompositionIntegrationError(
            "Scheduler health API lifespan composition is already installed"
        )

    try:
        composed_lifespan = compose_scheduler_health_api_lifespans(
            existing_lifespan=existing_lifespan,
            scheduler_runtime_lifespan=scheduler_runtime_lifespan,
            health_api_lifespan=health_api_lifespan,
        )

        metadata = {
            "installed": True,
            "lifespan": composed_lifespan,
            "existing_lifespan_supplied": (
                existing_lifespan is not None
            ),
            "scheduler_runtime_lifespan_supplied": (
                scheduler_runtime_lifespan is not None
            ),
            "health_api_lifespan_supplied": (
                health_api_lifespan is not None
            ),
        }

        setattr(
            app.state,
            COMPOSITION_STATE_KEY,
            metadata,
        )

        logger.info(
            "Scheduler health API lifespan composition registered"
        )

        return composed_lifespan

    except (TypeError, ValueError):
        raise

    except Exception as exc:
        logger.exception(
            "Failed to register scheduler health API lifespan composition"
        )

        raise SchedulerHealthAPILifespanCompositionIntegrationError(
            "Unable to register scheduler health API lifespan composition"
        ) from exc


def get_scheduler_health_api_lifespan_composition(
    app: FastAPI,
) -> LifespanFactory:
    """Return the registered composed lifespan factory."""

    _validate_app(app)

    state = _get_state(app)

    if state is None or state.get("installed") is not True:
        raise SchedulerHealthAPILifespanCompositionIntegrationError(
            "Scheduler health API lifespan composition is not installed"
        )

    lifespan = state.get("lifespan")

    if not callable(lifespan):
        raise SchedulerHealthAPILifespanCompositionIntegrationError(
            "Registered scheduler lifespan composition is invalid"
        )

    return lifespan


def is_scheduler_health_api_lifespan_composed(
    app: FastAPI,
) -> bool:
    """Return whether a valid composition is registered."""

    _validate_app(app)

    state = _get_state(app)

    return (
        state is not None
        and state.get("installed") is True
        and callable(state.get("lifespan"))
    )


def get_scheduler_health_api_lifespan_composition_status(
    app: FastAPI,
) -> dict[str, Any]:
    """Return composition registration and configuration status."""

    _validate_app(app)

    state = _get_state(app)

    if state is None:
        return {
            "installed": False,
            "lifespan_valid": False,
            "consistent": True,
            "existing_lifespan_supplied": False,
            "scheduler_runtime_lifespan_supplied": False,
            "health_api_lifespan_supplied": False,
        }

    installed = state.get("installed") is True
    lifespan_valid = callable(state.get("lifespan"))

    return {
        "installed": installed,
        "lifespan_valid": lifespan_valid,
        "consistent": installed and lifespan_valid,
        "existing_lifespan_supplied": bool(
            state.get("existing_lifespan_supplied")
        ),
        "scheduler_runtime_lifespan_supplied": bool(
            state.get("scheduler_runtime_lifespan_supplied")
        ),
        "health_api_lifespan_supplied": bool(
            state.get("health_api_lifespan_supplied")
        ),
    }


def remove_scheduler_health_api_lifespan_composition(
    app: FastAPI,
) -> None:
    """
    Remove composed lifespan registration metadata.

    This does not alter the active lifespan of an application that
    has already been constructed or started.
    """

    _validate_app(app)

    state = _get_state(app)

    if state is None:
        logger.debug(
            "Scheduler health API lifespan composition is absent"
        )
        return

    setattr(
        app.state,
        COMPOSITION_STATE_KEY,
        None,
    )

    logger.info(
        "Scheduler health API lifespan composition metadata removed"
    )
