
"""FastAPI lifespan management for the scheduler runtime."""

from __future__ import annotations

import inspect
import logging
from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI

from app.services.scheduling.scheduler_runtime_integration import (
    SchedulerRuntimeIntegrationError,
    get_scheduler_runtime,
)

logger = logging.getLogger(__name__)

LifespanCallback = Callable[[FastAPI], Any]


class SchedulerRuntimeLifespanError(RuntimeError):
    """Raised when scheduler runtime lifespan operations fail."""


async def _invoke_callback(
    callback: LifespanCallback | None,
    app: FastAPI,
    callback_name: str,
) -> None:
    """Invoke a synchronous or asynchronous lifespan callback."""

    if callback is None:
        return

    try:
        result = callback(app)

        if inspect.isawaitable(result):
            await result

    except BaseException:
        logger.exception(
            "Scheduler lifespan callback failed: %s",
            callback_name,
        )
        raise


async def _best_effort_runtime_shutdown(
    runtime: Any,
    *,
    reason: str,
) -> None:
    """Attempt runtime shutdown without replacing an existing error."""

    try:
        await runtime.shutdown()

    except BaseException:
        logger.exception(
            "Scheduler runtime rollback failed during %s",
            reason,
        )


async def _shutdown_runtime(
    runtime: Any,
    app: FastAPI,
    *,
    before_shutdown: LifespanCallback | None,
    after_shutdown: LifespanCallback | None,
) -> None:
    """
    Execute every shutdown operation, even when an earlier one fails.

    The first failure is propagated after all shutdown operations
    have been attempted. Additional failures are logged.
    """

    failures: list[BaseException] = []

    operations = (
        (
            "before_shutdown",
            lambda: _invoke_callback(
                before_shutdown,
                app,
                "before_shutdown",
            ),
        ),
        (
            "runtime_shutdown",
            runtime.shutdown,
        ),
        (
            "after_shutdown",
            lambda: _invoke_callback(
                after_shutdown,
                app,
                "after_shutdown",
            ),
        ),
    )

    for operation_name, operation in operations:
        try:
            result = operation()

            if inspect.isawaitable(result):
                await result

        except BaseException as exc:
            failures.append(exc)

            logger.exception(
                "Scheduler shutdown operation failed: %s",
                operation_name,
            )

    if failures:
        first_failure = failures[0]

        if len(failures) > 1:
            logger.error(
                "Scheduler shutdown encountered %d failures",
                len(failures),
            )

        if isinstance(first_failure, Exception):
            raise SchedulerRuntimeLifespanError(
                "One or more scheduler shutdown operations failed"
            ) from first_failure

        # Preserve cancellation and other BaseException subclasses.
        raise first_failure


def create_scheduler_runtime_lifespan(
    *,
    before_start: LifespanCallback | None = None,
    after_start: LifespanCallback | None = None,
    before_shutdown: LifespanCallback | None = None,
    after_shutdown: LifespanCallback | None = None,
):
    """
    Create an asynchronous FastAPI lifespan for SchedulerRuntime.

    The runtime must be installed on app.state before application
    startup.

    Startup:
        1. before_start callback
        2. scheduler runtime start
        3. after_start callback

    Shutdown:
        1. before_shutdown callback
        2. scheduler runtime shutdown
        3. after_shutdown callback

    Every shutdown operation is attempted even if an earlier
    shutdown operation fails.
    """

    callbacks = {
        "before_start": before_start,
        "after_start": after_start,
        "before_shutdown": before_shutdown,
        "after_shutdown": after_shutdown,
    }

    for name, callback in callbacks.items():
        if callback is not None and not callable(callback):
            raise TypeError(f"{name} must be callable or None")

    @asynccontextmanager
    async def scheduler_runtime_lifespan(
        app: FastAPI,
    ) -> AsyncIterator[None]:
        if not isinstance(app, FastAPI):
            raise TypeError("app must be a FastAPI instance")

        try:
            runtime = get_scheduler_runtime(app)
        except SchedulerRuntimeIntegrationError as exc:
            raise SchedulerRuntimeLifespanError(
                "Scheduler runtime is not installed on the application"
            ) from exc

        startup_attempted = False

        try:
            await _invoke_callback(
                before_start,
                app,
                "before_start",
            )

            # Set before invocation because startup may partially
            # initialise resources before raising an exception.
            startup_attempted = True
            await runtime.start()

            await _invoke_callback(
                after_start,
                app,
                "after_start",
            )

        except BaseException:
            if startup_attempted:
                await _best_effort_runtime_shutdown(
                    runtime,
                    reason="startup failure",
                )

            raise

        try:
            yield

        except BaseException:
            # Preserve the original application exception or
            # cancellation if shutdown also encounters failures.
            try:
                await _shutdown_runtime(
                    runtime,
                    app,
                    before_shutdown=before_shutdown,
                    after_shutdown=after_shutdown,
                )
            except BaseException:
                logger.exception(
                    "Scheduler shutdown failed while preserving "
                    "an application exception"
                )

            raise

        else:
            await _shutdown_runtime(
                runtime,
                app,
                before_shutdown=before_shutdown,
                after_shutdown=after_shutdown,
            )

    return scheduler_runtime_lifespan
