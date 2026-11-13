
"""Composition utilities for FastAPI application lifespans."""

from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI

from app.services.scheduling.scheduler_runtime_lifespan_integration import (
    create_scheduler_runtime_lifespan_integration,
)

logger = logging.getLogger(__name__)

LifespanFactory = Callable[[FastAPI], Any]


class SchedulerLifespanCompositionError(RuntimeError):
    """Raised when application lifespan composition fails."""


def _validate_lifespan_factory(
    factory: LifespanFactory | None,
    name: str,
) -> None:
    """Validate an optional lifespan factory."""

    if factory is not None and not callable(factory):
        raise TypeError(f"{name} must be callable or None")


def _validate_async_context_manager(
    context_manager: Any,
    name: str,
) -> None:
    """Ensure a lifespan factory returned an async context manager."""

    if not callable(getattr(context_manager, "__aenter__", None)):
        raise SchedulerLifespanCompositionError(
            f"{name} must return an asynchronous context manager"
        )

    if not callable(getattr(context_manager, "__aexit__", None)):
        raise SchedulerLifespanCompositionError(
            f"{name} must return an asynchronous context manager"
        )


def compose_scheduler_runtime_lifespan(
    existing_lifespan: LifespanFactory | None = None,
    *,
    before_start: Callable[..., Any] | None = None,
    after_start: Callable[..., Any] | None = None,
    before_shutdown: Callable[..., Any] | None = None,
    after_shutdown: Callable[..., Any] | None = None,
) -> LifespanFactory:
    """
    Compose the scheduler runtime lifespan with an existing lifespan.

    Startup order:
        1. Existing application lifespan.
        2. Scheduler runtime lifespan.

    Shutdown order:
        1. Scheduler runtime lifespan.
        2. Existing application lifespan.

    The existing lifespan should initialise resources required by
    scheduled tasks, such as database connections or configuration.

    Example:

        lifespan = compose_scheduler_runtime_lifespan(
            existing_lifespan=database_lifespan,
        )

        app = FastAPI(lifespan=lifespan)

    The scheduler runtime must be installed on the FastAPI instance
    before its lifespan is entered.
    """

    _validate_lifespan_factory(
        existing_lifespan,
        "existing_lifespan",
    )

    scheduler_lifespan = (
        create_scheduler_runtime_lifespan_integration(
            before_start=before_start,
            after_start=after_start,
            before_shutdown=before_shutdown,
            after_shutdown=after_shutdown,
        )
    )

    @asynccontextmanager
    async def composed_lifespan(
        app: FastAPI,
    ) -> AsyncIterator[None]:
        if not isinstance(app, FastAPI):
            raise TypeError("app must be a FastAPI instance")

        async with AsyncExitStack() as stack:
            if existing_lifespan is not None:
                try:
                    existing_context = existing_lifespan(app)
                except Exception as exc:
                    logger.exception(
                        "Existing application lifespan failed to initialise"
                    )
                    raise SchedulerLifespanCompositionError(
                        "Failed to initialise existing application lifespan"
                    ) from exc

                _validate_async_context_manager(
                    existing_context,
                    "existing_lifespan",
                )

                await stack.enter_async_context(existing_context)

            try:
                scheduler_context = scheduler_lifespan(app)
            except Exception as exc:
                logger.exception(
                    "Scheduler lifespan failed to initialise"
                )
                raise SchedulerLifespanCompositionError(
                    "Failed to initialise scheduler lifespan"
                ) from exc

            _validate_async_context_manager(
                scheduler_context,
                "scheduler_lifespan",
            )

            await stack.enter_async_context(scheduler_context)

            yield

    return composed_lifespan


def create_scheduler_only_lifespan(
    *,
    before_start: Callable[..., Any] | None = None,
    after_start: Callable[..., Any] | None = None,
    before_shutdown: Callable[..., Any] | None = None,
    after_shutdown: Callable[..., Any] | None = None,
) -> LifespanFactory:
    """Create a scheduler-only lifespan using the composition API."""

    return compose_scheduler_runtime_lifespan(
        existing_lifespan=None,
        before_start=before_start,
        after_start=after_start,
        before_shutdown=before_shutdown,
        after_shutdown=after_shutdown,
    )
