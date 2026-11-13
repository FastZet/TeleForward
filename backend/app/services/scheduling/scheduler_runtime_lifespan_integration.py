
"""FastAPI integration helpers for the scheduler runtime lifespan."""

from __future__ import annotations

import logging
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

SCHEDULER_RUNTIME_LIFESPAN_FACTORY_STATE_KEY = (
    "scheduler_runtime_lifespan_factory"
)


class SchedulerRuntimeLifespanIntegrationError(RuntimeError):
    """Raised when scheduler runtime lifespan integration fails."""


def _validate_app(app: FastAPI) -> None:
    """Validate the FastAPI application."""

    if not isinstance(app, FastAPI):
        raise TypeError("app must be a FastAPI instance")


def install_scheduler_runtime_lifespan(
    app: FastAPI,
    *,
    before_start: Any | None = None,
    after_start: Any | None = None,
    before_shutdown: Any | None = None,
    after_shutdown: Any | None = None,
    replace: bool = False,
):
    """
    Create and register the scheduler runtime lifespan callable.

    The scheduler runtime must already be installed in app.state.

    This function stores the lifespan callable in application state.
    The caller must pass the returned callable to FastAPI during
    application construction:

        lifespan = install_scheduler_runtime_lifespan(
            app,
        )

        application = FastAPI(lifespan=lifespan)

    The app supplied to this function must be the same application
    instance that will be used by the lifespan.
    """

    _validate_app(app)

    if not isinstance(replace, bool):
        raise TypeError("replace must be a boolean")

    try:
        get_scheduler_runtime(app)
    except SchedulerRuntimeIntegrationError as exc:
        raise SchedulerRuntimeLifespanIntegrationError(
            "Install the scheduler runtime before its lifespan"
        ) from exc

    existing = getattr(
        app.state,
        SCHEDULER_RUNTIME_LIFESPAN_STATE_KEY,
        None,
    )

    if existing is not None and not replace:
        raise SchedulerRuntimeLifespanIntegrationError(
            "Scheduler runtime lifespan is already installed"
        )

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
        lifespan = create_scheduler_runtime_lifespan(
            before_start=before_start,
            after_start=after_start,
            before_shutdown=before_shutdown,
            after_shutdown=after_shutdown,
        )

        setattr(
            app.state,
            SCHEDULER_RUNTIME_LIFESPAN_STATE_KEY,
            lifespan,
        )

        setattr(
            app.state,
            SCHEDULER_RUNTIME_LIFESPAN_FACTORY_STATE_KEY,
            create_scheduler_runtime_lifespan,
        )

    except Exception as exc:
        logger.exception(
            "Failed to install scheduler runtime lifespan"
        )

        raise SchedulerRuntimeLifespanIntegrationError(
            "Failed to install scheduler runtime lifespan"
        ) from exc

    logger.info("Scheduler runtime lifespan registered")

    return lifespan


def get_scheduler_runtime_lifespan(app: FastAPI):
    """Return the registered scheduler runtime lifespan callable."""

    _validate_app(app)

    lifespan = getattr(
        app.state,
        SCHEDULER_RUNTIME_LIFESPAN_STATE_KEY,
        None,
    )

    if lifespan is None:
        raise SchedulerRuntimeLifespanIntegrationError(
            "Scheduler runtime lifespan is not installed"
        )

    if not callable(lifespan):
        raise SchedulerRuntimeLifespanIntegrationError(
            "Registered scheduler runtime lifespan is invalid"
        )

    return lifespan


def get_scheduler_runtime_lifespan_optional(
    app: FastAPI,
):
    """Return the lifespan callable or None when not installed."""

    _validate_app(app)

    lifespan = getattr(
        app.state,
        SCHEDULER_RUNTIME_LIFESPAN_STATE_KEY,
        None,
    )

    if lifespan is None:
        return None

    if not callable(lifespan):
        raise SchedulerRuntimeLifespanIntegrationError(
            "Registered scheduler runtime lifespan is invalid"
        )

    return lifespan


def is_scheduler_runtime_lifespan_installed(
    app: FastAPI,
) -> bool:
    """Check whether a scheduler runtime lifespan is registered."""

    return get_scheduler_runtime_lifespan_optional(app) is not None


def remove_scheduler_runtime_lifespan(
    app: FastAPI,
):
    """
    Remove lifespan registration metadata from application state.

    This does not alter an already-constructed FastAPI application's
    lifespan configuration and does not stop the scheduler runtime.

    It only removes the integration references stored by this module.
    """

    _validate_app(app)

    lifespan = get_scheduler_runtime_lifespan(app)

    delattr(
        app.state,
        SCHEDULER_RUNTIME_LIFESPAN_STATE_KEY,
    )

    if hasattr(
        app.state,
        SCHEDULER_RUNTIME_LIFESPAN_FACTORY_STATE_KEY,
    ):
        delattr(
            app.state,
            SCHEDULER_RUNTIME_LIFESPAN_FACTORY_STATE_KEY,
        )

    logger.info("Scheduler runtime lifespan registration removed")

    return lifespan


def get_scheduler_runtime_lifespan_status(
    app: FastAPI,
) -> dict[str, Any]:
    """Return the lifespan registration status."""

    _validate_app(app)

    installed = is_scheduler_runtime_lifespan_installed(app)

    runtime_installed = False

    try:
        get_scheduler_runtime(app)
        runtime_installed = True
    except SchedulerRuntimeIntegrationError:
        pass

    return {
        "lifespan_installed": installed,
        "runtime_installed": runtime_installed,
        "ready_for_application_startup": (
            installed and runtime_installed
        ),
    }
