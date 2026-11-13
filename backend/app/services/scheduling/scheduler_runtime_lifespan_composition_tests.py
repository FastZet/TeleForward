
"""Tests for scheduler runtime lifespan composition."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

import pytest
from fastapi import FastAPI

from app.services.scheduling.scheduler_lifecycle import (
    SchedulerLifecycleState,
)
from app.services.scheduling.scheduler_runtime import SchedulerRuntime
from app.services.scheduling.scheduler_runtime_integration import (
    install_scheduler_runtime,
)
from app.services.scheduling.scheduler_runtime_lifespan_composition import (
    SchedulerLifespanCompositionError,
    compose_scheduler_runtime_lifespan,
    create_scheduler_only_lifespan,
)
from app.services.scheduling.tasks.task_registry import (
    ScheduledTaskRegistry,
)


class FakeManager:
    """Minimal manager used by lifespan composition tests."""

    def __init__(self) -> None:
        self.start_calls = 0
        self.shutdown_calls = 0
        self.fail_start = False
        self.fail_shutdown = False

    async def start(self) -> None:
        self.start_calls += 1

        if self.fail_start:
            raise RuntimeError("Manager startup failed")

    async def shutdown(self) -> None:
        self.shutdown_calls += 1

        if self.fail_shutdown:
            raise RuntimeError("Manager shutdown failed")


@pytest.fixture
def manager() -> FakeManager:
    return FakeManager()


@pytest.fixture
def runtime(manager: FakeManager) -> SchedulerRuntime:
    return SchedulerRuntime(
        manager=manager,
        task_registry=ScheduledTaskRegistry(),
    )


@pytest.fixture
def app(runtime: SchedulerRuntime) -> FastAPI:
    application = FastAPI()
    install_scheduler_runtime(application, runtime)
    return application


def test_create_scheduler_only_lifespan() -> None:
    lifespan = create_scheduler_only_lifespan()

    assert callable(lifespan)


def test_compose_without_existing_lifespan() -> None:
    lifespan = compose_scheduler_runtime_lifespan()

    assert callable(lifespan)


def test_rejects_invalid_existing_lifespan() -> None:
    with pytest.raises(TypeError, match="existing_lifespan"):
        compose_scheduler_runtime_lifespan(
            existing_lifespan="invalid",  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_scheduler_only_lifespan_starts_and_stops(
    runtime: SchedulerRuntime,
    manager: FakeManager,
) -> None:
    lifespan = create_scheduler_only_lifespan()
    app = FastAPI(lifespan=lifespan)
    install_scheduler_runtime(app, runtime)

    async with app.router.lifespan_context(app):
        assert runtime.state == SchedulerLifecycleState.RUNNING

    assert runtime.state == SchedulerLifecycleState.STOPPED
    assert manager.start_calls == 1
    assert manager.shutdown_calls == 1


@pytest.mark.asyncio
async def test_existing_lifespan_starts_before_scheduler(
    runtime: SchedulerRuntime,
) -> None:
    events: list[str] = []

    @asynccontextmanager
    async def existing_lifespan(
        app: FastAPI,
    ) -> AsyncIterator[None]:
        events.append("existing_start")
        yield
        events.append("existing_shutdown")

    scheduler_lifespan = compose_scheduler_runtime_lifespan(
        existing_lifespan,
        before_start=lambda app: events.append("scheduler_before_start"),
        after_start=lambda app: events.append("scheduler_after_start"),
        before_shutdown=lambda app: events.append(
            "scheduler_before_shutdown"
        ),
        after_shutdown=lambda app: events.append(
            "scheduler_after_shutdown"
        ),
    )

    app = FastAPI(lifespan=scheduler_lifespan)
    install_scheduler_runtime(app, runtime)

    async with app.router.lifespan_context(app):
        events.append("application_running")

    assert events == [
        "existing_start",
        "scheduler_before_start",
        "scheduler_after_start",
        "application_running",
        "scheduler_before_shutdown",
        "scheduler_after_shutdown",
        "existing_shutdown",
    ]


@pytest.mark.asyncio
async def test_scheduler_stops_before_existing_resources(
    runtime: SchedulerRuntime,
) -> None:
    events: list[str] = []

    @asynccontextmanager
    async def existing_lifespan(
        app: FastAPI,
    ) -> AsyncIterator[None]:
        events.append("database_connected")
        yield
        events.append("database_disconnected")

    scheduler_lifespan = compose_scheduler_runtime_lifespan(
        existing_lifespan,
        before_shutdown=lambda app: events.append("scheduler_stopping"),
        after_shutdown=lambda app: events.append("scheduler_stopped"),
    )

    app = FastAPI(lifespan=scheduler_lifespan)
    install_scheduler_runtime(app, runtime)

    async with app.router.lifespan_context(app):
        assert "database_connected" in events

    assert events.index("scheduler_stopped") < events.index(
        "database_disconnected"
    )


@pytest.mark.asyncio
async def test_existing_lifespan_failure_prevents_scheduler_start(
    runtime: SchedulerRuntime,
    manager: FakeManager,
) -> None:
    @asynccontextmanager
    async def existing_lifespan(
        app: FastAPI,
    ) -> AsyncIterator[None]:
        raise RuntimeError("Database startup failed")
        yield

    lifespan = compose_scheduler_runtime_lifespan(
        existing_lifespan
    )

    app = FastAPI(lifespan=lifespan)
    install_scheduler_runtime(app, runtime)

    with pytest.raises(
        SchedulerLifespanCompositionError,
        match="existing application lifespan",
    ):
        async with app.router.lifespan_context(app):
            pass

    assert manager.start_calls == 0


@pytest.mark.asyncio
async def test_scheduler_start_failure_closes_existing_lifespan(
    runtime: SchedulerRuntime,
    manager: FakeManager,
) -> None:
    events: list[str] = []
    manager.fail_start = True

    @asynccontextmanager
    async def existing_lifespan(
        app: FastAPI,
    ) -> AsyncIterator[None]:
        events.append("existing_start")
        try:
            yield
        finally:
            events.append("existing_shutdown")

    lifespan = compose_scheduler_runtime_lifespan(
        existing_lifespan
    )

    app = FastAPI(lifespan=lifespan)
    install_scheduler_runtime(app, runtime)

    with pytest.raises(Exception):
        async with app.router.lifespan_context(app):
            pass

    assert events == [
        "existing_start",
        "existing_shutdown",
    ]
    assert runtime.state == SchedulerLifecycleState.STOPPED


@pytest.mark.asyncio
async def test_application_exception_reaches_both_lifespans(
    runtime: SchedulerRuntime,
) -> None:
    events: list[str] = []

    @asynccontextmanager
    async def existing_lifespan(
        app: FastAPI,
    ) -> AsyncIterator[None]:
        try:
            yield
        except RuntimeError:
            events.append("existing_received_error")
            raise
        finally:
            events.append("existing_cleanup")

    lifespan = compose_scheduler_runtime_lifespan(
        existing_lifespan,
        before_shutdown=lambda app: events.append(
            "scheduler_shutdown"
        ),
    )

    app = FastAPI(lifespan=lifespan)
    install_scheduler_runtime(app, runtime)

    with pytest.raises(RuntimeError, match="Application failed"):
        async with app.router.lifespan_context(app):
            raise RuntimeError("Application failed")

    assert events == [
        "scheduler_shutdown",
        "existing_received_error",
        "existing_cleanup",
    ]


@pytest.mark.asyncio
async def test_existing_lifespan_cleanup_runs_after_scheduler_shutdown(
    runtime: SchedulerRuntime,
) -> None:
    events: list[str] = []

    @asynccontextmanager
    async def existing_lifespan(
        app: FastAPI,
    ) -> AsyncIterator[None]:
        yield
        events.append("existing_cleanup")

    lifespan = compose_scheduler_runtime_lifespan(
        existing_lifespan,
        after_shutdown=lambda app: events.append(
            "scheduler_cleanup"
        ),
    )

    app = FastAPI(lifespan=lifespan)
    install_scheduler_runtime(app, runtime)

    async with app.router.lifespan_context(app):
        pass

    assert events == [
        "scheduler_cleanup",
        "existing_cleanup",
    ]


@pytest.mark.asyncio
async def test_existing_lifespan_cleanup_runs_when_scheduler_shutdown_fails(
    runtime: SchedulerRuntime,
    manager: FakeManager,
) -> None:
    events: list[str] = []
    manager.fail_shutdown = True

    @asynccontextmanager
    async def existing_lifespan(
        app: FastAPI,
    ) -> AsyncIterator[None]:
        try:
            yield
        finally:
            events.append("existing_cleanup")

    lifespan = compose_scheduler_runtime_lifespan(
        existing_lifespan
    )

    app = FastAPI(lifespan=lifespan)
    install_scheduler_runtime(app, runtime)

    with pytest.raises(Exception):
        async with app.router.lifespan_context(app):
            pass

    assert events == ["existing_cleanup"]


@pytest.mark.asyncio
async def test_invalid_existing_context_manager_is_rejected(
    runtime: SchedulerRuntime,
) -> None:
    def invalid_lifespan(app: FastAPI):
        return object()

    lifespan = compose_scheduler_runtime_lifespan(
        invalid_lifespan
    )

    app = FastAPI(lifespan=lifespan)
    install_scheduler_runtime(app, runtime)

    with pytest.raises(
        SchedulerLifespanCompositionError,
        match="asynchronous context manager",
    ):
        async with app.router.lifespan_context(app):
            pass


@pytest.mark.asyncio
async def test_invalid_application_is_rejected() -> None:
    lifespan = compose_scheduler_runtime_lifespan()

    with pytest.raises(TypeError, match="FastAPI"):
        async with lifespan(object()):  # type: ignore[arg-type]
            pass
