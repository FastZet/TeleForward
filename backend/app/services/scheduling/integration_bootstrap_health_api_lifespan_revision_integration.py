
"""Hardened integrated scheduler health API lifespan.

Composes the bootstrap health API integration with an existing FastAPI
lifespan and cancellation-aware cleanup.

Exception policy:
- Preserve primary application and startup exceptions.
- Respect ordinary exception suppression by existing lifespan contexts.
- Never allow an existing lifespan to suppress primary cancellation.
- Attempt all registered shutdown operations.
- Retain cleanup failures and cancellation diagnostics.
- Do not replace a primary exception with secondary cleanup failures.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
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
    """Resolve and validate an existing lifespan context manager."""

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
    """Install or reuse the combined bootstrap health integration."""

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

    details: list[str] = []

    for failure in report.failures:
        details.append(
            f"{failure.operation}: "
            f"{type(failure.error).__name__}: {failure.error}"
        )

    if report.cancellation is not None:
        details.append(
            "Cleanup cancellation: "
            f"{report.cancellation!r}"
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

    Startup order:
        1. Enter existing application lifespan.
        2. Run before_start.
        3. Install or reuse the bootstrap health API integration.
        4. Run after_start.
        5. Yield control to the application.

    Shutdown order:
        1. Run before_shutdown if integration was installed.
        2. Run after_shutdown if integration was installed.
        3. Exit the existing application lifespan if entered.

    An existing lifespan can suppress ordinary exceptions. It cannot
    suppress the primary application cancellation.
    """

    callbacks = (
        before_start,
        after_start,
        before_shutdown,
        after_shutdown,
    )

    _validate_arguments(
        service,
        existing_lifespan,
        callbacks,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if not isinstance(app, FastAPI):
            raise TypeError("app must be a FastAPI instance")

        existing_context: Any | None = None
        existing_context_entered = False
        integration_installed = False

        primary_error: BaseException | None = None
        primary_traceback: TracebackType | None = None
        exception_suppressed = False

        try:
            if existing_lifespan is not None:
                existing_context = await _resolve_lifespan(
                    existing_lifespan,
                    app,
                )

                await existing_context.__aenter__()
                existing_context_entered = True

            await _invoke_callback(before_start, app)

            integration = await _install_integration(app, service)

            if not isinstance(
                integration,
                SchedulingBootstrapHealthAPIIntegration,
            ):
                raise BootstrapHealthLifespanIntegrationError(
                    "Health API installation returned an invalid integration"
                )

            integration_installed = True

            await _invoke_callback(after_start, app)

            yield

        except BaseException as exc:
            primary_error = exc
            primary_traceback = exc.__traceback__

        operations: list[tuple[str, Callable[[], Any]]] = []

        if integration_installed:
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

        if existing_context_entered:

            async def exit_existing_lifespan() -> None:
                nonlocal exception_suppressed

                if existing_context is None:
                    return

                error = primary_error

                result = await existing_context.__aexit__(
                    type(error) if error is not None else None,
                    error,
                    primary_traceback if error is not None else None,
                )

                exception_suppressed = bool(result)

            operations.append(
                (
                    "existing_lifespan_exit",
                    exit_existing_lifespan,
                )
            )

        report: CleanupReport | None = None

        if operations:
            report = await execute_cleanup_resiliently(operations)

        # Cancellation is never suppressible by an existing lifespan.
        if isinstance(primary_error, asyncio.CancelledError):
            if report is not None:
                _attach_cleanup_diagnostics(primary_error, report)

            raise primary_error.with_traceback(primary_traceback)

        # Ordinary exceptions may be suppressed by the existing lifespan.
        if primary_error is not None and not exception_suppressed:
            if report is not None:
                _attach_cleanup_diagnostics(primary_error, report)

            raise primary_error.with_traceback(primary_traceback)

        # No primary exception remains to preserve.
        if report is None:
            return

        if report.cancellation is not None:
            raise CleanupCancelledError(report) from report.cancellation

        if report.failures:
            raise BootstrapHealthLifespanShutdownError(report) from (
                report.failures[0].error
            )

    return lifespan


def install_integrated_bootstrap_health_lifespan(
    app: FastAPI,
    **kwargs: Any,
) -> LifespanFactory:
    """Assign the integrated lifespan to an existing FastAPI application.

    Prefer passing the returned lifespan to FastAPI during application
    construction. This helper changes the router lifespan context and must
    be called before the application starts serving requests.
    """

    if not isinstance(app, FastAPI):
        raise TypeError("app must be a FastAPI instance")

    lifespan = create_integrated_bootstrap_health_lifespan(**kwargs)

    app.router.lifespan_context = lifespan

    return lifespan
