
"""Integrated cancellation-aware scheduler health API lifespan.

This module composes:
- The existing bootstrap health API installation.
- The cancellation-aware cleanup coordinator.
- Existing application lifespan contexts.

The original lifespan implementation remains available in
integration_bootstrap_health_api_lifespan.py.
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
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
    CleanupExecutionError,
    CleanupFailure,
    CleanupReport,
    execute_cleanup_resiliently,
    raise_for_cleanup_report,
)

logger = logging.getLogger(__name__)


class BootstrapHealthLifespanIntegrationError(RuntimeError):
    """Raised when integrated lifespan initialization fails."""


class BootstrapHealthLifespanShutdownError(RuntimeError):
    """Raised when integrated lifespan shutdown fails."""

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
    """Resolve an existing lifespan factory."""

    context = factory(app)

    if inspect.isawaitable(context):
        context = await context

    if not (
        hasattr(context, "__aenter__")
        and hasattr(context, "__aexit__")
    ):
        raise TypeError(
            "existing_lifespan must return an async context manager"
        )

    return context


async def _install_integration(
    app: FastAPI,
    service: SchedulingBootstrapHealthService | None,
) -> SchedulingBootstrapHealthAPIIntegration:
    """Install or reuse the combined health integration."""

    if is_bootstrap_health_api_integration_installed(app):
        integration = app.state.scheduling_bootstrap_health_api_integration

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


def create_integrated_bootstrap_health_lifespan(
    *,
    service: SchedulingBootstrapHealthService | None = None,
    existing_lifespan: LifespanFactory | None = None,
    before_start: LifespanCallback | None = None,
    after_start: LifespanCallback | None = None,
    before_shutdown: LifespanCallback | None = None,
    after_shutdown: LifespanCallback | None = None,
) -> LifespanFactory:
    """Create an integrated FastAPI lifespan.

    Shutdown order:
        1. before_shutdown callback
        2. after_shutdown callback
        3. existing application's lifespan exit

    The cleanup coordinator attempts every operation even when an earlier
    operation fails or raises cancellation.
    """

    if service is not None and not isinstance(
        service,
        SchedulingBootstrapHealthService,
    ):
        raise TypeError("service must be a SchedulingBootstrapHealthService")

    callbacks = (
        before_start,
        after_start,
        before_shutdown,
        after_shutdown,
    )

    if any(
        callback is not None and not callable(callback)
        for callback in callbacks
    ):
        raise TypeError("lifespan callbacks must be callable")

    if existing_lifespan is not None and not callable(existing_lifespan):
        raise TypeError("existing_lifespan must be callable")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if not isinstance(app, FastAPI):
            raise TypeError("app must be a FastAPI instance")

        existing_context = None
        primary_error: BaseException | None = None
        integration_installed = False

        try:
            if existing_lifespan is not None:
                existing_context = await _resolve_lifespan(
                    existing_lifespan,
                    app,
                )
                await existing_context.__aenter__()

            await _invoke_callback(before_start, app)

            integration = await _install_integration(app, service)
            integration_installed = True

            if not isinstance(
                integration,
                SchedulingBootstrapHealthAPIIntegration,
            ):
                raise BootstrapHealthLifespanIntegrationError(
                    "Health API installation returned an invalid integration"
                )

            await _invoke_callback(after_start, app)

            yield

        except BaseException as exc:
            primary_error = exc
            raise

        finally:
            operations: list[tuple[str, Callable[[], Any]]] = []

            if integration_installed:
                operations.append(
                    (
                        "before_shutdown",
                        lambda: _invoke_callback(before_shutdown, app),
                    )
                )

                operations.append(
                    (
                        "after_shutdown",
                        lambda: _invoke_callback(after_shutdown, app),
                    )
                )

            if existing_context is not None:
                operations.append(
                    (
                        "existing_lifespan_exit",
                        lambda: existing_context.__aexit__(
                            type(primary_error) if primary_error else None,
                            primary_error,
                            primary_error.__traceback__ if primary_error else None,
                        ),
                    )
                )

            if not operations:
                return

            report = await execute_cleanup_resiliently(operations)

            if primary_error is not None:
                if report.failures or report.cancellation is not None:
                    logger.error(
                        "Lifespan cleanup encountered errors while "
                        "preserving the primary application exception: %s",
                        report,
                    )

                # Do not replace the original application/startup exception.
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
    """Install the integrated lifespan on a FastAPI application.

    The returned lifespan must be supplied to FastAPI during application
    construction for normal lifespan execution. This helper assigns the
    router lifespan context for applications that have already been created.
    """

    if not isinstance(app, FastAPI):
        raise TypeError("app must be a FastAPI instance")

    lifespan = create_integrated_bootstrap_health_lifespan(**kwargs)

    app.router.lifespan_context = lifespan

    return lifespan
