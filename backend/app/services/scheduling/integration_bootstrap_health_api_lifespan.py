
"""Resilient FastAPI lifespan integration for scheduling bootstrap health."""

from __future__ import annotations

import asyncio
import inspect
import logging

from collections.abc import (
    AsyncIterator,
    Awaitable,
    Callable,
)
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI

from app.services.scheduling.integration_bootstrap import (
    SchedulingIntegrationBootstrap,
)
from app.services.scheduling.integration_bootstrap_health import (
    SchedulingBootstrapHealthService,
)
from app.services.scheduling.integration_bootstrap_health_api_integration import (
    BootstrapHealthAPIIntegration,
    get_bootstrap_health_api_integration_optional,
    install_bootstrap_health_api_integration,
)


logger = logging.getLogger(__name__)

LifespanCallback = Callable[
    [FastAPI],
    Any | Awaitable[Any],
]

LifespanFactory = Callable[[FastAPI], Any]

ExistingLifespan = Callable[
    [FastAPI],
    Any,
]


class BootstrapHealthLifespanError(RuntimeError):
    """Raised when bootstrap health lifespan integration fails."""


def _validate_app(app: FastAPI) -> None:
    if not isinstance(app, FastAPI):
        raise TypeError("app must be a FastAPI instance")


def _validate_callback(
    callback: LifespanCallback | None,
    name: str,
) -> None:
    if callback is not None and not callable(callback):
        raise TypeError(f"{name} must be callable")


async def _invoke_callback(
    callback: LifespanCallback | None,
    app: FastAPI,
) -> None:
    """Invoke a synchronous or asynchronous lifecycle callback."""
    if callback is None:
        return

    result = callback(app)

    if inspect.isawaitable(result):
        await result


async def _run_cleanup_steps(
    app: FastAPI,
    *,
    before_shutdown: LifespanCallback | None,
    after_shutdown: LifespanCallback | None,
    existing_context: Any | None,
    existing_context_entered: bool,
    primary_error: BaseException | None,
) -> list[BaseException]:
    """Attempt every shutdown operation and collect its failures."""
    errors: list[BaseException] = []

    try:
        await _invoke_callback(before_shutdown, app)
    except BaseException as exc:
        errors.append(exc)
        logger.error(
            "Bootstrap health before-shutdown callback failed",
            exc_info=(type(exc), exc, exc.__traceback__),
        )

    try:
        await _invoke_callback(after_shutdown, app)
    except BaseException as exc:
        errors.append(exc)
        logger.error(
            "Bootstrap health after-shutdown callback failed",
            exc_info=(type(exc), exc, exc.__traceback__),
        )

    if existing_context_entered and existing_context is not None:
        try:
            await existing_context.__aexit__(
                type(primary_error) if primary_error is not None else None,
                primary_error,
                (
                    primary_error.__traceback__
                    if primary_error is not None
                    else None
                ),
            )
        except BaseException as exc:
            errors.append(exc)
            logger.error(
                "Existing application lifespan shutdown failed",
                exc_info=(type(exc), exc, exc.__traceback__),
            )

    return errors


async def _run_cleanup_resiliently(
    cleanup_coroutine: Awaitable[list[BaseException]],
) -> tuple[list[BaseException], list[asyncio.CancelledError]]:
    """Finish cleanup despite repeated cancellation of the caller.

    Cleanup runs in its own task. Cancellation of the caller is
    deferred until that task has completed.

    Cancellation raised by a cleanup operation itself is retained
    in the cleanup error list.
    """
    cleanup_task = asyncio.create_task(cleanup_coroutine)

    deferred_cancellations: list[asyncio.CancelledError] = []

    while not cleanup_task.done():
        try:
            await asyncio.shield(cleanup_task)

        except asyncio.CancelledError as exc:
            if cleanup_task.done():
                break

            deferred_cancellations.append(exc)

    try:
        cleanup_errors = cleanup_task.result()

    except BaseException as exc:
        cleanup_errors = [exc]

    return cleanup_errors, deferred_cancellations


def _raise_cleanup_failures(
    errors: list[BaseException],
) -> None:
    """Raise collected cleanup failures without losing their causes."""
    if not errors:
        return

    if len(errors) == 1:
        error = errors[0]

        if isinstance(error, asyncio.CancelledError):
            raise error

        raise BootstrapHealthLifespanError(
            "Bootstrap health lifespan shutdown failed"
        ) from error

    raise BaseExceptionGroup(
        "Multiple bootstrap health lifespan shutdown failures",
        errors,
    )


