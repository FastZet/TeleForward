
"""Observable and cancellation-aware integrated scheduler health lifespan.

Provides:
- Explicit lifecycle phase tracking.
- Existing application lifespan composition.
- Bootstrap health API installation.
- Cancellation-aware cleanup.
- Primary exception preservation.
- Structured cleanup diagnostics.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from types import TracebackType
from typing import Any

from fastapi import FastAPI

from app.services.scheduling.integration_bootstrap_health import (
    SchedulingBootstrapHealthService,
)
from app.services.scheduling.integration_bootstrap_health_api_integration import (
    BootstrapHealthAPIIntegration,
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

LIFESPAN_EXECUTION_STATE_KEY = (
    "scheduler_bootstrap_health_lifespan_execution"
)


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
    """Observable phases of one lifespan execution."""

    INITIALISING = "initialising"
    EXISTING_LIFESPAN_ENTERED = "existing_lifespan_entered"
    INTEGRATION_INSTALLED = "integration_installed"
    RUNNING = "running"
    CLEANING_UP = "cleaning_up"
    STOPPED = "stopped"
    CANCELLED = "cancelled"
    FAILED = "failed"


@dataclass(slots=True)
class LifespanExecutionState:
    """Mutable state retained while one lifespan is executing."""

    phase: LifespanPhase = LifespanPhase.INITIALISING
    phase_history: list[tuple[LifespanPhase, datetime]] = field(
        default_factory=list
    )
    existing_context_entered: bool = False
    integration_installed: bool = False
    exception_suppressed: bool = False
    primary_error_type: str | None = None
    primary_error_message: str | None = None
    cleanup_report: CleanupReport | None = None

    def __post_init__(self) -> None:
        self.phase_history.append(
            (self.phase, datetime.now(timezone.utc))
        )

    def transition(self, phase: LifespanPhase) -> None:
        """Record a lifecycle transition."""

        if not isinstance(phase, LifespanPhase):
            raise TypeError("phase must be a LifespanPhase")

        allowed_transitions = {
            LifespanPhase.INITIALISING: {
                LifespanPhase.EXISTING_LIFESPAN_ENTERED,
                LifespanPhase.INTEGRATION_INSTALLED,
                LifespanPhase.FAILED,
            },
            LifespanPhase.EXISTING_LIFESPAN_ENTERED: {
                LifespanPhase.INTEGRATION_INSTALLED,
                LifespanPhase.FAILED,
            },
            LifespanPhase.INTEGRATION_INSTALLED: {
                LifespanPhase.RUNNING,
                LifespanPhase.FAILED,
            },
            LifespanPhase.RUNNING: {
                LifespanPhase.CLEANING_UP,
                LifespanPhase.FAILED,
            },
            LifespanPhase.FAILED: {
                LifespanPhase.CLEANING_UP,
            },
            LifespanPhase.CLEANING_UP: {
                LifespanPhase.STOPPED,
                LifespanPhase.CANCELLED,
                LifespanPhase.FAILED,
            },
            LifespanPhase.STOPPED: set(),
            LifespanPhase.CANCELLED: set(),
        }

        if phase not in allowed_transitions[self.phase]:
            raise ValueError(
                f"Invalid lifespan phase transition: "
                f"{self.phase.value} -> {phase.value}"
            )

        self.phase = phase
        self.phase_history.append(
            (phase, datetime.now(timezone.utc))
        )

    def record_primary_error(self, error: BaseException) -> None:
        """Record primary exception information without retaining its object."""

        self.primary_error_type = type(error).__name__
        self.primary_error_message = str(error)

    def snapshot(self) -> LifespanExecutionStateSnapshot:
        """Return an immutable copy safe to expose through app.state."""

        return LifespanExecutionStateSnapshot(
            phase=self.phase,
            phase_history=tuple(self.phase_history),
            existing_context_entered=self.existing_context_entered,
            integration_installed=self.integration_installed,
            exception_suppressed=self.exception_suppressed,
            primary_error_type=self.primary_error_type,
            primary_error_message=self.primary_error_message,
            cleanup_report=self.cleanup_report,
        )


@dataclass(frozen=True, slots=True)
class LifespanExecutionStateSnapshot:
    """Immutable public snapshot of one lifespan execution."""

    phase: LifespanPhase
    phase_history: tuple[tuple[LifespanPhase, datetime], ...]
    existing_context_entered: bool
    integration_installed: bool
    exception_suppressed: bool
    primary_error_type: str | None
    primary_error_message: str | None
    cleanup_report: CleanupReport | None


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
) -> BootstrapHealthAPIIntegration:
    """Install or reuse the bootstrap health API integration."""

    if is_bootstrap_health_api_integration_installed(app):
        integration = (
            app.state.scheduling_bootstrap_health_api_integration
        )

        if not isinstance(
            integration,
            BootstrapHealthAPIIntegration,
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


def _publish_state(
    app: FastAPI,
    state: LifespanExecutionState,
) -> None:
    """Publish the current execution state on app.state."""

    try:
        setattr(
            app.state,
            LIFESPAN_EXECUTION_STATE_KEY,
            state.snapshot(),
        )
    except Exception:
        # Diagnostics must not make application startup or shutdown fail.
        logger.exception("Could not publish scheduler lifespan state")


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


def _record_report(
    state: LifespanExecutionState,
    report: CleanupReport | None,
) -> None:
    """Retain the final cleanup report."""

    state.cleanup_report = report


def create_integrated_bootstrap_health_lifespan(
    *,
    service: SchedulingBootstrapHealthService | None = None,
    existing_lifespan: LifespanFactory | None = None,
    before_start: LifespanCallback | None = None,
    after_start: LifespanCallback | None = None,
    before_shutdown: LifespanCallback | None = None,
    after_shutdown: LifespanCallback | None = None,
) -> LifespanFactory:
    """Create the observable integrated bootstrap health API lifespan.

    Startup order:
        1. Resolve and enter the existing lifespan.
        2. Execute before_start.
        3. Install or reuse the health API integration.
        4. Execute after_start.
        5. Enter RUNNING.

    Shutdown order:
        1. Execute before_shutdown if integration was installed.
        2. Execute after_shutdown if integration was installed.
        3. Exit the existing lifespan if successfully entered.

    Cancellation takes precedence over ordinary cleanup failures.
    Existing lifespan suppression applies only to ordinary exceptions,
    never to the primary application cancellation.
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

        previous_state = getattr(
            app.state,
            LIFESPAN_EXECUTION_STATE_KEY,
            None,
        )

        if (
            isinstance(
                previous_state,
                LifespanExecutionStateSnapshot,
            )
            and previous_state.phase
            not in {
                LifespanPhase.STOPPED,
                LifespanPhase.CANCELLED,
                LifespanPhase.FAILED,
            }
        ):
            raise BootstrapHealthLifespanIntegrationError(
                "A scheduler health lifespan is already executing "
                "for this application"
            )

        state = LifespanExecutionState()
        _publish_state(app, state)

        existing_context: Any | None = None
        primary_error: BaseException | None = None
        primary_traceback: TracebackType | None = None

        try:
            if existing_lifespan is not None:
                existing_context = await _resolve_lifespan(
                    existing_lifespan,
                    app,
                )

                await existing_context.__aenter__()
                state.existing_context_entered = True
                state.transition(
                    LifespanPhase.EXISTING_LIFESPAN_ENTERED
                )
                _publish_state(app, state)

            await _invoke_callback(before_start, app)

            integration = await _install_integration(app, service)

            if not isinstance(
                integration,
                BootstrapHealthAPIIntegration,
            ):
                raise BootstrapHealthLifespanIntegrationError(
                    "Health API installation returned an invalid integration"
                )

            state.integration_installed = True
            state.transition(LifespanPhase.INTEGRATION_INSTALLED)
            _publish_state(app, state)

            await _invoke_callback(after_start, app)

            state.transition(LifespanPhase.RUNNING)
            _publish_state(app, state)

            yield

        except BaseException as exc:
            primary_error = exc
            primary_traceback = exc.__traceback__
            state.record_primary_error(exc)
            state.transition(LifespanPhase.FAILED)
            _publish_state(app, state)

        state.transition(LifespanPhase.CLEANING_UP)
        _publish_state(app, state)

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

            async def exit_existing_lifespan() -> None:
                result = await existing_context.__aexit__(
                    type(primary_error) if primary_error is not None else None,
                    primary_error,
                    primary_traceback,
                )

                state.exception_suppressed = bool(result)

            operations.append(
                (
                    "existing_lifespan_exit",
                    exit_existing_lifespan,
                )
            )

        report: CleanupReport | None = None

        if operations:
            report = await execute_cleanup_resiliently(operations)

        _record_report(state, report)
        _publish_state(app, state)

        # Primary cancellation always wins, even if the existing lifespan
        # attempts to suppress it.
        if isinstance(primary_error, asyncio.CancelledError):
            if report is not None:
                _attach_cleanup_diagnostics(primary_error, report)

            state.transition(LifespanPhase.CANCELLED)
            _publish_state(app, state)

            raise primary_error.with_traceback(primary_traceback)

        # Preserve an unsuppressed primary exception.
        if primary_error is not None and not state.exception_suppressed:
            if report is not None:
                _attach_cleanup_diagnostics(primary_error, report)

            state.transition(LifespanPhase.FAILED)
            _publish_state(app, state)

            raise primary_error.with_traceback(primary_traceback)

        # If the existing lifespan suppressed the primary exception,
        # cleanup cancellation must still propagate.
        if report is not None and report.cancellation is not None:
            state.transition(LifespanPhase.CANCELLED)
            _publish_state(app, state)

            raise CleanupCancelledError(report) from report.cancellation

        if report is not None and report.failures:
            state.transition(LifespanPhase.FAILED)
            _publish_state(app, state)

            raise BootstrapHealthLifespanShutdownError(
                report
            ) from report.failures[0].error

        state.transition(LifespanPhase.STOPPED)
        _publish_state(app, state)

    return lifespan


def get_lifespan_execution_state(
    app: FastAPI,
) -> LifespanExecutionStateSnapshot | None:
    """Return the latest lifespan execution state, if available."""

    if not isinstance(app, FastAPI):
        raise TypeError("app must be a FastAPI instance")

    state = getattr(
        app.state,
        LIFESPAN_EXECUTION_STATE_KEY,
        None,
    )

    if state is not None and not isinstance(
        state,
        LifespanExecutionStateSnapshot,
    ):
        raise BootstrapHealthLifespanIntegrationError(
            "Stored lifespan execution state has an invalid type"
        )

    return state


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
