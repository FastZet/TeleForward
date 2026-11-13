
"""Regression tests for scheduler runtime lifespan management."""

from __future__ import annotations

from contextlib import asynccontextmanager

import asyncio
import pytest
from fastapi import FastAPI

from app.services.scheduling.scheduler_lifecycle import (
    SchedulerLifecycleState,
)
from app.services.scheduling.scheduler_runtime import SchedulerRuntime
from app.services.scheduling.scheduler_runtime_integration import (
    install_scheduler_runtime,
)
from app.services.scheduling.scheduler_runtime_lifespan import (
    SchedulerRuntimeLifespanError,
    create_scheduler_runtime_lifespan,
)
from app.services.scheduling.tasks.task_registry import (
    ScheduledTaskRegistry,
)


class FakeManager:
    """Minimal manager for lifespan tests."""

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


def create_app(
    runtime: SchedulerRuntime,
    lifespan,
) -> FastAPI:
    """Create an application with its runtime installed."""

    app = FastAPI(lifespan=lifespan)
    install_scheduler_runtime(app, runtime)
    return app


@pytest.mark.asyncio
async def test_startup_and_shutdown(
    runtime: SchedulerRuntime,
    manager: FakeManager,
) -> None:
    lifespan = create_scheduler_runtime_lifespan()
    app = create_app(runtime, lifespan)

    async with app.router.lifespan_context(app):
        assert runtime.state == SchedulerLifecycleState.RUNNING
        assert manager.start_calls == 1
        assert manager.shutdown_calls == 0

    assert runtime.state == SchedulerLifecycleState.STOPPED
    assert manager.shutdown_calls == 1


@pytest.mark.asyncio
async def test_callback_execution_order(
    runtime: SchedulerRuntime,
) -> None:
    events: list[str] = []

    lifespan = create_scheduler_runtime_lifespan(
        before_start=lambda app: events.append("before_start"),
        after_start=lambda app: events.append("after_start"),
        before_shutdown=lambda app: events.append("before_shutdown"),
        after_shutdown=lambda app: events.append("after_shutdown"),
    )

    app = create_app(runtime, lifespan)

    async with app.router.lifespan_context(app):
        events.append("application_running")

    assert events == [
        "before_start",
        "after_start",
        "application_running",
        "before_shutdown",
        "after_shutdown",
    ]


@pytest.mark.asyncio
async def test_async_callbacks_are_supported(
    runtime: SchedulerRuntime,
) -> None:
    events: list[str] = []

    async def callback(name: str) -> None:
        events.append(name)

    lifespan = create_scheduler_runtime_lifespan(
        before_start=lambda app: callback("before_start"),
        after_start=lambda app: callback("after_start"),
        before_shutdown=lambda app: callback("before_shutdown"),
        after_shutdown=lambda app: callback("after_shutdown"),
    )

    app = create_app(runtime, lifespan)

    async with app.router.lifespan_context(app):
        events.append("running")

    assert events == [
        "before_start",
        "after_start",
        "running",
        "before_shutdown",
        "after_shutdown",
    ]


@pytest.mark.asyncio
async def test_before_shutdown_failure_does_not_skip_runtime_shutdown(
    runtime: SchedulerRuntime,
    manager: FakeManager,
) -> None:
    events: list[str] = []

    def before_shutdown(app: FastAPI) -> None:
        events.append("before_shutdown")
        raise RuntimeError("Pre-shutdown callback failed")

    lifespan = create_scheduler_runtime_lifespan(
        before_shutdown=before_shutdown,
        after_shutdown=lambda app: events.append("after_shutdown"),
    )

    app = create_app(runtime, lifespan)

    with pytest.raises(
        SchedulerRuntimeLifespanError,
        match="shutdown operations failed",
    ):
        async with app.router.lifespan_context(app):
            pass

    assert events == [
        "before_shutdown",
        "after_shutdown",
    ]
    assert manager.shutdown_calls == 1
    assert runtime.state == SchedulerLifecycleState.STOPPED


