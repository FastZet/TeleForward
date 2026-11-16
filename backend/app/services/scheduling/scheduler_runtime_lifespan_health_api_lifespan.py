
"""FastAPI lifespan integration for the scheduler health API."""

from __future__ import annotations

import inspect
import logging
from contextlib import AsyncExitStack, asynccontextmanager
from typing import AsyncContextManager, Callable

from fastapi import FastAPI

from app.services.scheduling.scheduler_runtime_lifespan_health import (
    SchedulerRuntimeLifespanHealthService,
)
from app.services.scheduling.scheduler_runtime_lifespan_health_api_integration import (
    SchedulerHealthAPIIntegrationError,
    get_scheduler_health_api_integration_status,
    install_scheduler_health_api_integration,
)

logger = logging.getLogger(__name__)

LifespanFactory = Callable[
    [FastAPI],
    AsyncContextManager[None],
]


class SchedulerHealthAPILifespanError(RuntimeError):
    """Raised when scheduler health API lifespan setup fails."""


def _validate_existing_lifespan(
    existing_lifespan: LifespanFactory | None,
) -> None:
    """Validate an optional existing lifespan factory."""

    if existing_lifespan is not None and not callable(
        existing_lifespan
    ):
        raise TypeError(
            "existing_lifespan must be callable or None"
        )


def _ensure_health_api_installed(
    app: FastAPI,
    service: SchedulerRuntimeLifespanHealthService | None,
) -> None:
    """Install the health API integration or validate its state."""

    try:
        state = get_scheduler_health_api_integration_status(
            app
        )

        if state["consistent"]:
            if service is not None:
                from app.services.scheduling.scheduler_runtime_lifespan_health_api_integration import (
                    get_scheduler_health_api_integration,
                )

                installed_service = (
                    get_scheduler_health_api_integration(app)
                )

                if installed_service is not service:
                    raise SchedulerHealthAPIIntegrationError(
                        "The installed health service differs from "
                        "the lifespan service"
                    )

            return

        if state["integrated"]:
            raise SchedulerHealthAPIIntegrationError(
                "Scheduler health API integration is inconsistent"
            )

        install_scheduler_health_api_integration(
            app,
            service=service,
        )

    except Exception as exc:
        raise SchedulerHealthAPILifespanError(
            "Unable to initialise scheduler health API integration"
        ) from exc


def create_scheduler_health_api_lifespan(
    *,
    existing_lifespan: LifespanFactory | None = None,
    service: SchedulerRuntimeLifespanHealthService | None = None,
) -> LifespanFactory:
    """
    Create a FastAPI lifespan that installs scheduler health integration.

    The optional existing lifespan is entered before scheduler health
    setup and remains active until scheduler health shutdown completes.

    The health API integration is retained in app.state after shutdown.
    This is intentional because FastAPI does not support safely removing
    an included router at runtime.
    """

    _validate_existing_lifespan(existing_lifespan)

    if service is not None and not isinstance(
        service,
        SchedulerRuntimeLifespanHealthService,
    ):
        raise TypeError(
            "service must be a SchedulerRuntimeLifespanHealthService"
        )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if not isinstance(app, FastAPI):
            raise TypeError(
                "app must be a FastAPI instance"
            )

        async with AsyncExitStack() as stack:
            if existing_lifespan is not None:
                try:
                    existing_context = existing_lifespan(app)

                    if inspect.isawaitable(existing_context):
                        existing_context = await existing_context

                    await stack.enter_async_context(
                        existing_context
                    )

                except Exception as exc:
                    raise SchedulerHealthAPILifespanError(
                        "Existing application lifespan failed to start"
                    ) from exc

            try:
                _ensure_health_api_installed(
                    app,
                    service,
                )

                logger.info(
                    "Scheduler health API lifespan started"
                )

            except Exception:
                logger.exception(
                    "Scheduler health API startup failed"
                )
                raise

            try:
                yield

            finally:
                logger.info(
                    "Scheduler health API lifespan stopped"
                )

    return lifespan


def install_scheduler_health_api_lifespan(
    app: FastAPI,
    *,
    existing_lifespan: LifespanFactory | None = None,
    service: SchedulerRuntimeLifespanHealthService | None = None,
) -> LifespanFactory:
    """
    Create and register the scheduler health lifespan.

    This function does not replace app.router.lifespan_context.
    Pass the returned lifespan to FastAPI during application creation,
    or use it with an appropriate lifespan composition mechanism.
    """

    if not isinstance(app, FastAPI):
        raise TypeError("app must be a FastAPI instance")

    lifespan = create_scheduler_health_api_lifespan(
        existing_lifespan=existing_lifespan,
        service=service,
    )

    setattr(
        app.state,
        "scheduler_health_api_lifespan",
        lifespan,
    )

    return lifespan


def get_scheduler_health_api_lifespan(
    app: FastAPI,
) -> LifespanFactory:
    """Return the registered scheduler health lifespan."""

    if not isinstance(app, FastAPI):
        raise TypeError("app must be a FastAPI instance")

    lifespan = getattr(
        app.state,
        "scheduler_health_api_lifespan",
        None,
    )

    if lifespan is None:
        raise SchedulerHealthAPILifespanError(
            "Scheduler health API lifespan is not registered"
        )

    return lifespan


def is_scheduler_health_api_lifespan_registered(
    app: FastAPI,
) -> bool:
    """Check whether a scheduler health lifespan is registered."""

    if not isinstance(app, FastAPI):
        raise TypeError("app must be a FastAPI instance")

    return callable(
        getattr(
            app.state,
            "scheduler_health_api_lifespan",
            None,
        )
    )
