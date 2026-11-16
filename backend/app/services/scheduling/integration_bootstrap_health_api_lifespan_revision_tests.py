
"""Regression tests for the resilient bootstrap health API lifespan."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI

from app.services.scheduling.integration_bootstrap_health import (
    SchedulingBootstrapHealthService,
)
from app.services.scheduling.integration_bootstrap_health_api_lifespan import (
    BootstrapHealthLifespanError,
    create_bootstrap_health_api_lifespan,
)


@pytest.fixture
def app() -> FastAPI:
    return FastAPI()


@pytest.fixture
def service() -> SchedulingBootstrapHealthService:
    return SchedulingBootstrapHealthService()


@pytest.mark.asyncio
async def test_repeated_cancellation_does_not_interrupt_cleanup(
    app: FastAPI,
    service: SchedulingBootstrapHealthService,
) -> None:
    application_entered = asyncio.Event()
    cleanup_started = asyncio.Event()
    allow_cleanup = asyncio.Event()
    cleanup_completed = asyncio.Event()

    async def before_shutdown(_app: FastAPI) -> None:
        cleanup_started.set()
        await allow_cleanup.wait()
        cleanup_completed.set()

    lifespan = create_bootstrap_health_api_lifespan(
        service=service,
        before_shutdown=before_shutdown,
    )

    async def run_application() -> None:
        async with lifespan(app):
            application_entered.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(run_application())

    await application_entered.wait()

    task.cancel()

    await asyncio.wait_for(cleanup_started.wait(), timeout=2)

    # A second cancellation must not interrupt the cleanup task.
    task.cancel()

    await asyncio.sleep(0)
    allow_cleanup.set()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert cleanup_completed.is_set()


@pytest.mark.asyncio
async def test_cleanup_completes_before_cancellation_propagates(
    app: FastAPI,
    service: SchedulingBootstrapHealthService,
) -> None:
    events: list[str] = []
    cleanup_started = asyncio.Event()
    allow_cleanup = asyncio.Event()

    async def before_shutdown(_app: FastAPI) -> None:
        events.append("cleanup_started")
        cleanup_started.set()

        await allow_cleanup.wait()

        events.append("cleanup_finished")

    lifespan = create_bootstrap_health_api_lifespan(
        service=service,
        before_shutdown=before_shutdown,
    )

    async def run_application() -> None:
        async with lifespan(app):
            await asyncio.Event().wait()

    task = asyncio.create_task(run_application())

    await asyncio.sleep(0)
    task.cancel()

    await asyncio.wait_for(cleanup_started.wait(), timeout=2)

    assert "cleanup_finished" not in events

    allow_cleanup.set()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert events == [
        "cleanup_started",
        "cleanup_finished",
    ]


@pytest.mark.asyncio
async def test_original_application_exception_survives_shutdown_failure(
    app: FastAPI,
    service: SchedulingBootstrapHealthService,
) -> None:
    async def failing_shutdown(_app: FastAPI) -> None:
        raise RuntimeError("shutdown failure")

    lifespan = create_bootstrap_health_api_lifespan(
        service=service,
        before_shutdown=failing_shutdown,
    )

    with pytest.raises(
        ValueError,
        match="primary application failure",
    ):
        async with lifespan(app):
            raise ValueError("primary application failure")


@pytest.mark.asyncio
async def test_original_startup_exception_survives_cleanup_failure(
    app: FastAPI,
    service: SchedulingBootstrapHealthService,
) -> None:
    async def failing_after_start(_app: FastAPI) -> None:
        raise ValueError("startup failure")

    async def failing_shutdown(_app: FastAPI) -> None:
        raise RuntimeError("cleanup failure")

    lifespan = create_bootstrap_health_api_lifespan(
        service=service,
        after_start=failing_after_start,
        before_shutdown=failing_shutdown,
    )

    with pytest.raises(ValueError, match="startup failure"):
        async with lifespan(app):
            pass


@pytest.mark.asyncio
async def test_multiple_shutdown_failures_are_preserved(
    app: FastAPI,
    service: SchedulingBootstrapHealthService,
) -> None:
    async def failing_before_shutdown(_app: FastAPI) -> None:
        raise RuntimeError("before shutdown failure")

    async def failing_after_shutdown(_app: FastAPI) -> None:
        raise ValueError("after shutdown failure")

    lifespan = create_bootstrap_health_api_lifespan(
        service=service,
        before_shutdown=failing_before_shutdown,
        after_shutdown=failing_after_shutdown,
    )

    with pytest.raises(BaseExceptionGroup) as captured:
        async with lifespan(app):
            pass

    errors = captured.value.exceptions

    assert len(errors) == 2
    assert isinstance(errors[0], RuntimeError)
    assert isinstance(errors[1], ValueError)


@pytest.mark.asyncio
async def test_existing_lifespan_shutdown_failure_is_preserved(
    app: FastAPI,
    service: SchedulingBootstrapHealthService,
) -> None:
    @asynccontextmanager
    async def existing_lifespan(
        _app: FastAPI,
    ) -> AsyncIterator[None]:
        yield
        raise RuntimeError("existing lifespan shutdown failure")

    lifespan = create_bootstrap_health_api_lifespan(
        service=service,
        existing_lifespan=existing_lifespan,
    )

    with pytest.raises(
        BootstrapHealthLifespanError,
    ) as captured:
        async with lifespan(app):
            pass

    assert isinstance(captured.value.__cause__, RuntimeError)
    assert str(captured.value.__cause__) == (
        "existing lifespan shutdown failure"
    )


@pytest.mark.asyncio
async def test_all_shutdown_operations_run_after_multiple_failures(
    app: FastAPI,
    service: SchedulingBootstrapHealthService,
) -> None:
    events: list[str] = []

    async def before_shutdown(_app: FastAPI) -> None:
        events.append("before_shutdown")
        raise RuntimeError("first failure")

    async def after_shutdown(_app: FastAPI) -> None:
        events.append("after_shutdown")
        raise ValueError("second failure")

    @asynccontextmanager
    async def existing_lifespan(
        _app: FastAPI,
    ) -> AsyncIterator[None]:
        try:
            yield
        finally:
            events.append("existing_shutdown")

    lifespan = create_bootstrap_health_api_lifespan(
        service=service,
        existing_lifespan=existing_lifespan,
        before_shutdown=before_shutdown,
        after_shutdown=after_shutdown,
    )

    with pytest.raises(BaseExceptionGroup):
        async with lifespan(app):
            events.append("application")

    assert events == [
        "application",
        "before_shutdown",
        "after_shutdown",
        "existing_shutdown",
    ]


@pytest.mark.asyncio
async def test_async_existing_lifespan_factory_is_supported(
    app: FastAPI,
    service: SchedulingBootstrapHealthService,
) -> None:
    events: list[str] = []

    @asynccontextmanager
    async def context_manager(
        _app: FastAPI,
    ) -> AsyncIterator[None]:
        events.append("entered")
        try:
            yield
        finally:
            events.append("exited")

    async def existing_lifespan_factory(
        _app: FastAPI,
    ):
        events.append("factory_called")
        return context_manager(_app)

    lifespan = create_bootstrap_health_api_lifespan(
        service=service,
        existing_lifespan=existing_lifespan_factory,
    )

    async with lifespan(app):
        events.append("application")

    assert events == [
        "factory_called",
        "entered",
        "application",
        "exited",
    ]


@pytest.mark.asyncio
async def test_async_existing_lifespan_factory_failure_propagates(
    app: FastAPI,
    service: SchedulingBootstrapHealthService,
) -> None:
    async def failing_factory(
        _app: FastAPI,
    ):
        raise RuntimeError("lifespan factory failure")

    lifespan = create_bootstrap_health_api_lifespan(
        service=service,
        existing_lifespan=failing_factory,
    )

    with pytest.raises(
        RuntimeError,
        match="lifespan factory failure",
    ):
        async with lifespan(app):
            pass


@pytest.mark.asyncio
async def test_cancellation_during_startup_preserves_cancellation(
    app: FastAPI,
    service: SchedulingBootstrapHealthService,
) -> None:
    events: list[str] = []

    async def failing_after_start(_app: FastAPI) -> None:
        raise asyncio.CancelledError()

    async def before_shutdown(_app: FastAPI) -> None:
        events.append("before_shutdown")

    async def after_shutdown(_app: FastAPI) -> None:
        events.append("after_shutdown")

    lifespan = create_bootstrap_health_api_lifespan(
        service=service,
        after_start=failing_after_start,
        before_shutdown=before_shutdown,
        after_shutdown=after_shutdown,
    )

    with pytest.raises(asyncio.CancelledError):
        async with lifespan(app):
            pass

    assert events == [
        "before_shutdown",
        "after_shutdown",
    ]


@pytest.mark.asyncio
async def test_shutdown_cancellation_is_propagated(
    app: FastAPI,
    service: SchedulingBootstrapHealthService,
) -> None:
    async def cancelling_shutdown(_app: FastAPI) -> None:
        raise asyncio.CancelledError()

    lifespan = create_bootstrap_health_api_lifespan(
        service=service,
        before_shutdown=cancelling_shutdown,
    )

    with pytest.raises(asyncio.CancelledError):
        async with lifespan(app):
            pass


@pytest.mark.asyncio
async def test_shutdown_cancellation_does_not_skip_later_cleanup(
    app: FastAPI,
    service: SchedulingBootstrapHealthService,
) -> None:
    events: list[str] = []

    async def cancelling_before_shutdown(_app: FastAPI) -> None:
        events.append("before_shutdown")
        raise asyncio.CancelledError()

    async def after_shutdown(_app: FastAPI) -> None:
        events.append("after_shutdown")

    lifespan = create_bootstrap_health_api_lifespan(
        service=service,
        before_shutdown=cancelling_before_shutdown,
        after_shutdown=after_shutdown,
    )

    with pytest.raises(asyncio.CancelledError):
        async with lifespan(app):
            pass

    assert events == [
        "before_shutdown",
        "after_shutdown",
    ]


@pytest.mark.asyncio
async def test_application_exception_is_passed_to_existing_lifespan(
    app: FastAPI,
    service: SchedulingBootstrapHealthService,
) -> None:
    received: list[type[BaseException] | None] = []

    @asynccontextmanager
    async def existing_lifespan(
        _app: FastAPI,
    ) -> AsyncIterator[None]:
        try:
            yield
        except BaseException as exc:
            received.append(type(exc))
            raise

    lifespan = create_bootstrap_health_api_lifespan(
        service=service,
        existing_lifespan=existing_lifespan,
    )

    with pytest.raises(ValueError, match="application error"):
        async with lifespan(app):
            raise ValueError("application error")

    assert received == [ValueError]


@pytest.mark.asyncio
async def test_repeated_cancellation_during_existing_lifespan_cleanup(
    app: FastAPI,
    service: SchedulingBootstrapHealthService,
) -> None:
    cleanup_started = asyncio.Event()
    allow_cleanup = asyncio.Event()
    cleanup_completed = asyncio.Event()

    @asynccontextmanager
    async def existing_lifespan(
        _app: FastAPI,
    ) -> AsyncIterator[None]:
        try:
            yield
        finally:
            cleanup_started.set()
            await allow_cleanup.wait()
            cleanup_completed.set()

    lifespan = create_bootstrap_health_api_lifespan(
        service=service,
        existing_lifespan=existing_lifespan,
    )

    async def run_application() -> None:
        async with lifespan(app):
            await asyncio.Event().wait()

    task = asyncio.create_task(run_application())

    await asyncio.sleep(0)
    task.cancel()

    await asyncio.wait_for(cleanup_started.wait(), timeout=2)

    task.cancel()
    await asyncio.sleep(0)

    allow_cleanup.set()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert cleanup_completed.is_set()