@pytest.mark.asyncio
async def test_runtime_shutdown_failure_does_not_skip_after_callback(
    runtime: SchedulerRuntime,
    manager: FakeManager,
) -> None:
    events: list[str] = []
    manager.fail_shutdown = True

    lifespan = create_scheduler_runtime_lifespan(
        after_shutdown=lambda app: events.append("after_shutdown"),
    )

    app = create_app(runtime, lifespan)

    with pytest.raises(SchedulerRuntimeLifespanError):
        async with app.router.lifespan_context(app):
            pass

    assert events == ["after_shutdown"]
    assert manager.shutdown_calls == 1


@pytest.mark.asyncio
async def test_after_shutdown_failure_does_not_undo_runtime_shutdown(
    runtime: SchedulerRuntime,
    manager: FakeManager,
) -> None:
    def after_shutdown(app: FastAPI) -> None:
        raise RuntimeError("Post-shutdown callback failed")

    lifespan = create_scheduler_runtime_lifespan(
        after_shutdown=after_shutdown,
    )

    app = create_app(runtime, lifespan)

    with pytest.raises(
        SchedulerRuntimeLifespanError,
        match="shutdown operations failed",
    ):
        async with app.router.lifespan_context(app):
            pass

    assert manager.shutdown_calls == 1
    assert runtime.state == SchedulerLifecycleState.STOPPED


@pytest.mark.asyncio
async def test_multiple_shutdown_failures_attempt_every_operation(
    runtime: SchedulerRuntime,
    manager: FakeManager,
) -> None:
    events: list[str] = []

    def before_shutdown(app: FastAPI) -> None:
        events.append("before_shutdown")
        raise RuntimeError("First shutdown failure")

    def after_shutdown(app: FastAPI) -> None:
        events.append("after_shutdown")
        raise ValueError("Second shutdown failure")

    lifespan = create_scheduler_runtime_lifespan(
        before_shutdown=before_shutdown,
        after_shutdown=after_shutdown,
    )

    app = create_app(runtime, lifespan)

    with pytest.raises(
        SchedulerRuntimeLifespanError,
    ):
        async with app.router.lifespan_context(app):
            pass

    assert events == [
        "before_shutdown",
        "after_shutdown",
    ]
    assert manager.shutdown_calls == 1


@pytest.mark.asyncio
async def test_application_exception_is_preserved_when_shutdown_fails(
    runtime: SchedulerRuntime,
    manager: FakeManager,
) -> None:
    manager.fail_shutdown = True

    lifespan = create_scheduler_runtime_lifespan(
        before_shutdown=lambda app: (
            (_ for _ in ()).throw(
                RuntimeError("Shutdown callback failed")
            )
        ),
    )

    app = create_app(runtime, lifespan)

    with pytest.raises(
        ValueError,
        match="Application failure",
    ):
        async with app.router.lifespan_context(app):
            raise ValueError("Application failure")

    assert manager.shutdown_calls == 1


@pytest.mark.asyncio
async def test_application_exception_is_preserved_when_callback_fails(
    runtime: SchedulerRuntime,
    manager: FakeManager,
) -> None:
    def before_shutdown(app: FastAPI) -> None:
        raise RuntimeError("Shutdown callback failed")

    lifespan = create_scheduler_runtime_lifespan(
        before_shutdown=before_shutdown,
    )

    app = create_app(runtime, lifespan)

    with pytest.raises(
        ValueError,
        match="Original application error",
    ):
        async with app.router.lifespan_context(app):
            raise ValueError("Original application error")

    assert manager.shutdown_calls == 1
    assert runtime.state == SchedulerLifecycleState.STOPPED


@pytest.mark.asyncio
async def test_before_start_failure_does_not_start_runtime(
    runtime: SchedulerRuntime,
    manager: FakeManager,
) -> None:
    def before_start(app: FastAPI) -> None:
        raise RuntimeError("Before-start failed")

    lifespan = create_scheduler_runtime_lifespan(
        before_start=before_start,
    )

    app = create_app(runtime, lifespan)

    with pytest.raises(RuntimeError, match="Before-start failed"):
        async with app.router.lifespan_context(app):
            pass

    assert manager.start_calls == 0
    assert manager.shutdown_calls == 0


