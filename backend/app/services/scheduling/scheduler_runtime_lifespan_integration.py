
"""FastAPI integration helpers for the scheduler runtime lifespan."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI

from app.services.scheduling.scheduler_runtime_integration import (
    SchedulerRuntimeIntegrationError,
    get_scheduler_runtime,
)
from app.services.scheduling.scheduler_runtime_lifespan import (
    create_scheduler_runtime_lifespan,
)

logger = logging.getLogger(__name__)

SCHEDULER_RUNTIME_LIFESPAN_STATE_KEY = (
    "scheduler_runtime_lifespan"
)


class SchedulerRuntimeLifespanIntegrationError(RuntimeError):
    """Raised when scheduler runtime lifespan integration fails."""


def _validate_app(app: FastAPI) -> None:
    if not isinstance(app, FastAPI):
        raise TypeError("app must be a FastAPI instance")


def create_scheduler_runtime_lifespan_integration(
    *,
    before_start: Callable[..., Any] | None = None,
    after_start: Callable[..., Any] | None = None,
    before_shutdown: Callable[..., Any] | None = None,
    after_shutdown: Callable[..., Any] | None = None,
):
    """
    Create a scheduler runtime lifespan callable independently
    of a FastAPI application instance.

    Usage:

        lifespan = create_scheduler_runtime_lifespan_integration()

        app = FastAPI(lifespan=lifespan)

        install_scheduler_runtime(app, runtime)

    The scheduler runtime must be installed on the same application
    instance that FastAPI passes to the lifespan.
    """

    callbacks = {
        "before_start": before_start,
        "after_start": after_start,
        "before_shutdown": before_shutdown,
        "after_shutdown": after_shutdown,
    }

    for name, callback in callbacks.items():
        if callback is not None and not callable(callback):
            raise TypeError(f"{name} must be callable")

    try:
        return create_scheduler_runtime_lifespan(
            before_start=before_start,
            after_start=after_start,
            before_shutdown=before_shutdown,
            after_shutdown=after_shutdown,
        )
    except Exception as exc:
        logger.exception(
            "Failed to create scheduler runtime lifespan"
        )
        raise SchedulerRuntimeLifespanIntegrationError(
            "Failed to create scheduler runtime lifespan"
        ) from exc


def register_scheduler_runtime_lifespan(
    app: FastAPI,
    lifespan: Callable[..., Any],
    *,
    replace: bool = False,
):
    """
    Register lifespan metadata on an already-constructed application.

    This does not modify FastAPI's active lifespan configuration.
    The supplied lifespan must already have been passed to
    FastAPI(lifespan=...) during application construction.
    """

    _validate_app(app)

    if not callable(lifespan):
        raise TypeError("lifespan must be callable")

    if not isinstance(replace, bool):
        raise TypeError("replace must be a boolean")

    existing = getattr(
        app.state,
        SCHEDULER_RUNTIME_LIFESPAN_STATE_KEY,
        None,
    )

    if existing is not None and not replace:
        raise SchedulerRuntimeLifespanIntegrationError(
            "Scheduler runtime lifespan is already registered"
        )

    setattr(
        app.state,
        SCHEDULER_RUNTIME_LIFESPAN_STATE_KEY,
        lifespan,
    )

    logger.info("Scheduler runtime lifespan metadata registered")

    return lifespan


def get_scheduler_runtime_lifespan(
    app: FastAPI,
):
    """Return the registered scheduler runtime lifespan callable."""

    _validate_app(app)

    lifespan = getattr(
        app.state,
        SCHEDULER_RUNTIME_LIFESPAN_STATE_KEY,
        None,
    )

    if lifespan is None:
        raise SchedulerRuntimeLifespanIntegrationError(
            "Scheduler runtime lifespan is not registered"
        )

    if not callable(lifespan):
        raise SchedulerRuntimeLifespanIntegrationError(
            "Registered scheduler runtime lifespan is invalid"
        )

    return lifespan


def get_scheduler_runtime_lifespan_optional(
    app: FastAPI,
):
    """Return the registered lifespan callable or None."""

    _validate_app(app)

    lifespan = getattr(
        app.state,
        SCHEDULER_RUNTIME_LIFESPAN_STATE_KEY,
        None,
    )

    if lifespan is not None and not callable(lifespan):
        raise SchedulerRuntimeLifespanIntegrationError(
            "Registered scheduler runtime lifespan is invalid"
        )

    return lifespan


def is_scheduler_runtime_lifespan_registered(
    app: FastAPI,
) -> bool:
    """Check whether lifespan metadata is registered."""

    return get_scheduler_runtime_lifespan_optional(app) is not None


def remove_scheduler_runtime_lifespan(
    app: FastAPI,
):
    """
    Remove lifespan metadata from application state.

    This does not change the lifespan configured on the FastAPI
    application and does not stop the scheduler runtime.
    """

    _validate_app(app)

    lifespan = get_scheduler_runtime_lifespan(app)

    delattr(
        app.state,
        SCHEDULER_RUNTIME_LIFESPAN_STATE_KEY,
    )

    logger.info("Scheduler runtime lifespan metadata removed")

    return lifespan


def get_scheduler_runtime_lifespan_status(
    app: FastAPI,
) -> dict[str, Any]:
    """Return the runtime and lifespan registration status."""

    _validate_app(app)

    lifespan_registered = is_scheduler_runtime_lifespan_registered(
        app
    )

    runtime_installed = False

    try:
        get_scheduler_runtime(app)
        runtime_installed = True
    except SchedulerRuntimeIntegrationError:
        pass

    return {
        "lifespan_registered": lifespan_registered,
        "runtime_installed": runtime_installed,
        "ready_for_application_startup": runtime_installed,
    }
