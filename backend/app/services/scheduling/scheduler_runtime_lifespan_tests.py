
"""Tests for SchedulerRuntime FastAPI lifespan integration."""

from __future__ import annotations

from typing import Any

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
    """Test manager for runtime lifespan tests."""

    def __init__(self) -> None:
        self.start_calls = 0
        self.shutdown_calls = 0

        self.start_error: Exception | None = None
        self.shutdown_error: Exception | None = None

        self.events: list[str] = []

    async def start(self) -> None:
        self.start_calls += 1
        self.events.append("manager_start")

        if self.start_error is not None:
            raise self.start_error

    async def shutdown(self) -> None:
        self.shutdown_calls += 1
        self.events.append("manager_shutdown")

        if self.shutdown_error is not None:
            raise self.shutdown_error


@pytest.fixture
def app() -> FastAPI:
    return FastAPI()


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
def installed_app(
    app: FastAPI,
    runtime: SchedulerRuntime,
) -> FastAPI:
    install_scheduler_runtime(app, runtime)
    return app


@pytest.mark.asyncio
async def test_lifespan_starts_and_stops_runtime(
    installed_app: FastAPI,
    runtime: SchedulerRuntime,
    manager: FakeManager,
) -> None:
    lifespan = create_scheduler_runtime_lifespan()

    async with lifespan(installed_app):
        assert runtime.is_running is True
        assert runtime.state == SchedulerLifecycleState.RUNNING

    assert runtime.state == SchedulerLifecycleState.STOPPED
    assert manager.start_calls == 1
    assert manager.shutdown_calls == 1


@pytest.mark.asyncio
async def test_lifespan_callback_order(
    installed_app: FastAPI,
    manager: FakeManager,
) -> None:
    events: list[str] = []

    def before_start(app: FastAPI) -> None:
        assert app is installed_app
        events.append("before_start")

    async def after_start(app: FastAPI) -> None:
        assert app is installed_app
        events.append("after_start")

    def before_shutdown(app: FastAPI) -> None:
        assert app is installed_app
        events.append("before_shutdown")

    async def after_shutdown(app: FastAPI) -> None:
        assert app is installed_app
        events.append("after_shutdown")

    lifespan = create_scheduler_runtime_lifespan(
        before_start=before_start,
        after_start=after_start,
        before_shutdown=before_shutdown,
        after_shutdown=after_shutdown,
    )

    async with lifespan(installed_app):
        events.append("application_running")

    assert events == [
        "before_start",
        "after_start",
        "application_running",
        "before_shutdown",
        "after_shutdown",
    ]

    assert manager.events == [
        "manager_start",
        "manager_shutdown",
    ]


@pytest.mark.asyncio
async def test_sync_callbacks_are_supported(
    installed_app: FastAPI,
) -> None:
    events: list[str] = []

    def callback(name: str):
        def execute(app: FastAPI) -> None:
            events.append(name)

        return execute

    lifespan = create_scheduler_runtime_lifespan(
        before_start=callback("before_start"),
        after_start=callback("after_start"),
        before_shutdown=callback("before_shutdown"),
        after_shutdown=callback("after_shutdown"),
    )

    async with lifespan(installed_app):
        pass

    assert events == [
        "before_start",
        "after_start",
        "before_shutdown",
        "after_shutdown",
    ]


@pytest.mark.asyncio
async def test_async_callbacks_are_supported(
    installed_app: FastAPI,
) -> None:
    events: list[str] = []

    async def callback(name: str, app: FastAPI) -> None:
        events.append(name)

    lifespan = create_scheduler_runtime_lifespan(
        before_start=lambda app: callback("before_start", app),
        after_start=lambda app: callback("after_start", app),
        before_shutdown=lambda app: callback("before_shutdown", app),
        after_shutdown=lambda app: callback("after_shutdown", app),
    )

    async with lifespan(installed_app):
        pass

    assert events == [
        "before_start",
        "after_start",
        "before_shutdown",
        "after_shutdown",
    ]


@pytest.mark.asyncio
async def test_lifespan_requires_installed_runtime(
    app: FastAPI,
) -> None:
    lifespan = create_scheduler_runtime_lifespan()

    with pytest.raises(Exception, match="not installed"):
        async with lifespan(app):
            pass


@pytest.mark.asyncio
async def test_before_start_failure_prevents_runtime_start(
    installed_app: FastAPI,
    runtime: SchedulerRuntime,
    manager: FakeManager,
) -> None:
    async def fail(app: FastAPI) -> None:
        raise RuntimeError("Before-start callback failed")

    lifespan = create_scheduler_runtime_lifespan(
        before_start=fail,
    )

    with pytest.raises(
        SchedulerRuntimeLifespanError,
        match="startup failed",
    ):
        async with lifespan(installed_app):
            pass

    assert manager.start_calls == 0
    assert manager.shutdown_calls == 0
    assert runtime.state == SchedulerLifecycleState.STOPPED