def create_bootstrap_health_api_lifespan(
    *,
    service: SchedulingBootstrapHealthService | None = None,
    bootstrap: SchedulingIntegrationBootstrap | None = None,
    existing_lifespan: ExistingLifespan | None = None,
    before_start: LifespanCallback | None = None,
    after_start: LifespanCallback | None = None,
    before_shutdown: LifespanCallback | None = None,
    after_shutdown: LifespanCallback | None = None,
    replace: bool = False,
) -> Callable[[FastAPI], Any]:
    """Create a resilient FastAPI lifespan for bootstrap health.

    Startup order:
        1. Enter the existing application lifespan.
        2. Execute before_start.
        3. Install or reuse bootstrap health integration.
        4. Execute after_start.
        5. Yield control to the application.

    Shutdown order:
        1. Execute before_shutdown.
        2. Execute after_shutdown.
        3. Exit the existing application lifespan.

    The integration registration is retained after shutdown because
    FastAPI routes cannot safely be unregistered.

    This lifespan does not close the supplied bootstrap. Its lifecycle
    remains owned by the application lifecycle manager.
    """
    if service is not None and bootstrap is not None:
        raise ValueError(
            "Provide either service or bootstrap, not both"
        )

    _validate_callback(before_start, "before_start")
    _validate_callback(after_start, "after_start")
    _validate_callback(before_shutdown, "before_shutdown")
    _validate_callback(after_shutdown, "after_shutdown")

    if existing_lifespan is not None and not callable(existing_lifespan):
        raise TypeError("existing_lifespan must be callable")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        _validate_app(app)

        existing_context: Any | None = None
        existing_context_entered = False

        primary_error: BaseException | None = None
        startup_completed = False

        try:
            if existing_lifespan is not None:
                existing_context = existing_lifespan(app)

                if inspect.isawaitable(existing_context):
                    existing_context = await existing_context

                if (
                    not hasattr(existing_context, "__aenter__")
                    or not hasattr(existing_context, "__aexit__")
                ):
                    raise BootstrapHealthLifespanError(
                        "Existing lifespan must return an "
                        "asynchronous context manager"
                    )

                await existing_context.__aenter__()
                existing_context_entered = True

            await _invoke_callback(before_start, app)

            existing_registration = (
                get_bootstrap_health_api_integration_optional(app)
            )

            if existing_registration is not None:
                integration = install_bootstrap_health_api_integration(
                    app,
                    existing_registration.service,
                )
            else:
                integration = install_bootstrap_health_api_integration(
                    app,
                    service,
                    bootstrap=bootstrap,
                    replace=replace,
                )

            if not isinstance(
                integration,
                BootstrapHealthAPIIntegration,
            ):
                raise BootstrapHealthLifespanError(
                    "Bootstrap health integration returned an "
                    "invalid registration"
                )

            await _invoke_callback(after_start, app)

            startup_completed = True

            yield

        except BaseException as exc:
            primary_error = exc
            raise

        finally:
            cleanup_coroutine = _run_cleanup_steps(
                app,
                before_shutdown=before_shutdown,
                after_shutdown=after_shutdown,
                existing_context=existing_context,
                existing_context_entered=existing_context_entered,
                primary_error=primary_error,
            )

            cleanup_errors, deferred_cancellations = (
                await _run_cleanup_resiliently(cleanup_coroutine)
            )

            if primary_error is not None:
                for error in cleanup_errors:
                    logger.error(
                        "Additional shutdown failure after "
                        "startup or application failure: %s",
                        error,
                    )

                for cancellation in deferred_cancellations:
                    logger.warning(
                        "Additional cancellation deferred during "
                        "bootstrap health cleanup: %s",
                        cancellation,
                    )

            else:
                if deferred_cancellations:
                    cancellation = deferred_cancellations[0]

                    for additional in deferred_cancellations[1:]:
                        logger.warning(
                            "Additional cancellation during cleanup: %s",
                            additional,
                        )

                    raise cancellation

                _raise_cleanup_failures(cleanup_errors)

    return lifespan


def install_bootstrap_health_api_lifespan(
    app: FastAPI,
    *,
    service: SchedulingBootstrapHealthService | None = None,
    bootstrap: SchedulingIntegrationBootstrap | None = None,
    before_start: LifespanCallback | None = None,
    after_start: LifespanCallback | None = None,
    before_shutdown: LifespanCallback | None = None,
    after_shutdown: LifespanCallback | None = None,
    replace: bool = False,
) -> Callable[[FastAPI], Any]:
    """Wrap and install the current FastAPI application lifespan.

    Call this before the application starts. The existing lifespan
    context is preserved and invoked inside the new lifespan.
    """
    _validate_app(app)

    if service is not None and bootstrap is not None:
        raise ValueError(
            "Provide either service or bootstrap, not both"
        )

    lifespan = create_bootstrap_health_api_lifespan(
        service=service,
        bootstrap=bootstrap,
        existing_lifespan=app.router.lifespan_context,
        before_start=before_start,
        after_start=after_start,
        before_shutdown=before_shutdown,
        after_shutdown=after_shutdown,
        replace=replace,
    )

    app.router.lifespan_context = lifespan

    return lifespan
