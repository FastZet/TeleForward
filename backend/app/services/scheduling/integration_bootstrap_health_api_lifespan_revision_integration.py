
"""Hardened integrated scheduler health API lifespan.

Provides explicit lifecycle tracking, exception preservation, and
cancellation-aware cleanup for the bootstrap health API integration.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from enum import StrEnum
from types import TracebackType
from typing import Any

from fastapi import FastAPI

from app.services.scheduling.integration_bootstrap_health import (
    SchedulingBootstrapHealthService,
)
from app.services.scheduling.integration_bootstrap_health_api_integration import (
    SchedulingBootstrapHealthAPIIntegration,
    install_bootstrap_health_api_integration,
    is_bootstrap_health_api_integration_installed,
)
from app.services.scheduling.integration_bootstrap_health_api_lifespan import (
    LifespanCallback,
    LifespanFactory,
)
from app.services.scheduling.integration_bootstrap_health_api_lifespan_revision import (
    CleanupCancelledError,
    CleanupReport,
    execute_cleanup_resiliently,
)

logger = logging.getLogger(__name__)


class BootstrapHealthLifespanIntegrationError(RuntimeError):
    """Raised when integrated lifespan initialization fails."""


class BootstrapHealthLifespanShutdownError(RuntimeError):
    """Raised when one or more shutdown operations fail."""

    def __init__(self, report: CleanupReport) -> None:
        if not isinstance(report, CleanupReport):
            raise TypeError("report must be a CleanupReport")

        if not report.failures:
            raise ValueError("report must contain cleanup failures")

        if report.cancellation is not None:
            raise ValueError(
                "shutdown error cannot represent cancellation"
            )

        self.report = report

        details = "; ".join(
            f"{failure.operation}: {failure.error}"
            for failure in report.failures
        )

        super().__init__(f"Lifespan shutdown failed: {details}")


class LifespanPhase(StrEnum):
    """Observable phases of the integrated lifespan."""

    INITIALISING = "initialising"
    EXISTING_LIFESPAN_ENTERED = "existing_lifespan_entered"
    INTEGRATION_INSTALLED = "integration_installed"
    RUNNING = "running"
    CLEANING_UP = "cleaning_up"
    STOPPED = "stopped"
    FAILED = "failed"


@dataclass(slots=True)
class LifespanExecutionState:
    """Internal state for one lifespan execution."""

    phase: LifespanPhase = LifespanPhase.INITIALISING
    existing_context_entered: bool = False
    integration_installed: bool = False
    primary_error: BaseException | None = None
    primary_traceback: TracebackType | None = None
    exception_suppressed: bool = False

    def set_primary_error(self, error: BaseException) -> None:
        self.primary_error = error
        self.primary_traceback = error.__traceback__


async def _invoke_callback(
    callback: LifespanCallback | None,
    app: FastAPI,
) -> None:
    """Invoke an optional synchronous or asynchronous callback."""

    if callback is None:
        return

    result = callback(app)

    if inspect.isawaitable(result):
        await result


async def _resolve_lifespan(
    factory: LifespanFactory,
    app: FastAPI,
) -> Any:
    """Resolve and validate an existing async lifespan context."""

    context = factory(app)

    if inspect.isawaitable(context):
        context = await context

    if not callable(getattr(context, "__aenter__", None)):
        raise TypeError(
            "existing_lifespan must return an async context manager"
        )

    if not callable(getattr(context, "__aexit__", None)):
        raise TypeError(
            "existing_lifespan must return an async context manager"
        )

    return context


async def _install_integration(
    app: FastAPI,
    service: SchedulingBootstrapHealthService | None,
) -> SchedulingBootstrapHealthAPIIntegration:
    """Install or reuse the bootstrap health API integration."""

    if is_bootstrap_health_api_integration_installed(app):
        integration = (
            app.state.scheduling_bootstrap_health_api_integration
        )

        if not isinstance(
            integration,
            SchedulingBootstrapHealthAPIIntegration,
        ):
            raise BootstrapHealthLifespanIntegrationError(
                "Registered bootstrap health integration has an invalid type"
            )

        return integration

    return install_bootstrap_health_api_integration(
        app,
        service=service,
    )


def _validate_arguments(
    service: SchedulingBootstrapHealthService | None,
    existing_lifespan: LifespanFactory | None,
    callbacks: tuple[LifespanCallback | None, ...],
) -> None:
    """Validate lifespan factory arguments."""

    if service is not None and not isinstance(
        service,
        SchedulingBootstrapHealthService,
    ):
        raise TypeError(
            "service must be a SchedulingBootstrapHealthService"
        )

    if (
        existing_lifespan is not None
        and not callable(existing_lifespan)
    ):
        raise TypeError("existing_lifespan must be callable")

    if any(
        callback is not None and not callable(callback)
        for callback in callbacks
    ):
        raise TypeError("lifespan callbacks must be callable")


def _attach_cleanup_diagnostics(
    primary_error: BaseException,
    report: CleanupReport,
) -> None:
    """Attach secondary cleanup failures to the primary exception."""

    if not report.failures and report.cancellation is None:
        return

    details = [
        (
            f"{failure.operation}: "
            f"{type(failure.error).__name__}: {failure.error}"
        )
        for failure in report.failures
    ]

    if report.cancellation is not None:
        details.append(
            f"Cleanup cancellation: {report.cancellation!r}"
        )

    diagnostic = (
        "Secondary lifespan cleanup diagnostics: "
        + "; ".join(details)
    )

    add_note = getattr(primary_error, "add_note", None)

    if callable(add_note):
        add_note(diagnostic)

    logger.error(
        "%s",
        diagnostic,
        exc_info=(
            type(primary_error),
            primary_error,
            primary_error.__traceback__,
        ),
    )


async def _exit_existing_lifespan(
    context: Any,
    state: LifespanExecutionState,
) -> None:
    """Exit the existing lifespan and record suppression semantics."""

    error = state.primary_error

    result = await context.__aexit__(
        type(error) if error is not None else None,
        error,
        state.primary_traceback if error is not None else None,
    )

    state.exception_suppressed = bool(result)


def create_integrated_bootstrap_health_lifespan(
    *,
    service: SchedulingBootstrapHealthService | None = None,
    existing_lifespan: LifespanFactory | None = None,
    before_start: LifespanCallback | None = None,
    after_start: LifespanCallback | None = None,
    before_shutdown: LifespanCallback | None = None,
    after_shutdown: LifespanCallback | None = None,
) -> LifespanFactory:
    """Create the integrated bootstrap health API lifespan.

    Startup:
        1. Resolve and enter the existing lifespan.
        2. Execute before_start.
        3. Install or reuse the health API integration.
        4. Execute after_start.
        5. Yield control to FastAPI.

    Shutdown:
        1. Execute before_shutdown if integration was installed.
        2. Execute after_shutdown if integration was installed.
        3. Exit the existing lifespan if successfully entered.

    A primary cancellation is never suppressed by an existing lifespan.
    Ordinary exceptions may be suppressed by the existing lifespan.
    """

    _validate_arguments(
        service,
        existing_lifespan,
        (
            before_start,
            after_start,
            before_shutdown,
            after_shutdown,
        ),
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if not isinstance(app, FastAPI):
            raise TypeError("app must be a FastAPI instance")

        state = LifespanExecutionState()
        existing_context: Any | None = None

        try:
            if existing_lifespan is not None:
                existing_context = await _resolve_lifespan(
                    existing_lifespan,
                    app,
                )

                # Mark ownership only after successful entry.
                await existing_context.__aenter__()
                state.existing_context_entered = True
                state.phase = LifespanPhase.EXISTING_LIFESPAN_ENTERED

            await _invoke_callback(before_start, app)

            integration = await _install_integration(app, service)

            if not isinstance(
                integration,
                SchedulingBootstrapHealthAPIIntegration,
            ):
                raise BootstrapHealthLifespanIntegrationError(
                    "Health API installation returned an invalid integration"
                )

            state.integration_installed = True
            state.phase = LifespanPhase.INTEGRATION_INSTALLED

            await _invoke_callback(after_start, app)

            state.phase = LifespanPhase.RUNNING

            yield

        except BaseException as exc:
            state.set_primary_error(exc)
            state.phase = LifespanPhase.FAILED

        state.phase = LifespanPhase.CLEANING_UP

        operations: list[tuple[str, Callable[[], Any]]] = []

        if state.integration_installed:
            operations.extend(
                [
                    (
                        "before_shutdown",
                        lambda: _invoke_callback(before_shutdown, app),
                    ),
                    (
                        "after_shutdown",
                        lambda: _invoke_callback(after_shutdown, app),
                    ),
                ]
            )

        if state.existing_context_entered and existing_context is not None:
            operations.append(
                (
                    "existing_lifespan_exit",
                    lambda: _exit_existing_lifespan(
                        existing_context,
                        state,
                    ),
                )
            )

        report: CleanupReport | None = None

        if operations:
            report = await execute_cleanup_resiliently(operations)

        primary_error = state.primary_error

        if isinstance(primary_error, asyncio.CancelledError):
            if report is not None:
                _attach_cleanup_diagnostics(primary_error, report)

            state.phase = LifespanPhase.STOPPED
            raise primary_error.with_traceback(state.primary_traceback)

        if primary_error is not None and not state.exception_suppressed:
            if report is not None:
                _attach_cleanup_diagnostics(primary_error, report)

            state.phase = LifespanPhase.FAILED
            raise primary_error.with_traceback(state.primary_traceback)

        if report is not None:
            if report.cancellation is not None:
                state.phase = LifespanPhase.STOPPED
                raise CleanupCancelledError(report) from report.cancellation

            if report.failures:
                state.phase = LifespanPhase.FAILED

                raise BootstrapHealthLifespanShutdownError(
                    report
                ) from report.failures[0].error

        state.phase = LifespanPhase.STOPPED

    return lifespan


def install_integrated_bootstrap_health_lifespan(
    app: FastAPI,
    **kwargs: Any,
) -> LifespanFactory:
    """Assign the integrated lifespan to an existing FastAPI application.

    Prefer passing the returned lifespan to FastAPI during construction.
    This helper changes the router lifespan context and must be called
    before the application starts serving requests.
    """

    if not isinstance(app, FastAPI):
        raise TypeError("app must be a FastAPI instance")

    lifespan = create_integrated_bootstrap_health_lifespan(**kwargs)

    app.router.lifespan_context = lifespan

    return lifespan