@pytest.mark.asyncio
async def test_manager_start_failure_triggers_rollback(
    runtime: SchedulerRuntime,
    manager: FakeManager,
) -> None:
    manager.fail_start = True

    lifespan = create_scheduler_runtime_lifespan()
    app = create_app(runtime, lifespan)

    with pytest.raises(Exception):
        async with app.router.lifespan_context(app):
            pass

    assert manager.start_calls == 1
    assert manager.shutdown_calls == 1


@pytest.mark.asyncio
async def test_after_start_failure_triggers_rollback(
    runtime: SchedulerRuntime,
    manager: FakeManager,
) -> None:
    def after_start(app: FastAPI) -> None:
        raise RuntimeError("After-start failed")

    lifespan = create_scheduler_runtime_lifespan(
        after_start=after_start,
    )

    app = create_app(runtime, lifespan)

    with pytest.raises(RuntimeError, match="After-start failed"):
        async with app.router.lifespan_context(app):
            pass

    assert manager.start_calls == 1
    assert manager.shutdown_calls == 1
    assert runtime.state == SchedulerLifecycleState.STOPPED


@pytest.mark.asyncio
async def test_startup_cancellation_triggers_rollback(
    runtime: SchedulerRuntime,
    manager: FakeManager,
) -> None:
    async def after_start(app: FastAPI) -> None:
        raise asyncio.CancelledError()

    lifespan = create_scheduler_runtime_lifespan(
        after_start=after_start,
    )

    app = create_app(runtime, lifespan)

    with pytest.raises(asyncio.CancelledError):
        async with app.router.lifespan_context(app):
            pass

    assert manager.start_calls == 1
    assert manager.shutdown_calls == 1


@pytest.mark.asyncio
async def test_shutdown_cancellation_does_not_skip_cleanup(
    runtime: SchedulerRuntime,
    manager: FakeManager,
) -> None:
    events: list[str] = []

    async def before_shutdown(app: FastAPI) -> None:
        events.append("before_shutdown")
        raise asyncio.CancelledError()

    async def after_shutdown(app: FastAPI) -> None:
        events.append("after_shutdown")

    lifespan = create_scheduler_runtime_lifespan(
        before_shutdown=before_shutdown,
        after_shutdown=after_shutdown,
    )

    app = create_app(runtime, lifespan)

    with pytest.raises(asyncio.CancelledError):
        async with app.router.lifespan_context(app):
            pass

    assert events == [
        "before_shutdown",
        "after_shutdown",
    ]
    assert manager.shutdown_calls == 1


@pytest.mark.asyncio
async def test_application_exception_is_preserved_over_shutdown_cancellation(
    runtime: SchedulerRuntime,
    manager: FakeManager,
) -> None:
    async def before_shutdown(app: FastAPI) -> None:
        raise asyncio.CancelledError()

    lifespan = create_scheduler_runtime_lifespan(
        before_shutdown=before_shutdown,
    )

    app = create_app(runtime, lifespan)

    with pytest.raises(ValueError, match="Application failure"):
        async with app.router.lifespan_context(app):
            raise ValueError("Application failure")

    assert manager.shutdown_calls == 1


@pytest.mark.asyncio
async def test_missing_runtime_is_reported() -> None:
    app = FastAPI(lifespan=create_scheduler_runtime_lifespan())

    with pytest.raises(Exception, match="not installed"):
        async with app.router.lifespan_context(app):
            pass


@pytest.mark.parametrize(
    "callback_name",
    [
        "before_start",
        "after_start",
        "before_shutdown",
        "after_shutdown",
    ],
)
def test_invalid_callback_is_rejected(callback_name: str) -> None:
    with pytest.raises(TypeError):
        create_scheduler_runtime_lifespan(
            **{callback_name: "invalid"},
        )


@pytest.mark.asyncio
async def test_shutdown_operations_are_attempted_in_order(
    runtime: SchedulerRuntime,
    manager: FakeManager,
) -> None:
    events: list[str] = []

    async def before_shutdown(app: FastAPI) -> None:
        events.append("before")

    async def after_shutdown(app: FastAPI) -> None:
        events.append("after")

    lifespan = create_scheduler_runtime_lifespan(
        before_shutdown=before_shutdown,
        after_shutdown=after_shutdown,
    )

    app = create_app(runtime, lifespan)

    async with app.router.lifespan_context(app):
        pass

    assert events == ["before", "after"]
    assert manager.shutdown_calls == 1