@pytest.mark.asyncio
async def test_manager_start_failure_is_propagated(
    installed_app: FastAPI,
    runtime: SchedulerRuntime,
    manager: FakeManager,
) -> None:
    manager.start_error = RuntimeError("Manager startup failed")

    lifespan = create_scheduler_runtime_lifespan()

    with pytest.raises(
        SchedulerRuntimeLifespanError,
        match="startup failed",
    ):
        async with lifespan(installed_app):
            pass

    assert manager.start_calls == 1
    assert manager.shutdown_calls == 1
    assert runtime.state == SchedulerLifecycleState.FAILED


@pytest.mark.asyncio
async def test_after_start_failure_triggers_runtime_cleanup(
    installed_app: FastAPI,
    runtime: SchedulerRuntime,
    manager: FakeManager,
) -> None:
    async def fail(app: FastAPI) -> None:
        raise RuntimeError("After-start callback failed")

    lifespan = create_scheduler_runtime_lifespan(
        after_start=fail,
    )

    with pytest.raises(
        SchedulerRuntimeLifespanError,
        match="startup failed",
    ):
        async with lifespan(installed_app):
            pass

    assert manager.start_calls == 1
    assert manager.shutdown_calls == 1
    assert runtime.state == SchedulerLifecycleState.STOPPED


@pytest.mark.asyncio
async def test_normal_shutdown_executes_callbacks(
    installed_app: FastAPI,
) -> None:
    events: list[str] = []

    def before_shutdown(app: FastAPI) -> None:
        events.append("before_shutdown")

    async def after_shutdown(app: FastAPI) -> None:
        events.append("after_shutdown")

    lifespan = create_scheduler_runtime_lifespan(
        before_shutdown=before_shutdown,
        after_shutdown=after_shutdown,
    )

    async with lifespan(installed_app):
        pass

    assert events == [
        "before_shutdown",
        "after_shutdown",
    ]


@pytest.mark.asyncio
async def test_application_exception_is_preserved(
    installed_app: FastAPI,
    runtime: SchedulerRuntime,
    manager: FakeManager,
) -> None:
    lifespan = create_scheduler_runtime_lifespan()

    with pytest.raises(
        ValueError,
        match="Application execution failed",
    ):
        async with lifespan(installed_app):
            assert runtime.is_running is True
            raise ValueError("Application execution failed")

    assert runtime.state == SchedulerLifecycleState.STOPPED
    assert manager.shutdown_calls == 1


@pytest.mark.asyncio
async def test_application_exception_still_runs_shutdown_callbacks(
    installed_app: FastAPI,
) -> None:
    events: list[str] = []

    lifespan = create_scheduler_runtime_lifespan(
        before_shutdown=lambda app: events.append("before_shutdown"),
        after_shutdown=lambda app: events.append("after_shutdown"),
    )

    with pytest.raises(RuntimeError, match="Application failure"):
        async with lifespan(installed_app):
            raise RuntimeError("Application failure")

    assert events == [
        "before_shutdown",
        "after_shutdown",
    ]


@pytest.mark.asyncio
async def test_shutdown_failure_during_application_exception_does_not_replace_it(
    installed_app: FastAPI,
    runtime: SchedulerRuntime,
    manager: FakeManager,
) -> None:
    manager.shutdown_error = RuntimeError("Shutdown failed")

    lifespan = create_scheduler_runtime_lifespan()

    with pytest.raises(RuntimeError, match="Application failure"):
        async with lifespan(installed_app):
            raise RuntimeError("Application failure")

    assert runtime.state == SchedulerLifecycleState.FAILED


@pytest.mark.asyncio
async def test_normal_shutdown_failure_is_wrapped(
    installed_app: FastAPI,
    runtime: SchedulerRuntime,
    manager: FakeManager,
) -> None:
    lifespan = create_scheduler_runtime_lifespan()

    with pytest.raises(
        SchedulerRuntimeLifespanError,
        match="shutdown failed",
    ):
        async with lifespan(installed_app):
            manager.shutdown_error = RuntimeError(
                "Manager shutdown failed"
            )

    assert runtime.state == SchedulerLifecycleState.FAILED


@pytest.mark.asyncio
async def test_after_shutdown_failure_is_propagated(
    installed_app: FastAPI,
    runtime: SchedulerRuntime,
) -> None:
    async def fail(app: FastAPI) -> None:
        raise RuntimeError("After-shutdown callback failed")

    lifespan = create_scheduler_runtime_lifespan(
        after_shutdown=fail,
    )

    with pytest.raises(
        SchedulerRuntimeLifespanError,
        match="shutdown failed",
    ):
        async with lifespan(installed_app):
            assert runtime.is_running is True

    assert runtime.state == SchedulerLifecycleState.STOPPED


