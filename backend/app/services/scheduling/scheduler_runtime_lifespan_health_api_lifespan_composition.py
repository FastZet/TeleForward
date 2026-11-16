
"""Composition utilities for scheduler health API lifespans."""

from __future__ import annotations

import inspect
import logging
from contextlib import AsyncExitStack, asynccontextmanager
from typing import AsyncContextManager, Callable

from fastapi import FastAPI

logger = logging.getLogger(__name__)

LifespanFactory = Callable[
    [FastAPI],
    AsyncContextManager[None],
]


class SchedulerHealthAPILifespanCompositionError(RuntimeError):
    """Raised when scheduler health lifespan composition fails."""


async def _enter_lifespan(
    stack: AsyncExitStack,
    app: FastAPI,
    factory: LifespanFactory,
    name: str,
) -> None:
    """Create and enter one lifespan context."""

    try:
        context = factory(app)

        if inspect.isawaitable(context):
            context = await context

        if not hasattr(context, "__aenter__") or not hasattr(
            context,
            "__aexit__",
        ):
            raise TypeError(
                f"{name} must return an asynchronous context manager"
            )

        await stack.enter_async_context(context)

        logger.debug(
            "Entered %s lifespan context",
            name,
        )

    except Exception as exc:
        logger.exception(
            "Failed to enter %s lifespan context",
            name,
        )

        raise SchedulerHealthAPILifespanCompositionError(
            f"Unable to enter {name} lifespan"
        ) from exc


def _validate_lifespan(
    factory: LifespanFactory | None,
    name: str,
) -> None:
    """Validate an optional lifespan factory."""

    if factory is not None and not callable(factory):
        raise TypeError(
            f"{name} must be callable or None"
        )


def compose_scheduler_health_api_lifespans(
    *,
    existing_lifespan: LifespanFactory | None = None,
    scheduler_runtime_lifespan: LifespanFactory | None = None,
    health_api_lifespan: LifespanFactory | None = None,
) -> LifespanFactory:
    """
    Compose application, scheduler and health API lifespans.

    Startup order:
        1. Existing application lifespan.
        2. Scheduler runtime lifespan.
        3. Scheduler health API lifespan.

    Shutdown order:
        1. Scheduler health API lifespan.
        2. Scheduler runtime lifespan.
        3. Existing application lifespan.

    All supplied contexts are entered through one AsyncExitStack.
    If startup fails, previously entered contexts are unwound.
    """

    _validate_lifespan(
        existing_lifespan,
        "existing_lifespan",
    )

    _validate_lifespan(
        scheduler_runtime_lifespan,
        "scheduler_runtime_lifespan",
    )

    _validate_lifespan(
        health_api_lifespan,
        "health_api_lifespan",
    )

    @asynccontextmanager
    async def composed_lifespan(app: FastAPI):
        if not isinstance(app, FastAPI):
            raise TypeError(
                "app must be a FastAPI instance"
            )

        async with AsyncExitStack() as stack:
            contexts = (
                (
                    "existing application",
                    existing_lifespan,
                ),
                (
                    "scheduler runtime",
                    scheduler_runtime_lifespan,
                ),
                (
                    "scheduler health API",
                    health_api_lifespan,
                ),
            )

            for name, factory in contexts:
                if factory is None:
                    continue

                await _enter_lifespan(
                    stack,
                    app,
                    factory,
                    name,
                )

            logger.info(
                "Scheduler health API lifespan composition started"
            )

            try:
                yield
            finally:
                logger.info(
                    "Scheduler health API lifespan composition stopping"
                )

    return composed_lifespan


def create_scheduler_health_api_lifespan_composition(
    *,
    existing_lifespan: LifespanFactory | None = None,
    scheduler_runtime_lifespan: LifespanFactory | None = None,
    health_api_lifespan: LifespanFactory | None = None,
) -> LifespanFactory:
    """Create a composed scheduler health API lifespan."""

    return compose_scheduler_health_api_lifespans(
        existing_lifespan=existing_lifespan,
        scheduler_runtime_lifespan=scheduler_runtime_lifespan,
        health_api_lifespan=health_api_lifespan,
    )


def create_scheduler_health_api_only_composition(
    health_api_lifespan: LifespanFactory,
) -> LifespanFactory:
    """Create a composition containing only the health API lifespan."""

    _validate_lifespan(
        health_api_lifespan,
        "health_api_lifespan",
    )

    if health_api_lifespan is None:
        raise TypeError(
            "health_api_lifespan is required"
        )

    return compose_scheduler_health_api_lifespans(
        health_api_lifespan=health_api_lifespan,
    )
