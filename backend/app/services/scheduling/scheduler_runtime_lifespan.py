
"""FastAPI lifespan integration for SchedulerRuntime."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator, Callable

from fastapi import FastAPI

from app.services.scheduling.scheduler_runtime_integration import (
    SchedulerRuntimeIntegrationError,
    get_scheduler_runtime,
    start_scheduler_runtime,
    shutdown_scheduler_runtime,
)

logger = logging.getLogger(__name__)


class SchedulerRuntimeLifespanError(RuntimeError):
    """Raised when scheduler runtime lifespan management fails."""


def create_scheduler_runtime_lifespan(
    *,
    before_start: Callable[[FastAPI], object] | None = None,
    after_start: Callable[[FastAPI], object] | None = None,
    before_shutdown: Callable[[FastAPI], object] | None = None,
    after_shutdown: Callable[[FastAPI], object] | None = None,
):
    """
    Create a FastAPI lifespan context manager for SchedulerRuntime.

    Startup sequence:
        1. Verify that a runtime is installed.
        2. Execute before_start callback.
        3. Start the scheduler runtime.
        4. Execute after_start callback.
        5. Yield control to the application.

    Shutdown sequence:
        1. Execute before_shutdown callback.
        2. Shut down the scheduler runtime.
        3. Execute after_shutdown callback.

    If application execution fails, shutdown is still attempted.
    Shutdown failures during an existing application exception are logged
    without replacing the original exception.

    Callbacks may be synchronous or asynchronous.
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

    async def invoke_callback(
        callback: Callable[[FastAPI], object] | None,
        app: FastAPI,
    ) -> None:
        """Invoke a synchronous or asynchronous lifespan callback."""

        if callback is None:
            return

        import inspect

        result = callback(app)

        if inspect.isawaitable(result):
            await result

    async def perform_shutdown(app: FastAPI) -> None:
        """Execute the complete shutdown sequence."""

        await invoke_callback(before_shutdown, app)

        await shutdown_scheduler_runtime(app)

        await invoke_callback(after_shutdown, app)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Manage scheduler runtime startup and shutdown."""

        if not isinstance(app, FastAPI):
            raise TypeError("app must be a FastAPI instance")

        # Fail early if the runtime has not been installed.
        get_scheduler_runtime(app)

        try:
            await invoke_callback(before_start, app)

            await start_scheduler_runtime(app)

            await invoke_callback(after_start, app)

        except BaseException as exc:
            logger.exception(
                "Scheduler runtime application startup failed"
            )

            # If the runtime started but a later startup callback failed,
            # attempt to shut it down before propagating the error.
            try:
                runtime = get_scheduler_runtime(app)

                if runtime.is_running or (
                    runtime.lifecycle.manager_started
                    or runtime.lifecycle.monitor_started
                ):
                    await shutdown_scheduler_runtime(app)

            except BaseException:
                logger.exception(
                    "Scheduler runtime cleanup failed during startup rollback"
                )

            if isinstance(exc, Exception):
                raise SchedulerRuntimeLifespanError(
                    "Scheduler runtime startup failed"
                ) from exc

            raise

        try:
            yield

        except BaseException:
            # Preserve the original application exception or cancellation.
            # Shutdown errors are logged rather than replacing that exception.
            try:
                await perform_shutdown(app)

            except BaseException:
                logger.exception(
                    "Scheduler runtime shutdown failed after "
                    "application execution error"
                )

            raise

        else:
            # On normal application shutdown, propagate cleanup failures
            # so that the application server can report them.
            try:
                await perform_shutdown(app)

            except asyncio.CancelledError:
                logger.warning(
                    "Scheduler runtime shutdown was cancelled"
                )
                raise

            except Exception as exc:
                logger.exception(
                    "Scheduler runtime shutdown failed"
                )

                raise SchedulerRuntimeLifespanError(
                    "Scheduler runtime shutdown failed"
                ) from exc

    return lifespan
