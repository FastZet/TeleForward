
"""Tests for scheduler health API lifespan composition."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncContextManager

import pytest
from fastapi import FastAPI

from app.services.scheduling.scheduler_runtime_lifespan_health_api_lifespan_composition import (
    SchedulerHealthAPILifespanCompositionError,
    compose_scheduler_health_api_lifespans,
    create_scheduler_health_api_lifespan_composition,
    create_scheduler_health_api_only_composition,
)


@pytest.fixture
def app() -> FastAPI:
    """Create a FastAPI application."""

    return FastAPI()


def make_lifespan(
    name: str,
    events: list[str],
):
    """Create a lifespan that records startup and shutdown events."""

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        events.append(f"{name}_startup")

        try:
            yield
        finally:
            events.append(f"{name}_shutdown")

    return lifespan


@pytest.mark.asyncio
async def test_startup_and_shutdown_order(
    app: FastAPI,
) -> None:
    """Contexts must start in order and stop in reverse order."""

    events: list[str] = []

    composed = compose_scheduler_health_api_lifespans(
        existing_lifespan=make_lifespan(
            "application",
            events,
        ),
        scheduler_runtime_lifespan=make_lifespan(
            "scheduler",
            events,
        ),
        health_api_lifespan=make_lifespan(
            "health",
            events,
        ),
    )

    async with composed(app):
        events.append("application_running")

    assert events == [
        "application_startup",
        "scheduler_startup",
        "health_startup",
        "application_running",
        "health_shutdown",
        "scheduler_shutdown",
        "application_shutdown",
    ]


@pytest.mark.asyncio
async def test_composition_without_existing_lifespan(
    app: FastAPI,
) -> None:
    """The existing application lifespan must be optional."""

    events: list[str] = []

    composed = compose_scheduler_health_api_lifespans(
        scheduler_runtime_lifespan=make_lifespan(
            "scheduler",
            events,
        ),
        health_api_lifespan=make_lifespan(
            "health",
            events,
        ),
    )

    async with composed(app):
        events.append("running")

    assert events == [
        "scheduler_startup",
        "health_startup",
        "running",
        "health_shutdown",
        "scheduler_shutdown",
    ]


@pytest.mark.asyncio
async def test_composition_with_only_health_api(
    app: FastAPI,
) -> None:
    """The health-only composition must enter its supplied context."""

    events: list[str] = []

    composed = create_scheduler_health_api_only_composition(
        make_lifespan("health", events)
    )

    async with composed(app):
        events.append("running")

    assert events == [
        "health_startup",
        "running",
        "health_shutdown",
    ]


@pytest.mark.asyncio
async def test_empty_composition_is_valid(
    app: FastAPI,
) -> None:
    """A composition with no optional contexts must still work."""

    composed = compose_scheduler_health_api_lifespans()

    async with composed(app):
        assert isinstance(app, FastAPI)


@pytest.mark.asyncio
async def test_scheduler_startup_failure_rolls_back_application(
    app: FastAPI,
) -> None:
    """Application context must exit when scheduler startup fails."""

    events: list[str] = []

    @asynccontextmanager
    async def failing_scheduler(application: FastAPI):
        events.append("scheduler_startup")
        raise RuntimeError("Scheduler startup failure")
        yield

    composed = compose_scheduler_health_api_lifespans(
        existing_lifespan=make_lifespan(
            "application",
            events,
        ),
        scheduler_runtime_lifespan=failing_scheduler,
    )

    with pytest.raises(
        SchedulerHealthAPILifespanCompositionError,
        match="Unable to enter scheduler runtime lifespan",
    ):
        async with composed(app):
            pass

    assert events == [
        "application_startup",
        "scheduler_startup",
        "application_shutdown",
    ]


@pytest.mark.asyncio
async def test_health_startup_failure_rolls_back_prior_contexts(
    app: FastAPI,
) -> None:
    """Health startup failure must unwind scheduler and application."""

    events: list[str] = []

    @asynccontextmanager
    async def failing_health(application: FastAPI):
        events.append("health_startup")
        raise RuntimeError("Health startup failure")
        yield

    composed = compose_scheduler_health_api_lifespans(
        existing_lifespan=make_lifespan(
            "application",
            events,
        ),
        scheduler_runtime_lifespan=make_lifespan(
            "scheduler",
            events,
        ),
        health_api_lifespan=failing_health,
    )

    with pytest.raises(
        SchedulerHealthAPILifespanCompositionError,
        match="Unable to enter scheduler health API lifespan",
    ):
        async with composed(app):
            pass

    assert events == [
        "application_startup",
        "scheduler_startup",
        "health_startup",
        "scheduler_shutdown",
        "application_shutdown",
    ]


@pytest.mark.asyncio
async def test_context_factory_failure_is_wrapped(
    app: FastAPI,
) -> None:
    """A synchronous factory failure must be wrapped."""

    def failing_factory(application: FastAPI):
        raise RuntimeError("Factory failure")

    composed = compose_scheduler_health_api_lifespans(
        scheduler_runtime_lifespan=failing_factory,
    )

    with pytest.raises(
        SchedulerHealthAPILifespanCompositionError,
        match="Unable to enter scheduler runtime lifespan",
    ):
        async with composed(app):
            pass


@pytest.mark.asyncio
async def test_async_context_factory_is_supported(
    app: FastAPI,
) -> None:
    """An awaitable factory result must be supported."""

    events: list[str] = []

    @asynccontextmanager
    async def context(application: FastAPI):
        events.append("startup")
        yield
        events.append("shutdown")

    async def async_factory(
        application: FastAPI,
    ) -> AsyncContextManager[None]:
        return context(application)

    composed = compose_scheduler_health_api_lifespans(
        health_api_lifespan=async_factory,
    )

    async with composed(app):
        events.append("running")

    assert events == [
        "startup",
        "running",
        "shutdown",
    ]


@pytest.mark.asyncio
async def test_invalid_context_manager_is_rejected(
    app: FastAPI,
) -> None:
    """A factory returning an invalid object must fail."""

    def invalid_factory(application: FastAPI):
        return object()

    composed = compose_scheduler_health_api_lifespans(
        health_api_lifespan=invalid_factory,
    )

    with pytest.raises(
        SchedulerHealthAPILifespanCompositionError,
        match="Unable to enter scheduler health API lifespan",
    ):
        async with composed(app):
            pass


@pytest.mark.asyncio
async def test_application_exception_propagates(
    app: FastAPI,
) -> None:
    """Exceptions from the application body must remain unchanged."""

    events: list[str] = []

    composed = compose_scheduler_health_api_lifespans(
        existing_lifespan=make_lifespan(
            "application",
            events,
        ),
        scheduler_runtime_lifespan=make_lifespan(
            "scheduler",
            events,
        ),
        health_api_lifespan=make_lifespan(
            "health",
            events,
        ),
    )

    with pytest.raises(
        RuntimeError,
        match="Application failure",
    ):
        async with composed(app):
            raise RuntimeError("Application failure")

    assert events == [
        "application_startup",
        "scheduler_startup",
        "health_startup",
        "health_shutdown",
        "scheduler_shutdown",
        "application_shutdown",
    ]


@pytest.mark.asyncio
async def test_cancellation_during_startup_propagates(
    app: FastAPI,
) -> None:
    """Cancellation must not be converted into a composition error."""

    events: list[str] = []

    @asynccontextmanager
    async def cancelled_health(application: FastAPI):
        events.append("health_startup")
        raise asyncio.CancelledError()
        yield

    composed = compose_scheduler_health_api_lifespans(
        existing_lifespan=make_lifespan(
            "application",
            events,
        ),
        scheduler_runtime_lifespan=make_lifespan(
            "scheduler",
            events,
        ),
        health_api_lifespan=cancelled_health,
    )

    with pytest.raises(asyncio.CancelledError):
        async with composed(app):
            pass

    assert events == [
        "application_startup",
        "scheduler_startup",
        "health_startup",
        "scheduler_shutdown",
        "application_shutdown",
    ]


@pytest.mark.asyncio
async def test_cancellation_during_application_body_propagates(
    app: FastAPI,
) -> None:
    """Application cancellation must trigger all context cleanup."""

    events: list[str] = []

    composed = compose_scheduler_health_api_lifespans(
        existing_lifespan=make_lifespan(
            "application",
            events,
        ),
        scheduler_runtime_lifespan=make_lifespan(
            "scheduler",
            events,
        ),
        health_api_lifespan=make_lifespan(
            "health",
            events,
        ),
    )

    with pytest.raises(asyncio.CancelledError):
        async with composed(app):
            raise asyncio.CancelledError()

    assert events == [
        "application_startup",
        "scheduler_startup",
        "health_startup",
        "health_shutdown",
        "scheduler_shutdown",
        "application_shutdown",
    ]


@pytest.mark.asyncio
async def test_shutdown_exception_does_not_skip_earlier_context_cleanup(
    app: FastAPI,
) -> None:
    """A shutdown failure must not prevent remaining cleanup."""

    events: list[str] = []

    @asynccontextmanager
    async def failing_health(application: FastAPI):
        events.append("health_startup")
        try:
            yield
        finally:
            events.append("health_shutdown")
            raise RuntimeError("Health shutdown failure")

    composed = compose_scheduler_health_api_lifespans(
        existing_lifespan=make_lifespan(
            "application",
            events,
        ),
        scheduler_runtime_lifespan=make_lifespan(
            "scheduler",
            events,
        ),
        health_api_lifespan=failing_health,
    )

    with pytest.raises(
        RuntimeError,
        match="Health shutdown failure",
    ):
        async with composed(app):
            events.append("running")

    assert events == [
        "application_startup",
        "scheduler_startup",
        "health_startup",
        "running",
        "health_shutdown",
        "scheduler_shutdown",
        "application_shutdown",
    ]


def test_invalid_existing_lifespan_is_rejected() -> None:
    """Invalid existing lifespan factories must be rejected."""

    with pytest.raises(
        TypeError,
        match="existing_lifespan must be callable",
    ):
        compose_scheduler_health_api_lifespans(
            existing_lifespan="invalid",  # type: ignore[arg-type]
        )


def test_invalid_scheduler_lifespan_is_rejected() -> None:
    """Invalid scheduler lifespan factories must be rejected."""

    with pytest.raises(
        TypeError,
        match="scheduler_runtime_lifespan must be callable",
    ):
        compose_scheduler_health_api_lifespans(
            scheduler_runtime_lifespan=123,  # type: ignore[arg-type]
        )


def test_invalid_health_lifespan_is_rejected() -> None:
    """Invalid health lifespan factories must be rejected."""

    with pytest.raises(
        TypeError,
        match="health_api_lifespan must be callable",
    ):
        compose_scheduler_health_api_lifespans(
            health_api_lifespan=False,  # type: ignore[arg-type]
        )


def test_health_only_composition_requires_factory() -> None:
    """The health-only helper requires a lifespan factory."""

    with pytest.raises(
        TypeError,
        match="health_api_lifespan is required",
    ):
        create_scheduler_health_api_only_composition(
            None  # type: ignore[arg-type]
        )


def test_factory_alias_produces_composition() -> None:
    """The factory alias must delegate to the composition function."""

    composed = create_scheduler_health_api_lifespan_composition()

    assert callable(composed)


@pytest.mark.asyncio
async def test_composition_rejects_invalid_application() -> None:
    """The composed lifespan must require a FastAPI application."""

    composed = compose_scheduler_health_api_lifespans()

    with pytest.raises(
        TypeError,
        match="FastAPI instance",
    ):
        async with composed(object()):  # type: ignore[arg-type]
            pass
