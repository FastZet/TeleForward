
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
    """Raised when scheduler lifespan composition fails."""


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
    """Validate an asynchronous context manager."""

    if not callable(getattr(context_manager, "__aenter__", None)):
        raise SchedulerLifespanCompositionError(
            f"{name} must return an asynchronous context manager"
        )

    if not callable(getattr(context_manager, "__aexit__", None)):
        raise SchedulerLifespanCompositionError(
            f"{name} must return an asynchronous context manager"
        )


def _create_context_manager(
    factory: LifespanFactory,
    app: FastAPI,
    name: str,
):
    """Invoke a lifespan factory and validate its result."""

    try:
        context_manager = factory(app)
    except Exception as exc:
        logger.exception("%s lifespan factory failed", name)

        raise SchedulerLifespanCompositionError(
            f"Failed to create {name} lifespan context"
        ) from exc

    _validate_async_context_manager(
        context_manager,
        name,
    )

    return context_manager


async def _enter_context(
    stack: AsyncExitStack,
    context_manager: Any,
    name: str,
) -> None:
    """Enter a lifespan context with consistent error handling."""

    try:
        await stack.enter_async_context(context_manager)
    except Exception as exc:
        logger.exception("%s lifespan startup failed", name)

        raise SchedulerLifespanCompositionError(
            f"Failed to enter {name} lifespan context"
        ) from exc


def compose_scheduler_runtime_lifespan(
    existing_lifespan: LifespanFactory | None = None,
    *,
    before_start: Callable[..., Any] | None = None,
    after_start: Callable[..., Any] | None = None,
    before_shutdown: Callable[..., Any] | None = None,
    after_shutdown: Callable[..., Any] | None = None,
) -> LifespanFactory:
    """
    Compose the scheduler lifespan with an existing application lifespan.

    Startup order:
        1. Existing application lifespan.
        2. Scheduler runtime lifespan.

    Shutdown order:
        1. Scheduler runtime lifespan.
        2. Existing application lifespan.

    Existing application resources should be initialised before the
    scheduler starts, and remain available until it has stopped.
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
                existing_context = _create_context_manager(
                    existing_lifespan,
                    app,
                    "existing application",
                )

                await _enter_context(
                    stack,
                    existing_context,
                    "existing application",
                )

            scheduler_context = _create_context_manager(
                scheduler_lifespan,
                app,
                "scheduler runtime",
            )

            await _enter_context(
                stack,
                scheduler_context,
                "scheduler runtime",
            )

            yield

    return composed_lifespan


def create_scheduler_only_lifespan(
    *,
    before_start: Callable[..., Any] | None = None,
    after_start: Callable[..., Any] | None = None,
    before_shutdown: Callable[..., Any] | None = None,
    after_shutdown: Callable[..., Any] | None = None,
) -> LifespanFactory:
    """Create a scheduler-only application lifespan."""

    return compose_scheduler_runtime_lifespan(
        existing_lifespan=None,
        before_start=before_start,
        after_start=after_start,
        before_shutdown=before_shutdown,
        after_shutdown=after_shutdown,
    )
