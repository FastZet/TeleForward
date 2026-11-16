
"""FastAPI lifespan integration for scheduling bootstrap health API."""

from __future__ import annotations

import inspect
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
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
    BootstrapHealthAPIIntegrationError,
    get_bootstrap_health_api_integration_optional,
    install_bootstrap_health_api_integration,
)


logger = logging.getLogger(__name__)

LifespanCallback = Callable[
    [FastAPI],
    Any | Awaitable[Any],
]

ExistingLifespan = Callable[
    [FastAPI],
    AbstractAsyncContextManager[Any],
]


class BootstrapHealthLifespanError(RuntimeError):
    """Raised when bootstrap health lifespan integration fails."""


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


def _validate_app(app: FastAPI) -> None:
    if not isinstance(app, FastAPI):
        raise TypeError("app must be a FastAPI instance")


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
) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    """Create a FastAPI lifespan integrating bootstrap health.

    The combined health service and API are installed during startup.

    An existing application lifespan may be supplied. It is entered
    before the bootstrap health integration is installed and exited
    after the integration's shutdown callbacks have completed.

    The integration registration is intentionally retained after
    shutdown. FastAPI routes cannot safely be unregistered, and
    retaining the registration permits the same application instance
    to enter its lifespan again without attempting duplicate route
    registration.

    The underlying bootstrap lifecycle remains owned by the supplied
    application lifespan or another lifecycle manager.
    """
    if service is not None and bootstrap is not None:
        raise ValueError(
            "Provide either service or bootstrap, not both"
        )

    callbacks = (
        before_start,
        after_start,
        before_shutdown,
        after_shutdown,
    )

    for callback in callbacks:
        if callback is not None and not callable(callback):
            raise TypeError("Lifespan callbacks must be callable")

    if existing_lifespan is not None and not callable(existing_lifespan):
        raise TypeError("existing_lifespan must be callable")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        _validate_app(app)

        existing_context: AbstractAsyncContextManager[Any] | None = None
        existing_context_entered = False
        integration: BootstrapHealthAPIIntegration | None = None

        startup_error: BaseException | None = None

        try:
            if existing_lifespan is not None:
                existing_context = existing_lifespan(app)

                if not hasattr(existing_context, "__aenter__") or not hasattr(
                    existing_context,
                    "__aexit__",
                ):
                    raise BootstrapHealthLifespanError(
                        "Existing lifespan did not return an "
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

            await _invoke_callback(after_start, app)

            yield

        except BaseException as exc:
            startup_error = exc
            raise

        finally:
            shutdown_errors: list[BaseException] = []

            try:
                await _invoke_callback(before_shutdown, app)
            except BaseException as exc:
                shutdown_errors.append(exc)
                logger.exception(
                    "Bootstrap health before-shutdown callback failed"
                )

            try:
                await _invoke_callback(after_shutdown, app)
            except BaseException as exc:
                shutdown_errors.append(exc)
                logger.exception(
                    "Bootstrap health after-shutdown callback failed"
                )

            if existing_context_entered and existing_context is not None:
                try:
                    await existing_context.__aexit__(
                        type(startup_error) if startup_error else None,
                        startup_error,
                        startup_error.__traceback__ if startup_error else None,
                    )
                except BaseException as exc:
                    shutdown_errors.append(exc)
                    logger.exception(
                        "Existing application lifespan shutdown failed"
                    )

            if shutdown_errors:
                if startup_error is not None:
                    for error in shutdown_errors:
                        logger.error(
                            "Additional shutdown failure: %s",
                            error,
                        )
                else:
                    first_error = shutdown_errors[0]

                    if len(shutdown_errors) > 1:
                        raise BaseExceptionGroup(
                            "Multiple bootstrap health shutdown failures",
                            shutdown_errors,
                        )

                    raise BootstrapHealthLifespanError(
                        "Bootstrap health lifespan shutdown failed"
                    ) from first_error

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
) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    """Create and register the bootstrap health lifespan on an app.

    The returned lifespan must be supplied to FastAPI when constructing
    the application, or assigned to app.router.lifespan_context before
    the application starts.
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
