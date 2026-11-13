
"""FastAPI application-state integration for SchedulerRuntime."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI

from app.services.scheduling.scheduler_lifecycle import (
    SchedulerLifecycleState,
)
from app.services.scheduling.scheduler_runtime import (
    SchedulerRuntime,
)

logger = logging.getLogger(__name__)

SCHEDULER_RUNTIME_STATE_KEY = "scheduler_runtime"


class SchedulerRuntimeIntegrationError(RuntimeError):
    """Raised when scheduler runtime integration fails."""


def _validate_app(app: FastAPI) -> None:
    """Validate the application object."""

    if not isinstance(app, FastAPI):
        raise TypeError("app must be a FastAPI instance")


def install_scheduler_runtime(
    app: FastAPI,
    runtime: SchedulerRuntime,
    *,
    replace: bool = False,
) -> SchedulerRuntime:
    """
    Install a scheduler runtime in FastAPI application state.

    Installation does not start the runtime. The application lifespan
    should manage its startup and shutdown.

    Args:
        app: FastAPI application.
        runtime: Runtime instance to install.
        replace: Whether to replace an existing runtime.

    Returns:
        The installed runtime.

    Raises:
        TypeError: If the application or runtime is invalid.
        SchedulerRuntimeIntegrationError: If installation is rejected.
    """

    _validate_app(app)

    if not isinstance(runtime, SchedulerRuntime):
        raise TypeError("runtime must be a SchedulerRuntime instance")

    if not isinstance(replace, bool):
        raise TypeError("replace must be a boolean")

    existing = getattr(
        app.state,
        SCHEDULER_RUNTIME_STATE_KEY,
        None,
    )

    if existing is not None:
        if existing is runtime:
            return runtime

        if not replace:
            raise SchedulerRuntimeIntegrationError(
                "A scheduler runtime is already installed"
            )

        existing_state = getattr(existing, "state", None)

        if existing_state != SchedulerLifecycleState.STOPPED:
            raise SchedulerRuntimeIntegrationError(
                "Cannot replace a scheduler runtime that is not stopped"
            )

    setattr(
        app.state,
        SCHEDULER_RUNTIME_STATE_KEY,
        runtime,
    )

    logger.info("Scheduler runtime installed")

    return runtime


def get_scheduler_runtime(app: FastAPI) -> SchedulerRuntime:
    """
    Retrieve the installed scheduler runtime.

    Raises:
        SchedulerRuntimeIntegrationError: If no runtime is installed.
    """

    _validate_app(app)

    runtime = getattr(
        app.state,
        SCHEDULER_RUNTIME_STATE_KEY,
        None,
    )

    if runtime is None:
        raise SchedulerRuntimeIntegrationError(
            "Scheduler runtime is not installed"
        )

    if not isinstance(runtime, SchedulerRuntime):
        raise SchedulerRuntimeIntegrationError(
            "Installed scheduler runtime has an invalid type"
        )

    return runtime


def get_scheduler_runtime_optional(
    app: FastAPI,
) -> SchedulerRuntime | None:
    """Retrieve the installed runtime, returning None when absent."""

    _validate_app(app)

    runtime = getattr(
        app.state,
        SCHEDULER_RUNTIME_STATE_KEY,
        None,
    )

    if runtime is None:
        return None

    if not isinstance(runtime, SchedulerRuntime):
        raise SchedulerRuntimeIntegrationError(
            "Installed scheduler runtime has an invalid type"
        )

    return runtime


def is_scheduler_runtime_installed(app: FastAPI) -> bool:
    """Check whether a scheduler runtime is installed."""

    return get_scheduler_runtime_optional(app) is not None


def get_scheduler_runtime_status(app: FastAPI) -> dict[str, Any]:
    """Return the installed runtime's status snapshot."""

    runtime = get_scheduler_runtime(app)

    try:
        return runtime.get_status()

    except Exception as exc:
        logger.exception("Failed to retrieve scheduler runtime status")

        raise SchedulerRuntimeIntegrationError(
            "Failed to retrieve scheduler runtime status"
        ) from exc


async def start_scheduler_runtime(app: FastAPI) -> SchedulerRuntime:
    """
    Start the installed scheduler runtime.

    This helper is intended for use by the application lifespan.
    """

    runtime = get_scheduler_runtime(app)

    try:
        await runtime.start()

    except Exception as exc:
        logger.exception("Failed to start installed scheduler runtime")

        raise SchedulerRuntimeIntegrationError(
            "Failed to start scheduler runtime"
        ) from exc

    return runtime


async def shutdown_scheduler_runtime(app: FastAPI) -> SchedulerRuntime:
    """
    Shut down the installed scheduler runtime.

    This helper is intended for use by the application lifespan.
    """

    runtime = get_scheduler_runtime(app)

    try:
        await runtime.shutdown()

    except Exception as exc:
        logger.exception("Failed to shut down installed scheduler runtime")

        raise SchedulerRuntimeIntegrationError(
            "Failed to shut down scheduler runtime"
        ) from exc

    return runtime


def remove_scheduler_runtime(
    app: FastAPI,
    *,
    require_stopped: bool = True,
) -> SchedulerRuntime:
    """
    Remove the installed scheduler runtime from application state.

    By default, removal is permitted only when the runtime is stopped.

    This function does not shut down the runtime automatically.
    """

    _validate_app(app)

    if not isinstance(require_stopped, bool):
        raise TypeError("require_stopped must be a boolean")

    runtime = get_scheduler_runtime(app)

    if (
        require_stopped
        and runtime.state != SchedulerLifecycleState.STOPPED
    ):
        raise SchedulerRuntimeIntegrationError(
            "Cannot remove a scheduler runtime that is not stopped"
        )

    delattr(
        app.state,
        SCHEDULER_RUNTIME_STATE_KEY,
    )

    logger.info("Scheduler runtime removed")

    return runtime


def get_scheduler_runtime_state(app: FastAPI) -> SchedulerLifecycleState:
    """Return the installed runtime's lifecycle state."""

    runtime = get_scheduler_runtime(app)
    return runtime.state


def is_scheduler_runtime_running(app: FastAPI) -> bool:
    """Return whether the installed runtime is fully running."""

    runtime = get_scheduler_runtime_optional(app)

    if runtime is None:
        return False

    return runtime.is_running