@pytest.mark.asyncio
async def test_shutdown_callback_failure_does_not_replace_application_error(
    installed_app: FastAPI,
) -> None:
    async def fail(app: FastAPI) -> None:
        raise RuntimeError("Shutdown callback failed")

    lifespan = create_scheduler_runtime_lifespan(
        before_shutdown=fail,
    )

    with pytest.raises(
        ValueError,
        match="Original application error",
    ):
        async with lifespan(installed_app):
            raise ValueError("Original application error")


@pytest.mark.asyncio
async def test_startup_callback_receives_correct_application(
    installed_app: FastAPI,
) -> None:
    received: list[FastAPI] = []

    def callback(app: FastAPI) -> None:
        received.append(app)

    lifespan = create_scheduler_runtime_lifespan(
        before_start=callback,
    )

    async with lifespan(installed_app):
        pass

    assert received == [installed_app]


@pytest.mark.asyncio
async def test_shutdown_callbacks_receive_correct_application(
    installed_app: FastAPI,
) -> None:
    received: list[FastAPI] = []

    def callback(app: FastAPI) -> None:
        received.append(app)

    lifespan = create_scheduler_runtime_lifespan(
        before_shutdown=callback,
        after_shutdown=callback,
    )

    async with lifespan(installed_app):
        pass

    assert received == [
        installed_app,
        installed_app,
    ]


def test_lifespan_factory_rejects_invalid_callback() -> None:
    with pytest.raises(TypeError, match="before_start"):
        create_scheduler_runtime_lifespan(
            before_start="invalid",  # type: ignore[arg-type]
        )


def test_lifespan_factory_accepts_no_callbacks() -> None:
    lifespan = create_scheduler_runtime_lifespan()

    assert callable(lifespan)


@pytest.mark.asyncio
async def test_lifespan_does_not_start_runtime_during_factory_creation(
    installed_app: FastAPI,
    runtime: SchedulerRuntime,
    manager: FakeManager,
) -> None:
    lifespan = create_scheduler_runtime_lifespan()

    assert runtime.state == SchedulerLifecycleState.STOPPED
    assert manager.start_calls == 0

    async with lifespan(installed_app):
        assert runtime.is_running is True


@pytest.mark.asyncio
async def test_lifespan_stops_runtime_after_normal_exit(
    installed_app: FastAPI,
    runtime: SchedulerRuntime,
) -> None:
    lifespan = create_scheduler_runtime_lifespan()

    async with lifespan(installed_app):
        assert runtime.is_running is True

    assert runtime.is_running is False
    assert runtime.state == SchedulerLifecycleState.STOPPED


@pytest.mark.asyncio
async def test_lifespan_rejects_non_fastapi_application() -> None:
    lifespan = create_scheduler_runtime_lifespan()

    with pytest.raises(TypeError, match="FastAPI"):
        async with lifespan(object()):  # type: ignore[arg-type]
            pass


@pytest.mark.asyncio
async def test_cancelled_application_execution_triggers_cleanup(
    installed_app: FastAPI,
    runtime: SchedulerRuntime,
    manager: FakeManager,
) -> None:
    lifespan = create_scheduler_runtime_lifespan()

    with pytest.raises(asyncio.CancelledError):
        async with lifespan(installed_app):
            raise asyncio.CancelledError()

    assert manager.shutdown_calls == 1
    assert runtime.state == SchedulerLifecycleState.STOPPED


@pytest.mark.asyncio
async def test_runtime_is_not_started_twice_by_one_lifespan(
    installed_app: FastAPI,
    runtime: SchedulerRuntime,
    manager: FakeManager,
) -> None:
    lifespan = create_scheduler_runtime_lifespan()

    async with lifespan(installed_app):
        await runtime.start()

    assert manager.start_calls == 1
    assert manager.shutdown_calls == 1


@pytest.mark.asyncio
async def test_lifespan_can_be_reused_for_separate_applications(
    manager: FakeManager,
) -> None:
    first_app = FastAPI()
    second_app = FastAPI()

    first_runtime = SchedulerRuntime(
        manager,
        ScheduledTaskRegistry(),
    )
    second_runtime = SchedulerRuntime(
        manager,
        ScheduledTaskRegistry(),
    )

    install_scheduler_runtime(first_app, first_runtime)
    install_scheduler_runtime(second_app, second_runtime)

    lifespan = create_scheduler_runtime_lifespan()

    async with lifespan(first_app):
        assert first_runtime.is_running is True

    async with lifespan(second_app):
        assert second_runtime.is_running is True

    assert first_runtime.state == SchedulerLifecycleState.STOPPED
    assert second_runtime.state == SchedulerLifecycleState.STOPPED
