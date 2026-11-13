
"""Tests for the scheduling subsystem lifecycle coordinator."""

from __future__ import annotations

from typing import Any

import pytest

from app.services.scheduling.scheduler_lifecycle import (
    SchedulerLifecycle,
    SchedulerLifecycleError,
    SchedulerLifecycleState,
)


class FakeSchedulerManager:
    """Test double for the scheduling manager."""

    def __init__(self) -> None:
        self.start_calls = 0
        self.shutdown_calls = 0
        self.start_error: Exception | None = None
        self.shutdown_error: Exception | None = None

    async def start(self) -> None:
        self.start_calls += 1

        if self.start_error is not None:
            raise self.start_error

    async def shutdown(self) -> None:
        self.shutdown_calls += 1

        if self.shutdown_error is not None:
            raise self.shutdown_error


class FakeHealthMonitor:
    """Test double for the scheduler health monitor."""

    def __init__(self) -> None:
        self.start_calls = 0
        self.stop_calls = 0
        self.start_arguments: list[bool] = []
        self.start_error: Exception | None = None
        self.stop_error: Exception | None = None

    async def start(self, *, run_immediately: bool = True) -> None:
        self.start_calls += 1
        self.start_arguments.append(run_immediately)

        if self.start_error is not None:
            raise self.start_error

    async def stop(self) -> None:
        self.stop_calls += 1

        if self.stop_error is not None:
            raise self.stop_error


@pytest.fixture
def manager() -> FakeSchedulerManager:
    return FakeSchedulerManager()


@pytest.fixture
def monitor() -> FakeHealthMonitor:
    return FakeHealthMonitor()


@pytest.fixture
def lifecycle(
    manager: FakeSchedulerManager,
    monitor: FakeHealthMonitor,
) -> SchedulerLifecycle:
    return SchedulerLifecycle(
        manager,
        health_monitor=monitor,
    )


@pytest.mark.asyncio
async def test_initial_state_is_stopped(
    lifecycle: SchedulerLifecycle,
) -> None:
    assert lifecycle.state == SchedulerLifecycleState.STOPPED
    assert lifecycle.is_running is False
    assert lifecycle.manager_started is False
    assert lifecycle.monitor_started is False
    assert lifecycle.last_error is None


@pytest.mark.asyncio
async def test_start_starts_manager_and_monitor(
    lifecycle: SchedulerLifecycle,
    manager: FakeSchedulerManager,
    monitor: FakeHealthMonitor,
) -> None:
    await lifecycle.start()

    assert manager.start_calls == 1
    assert monitor.start_calls == 1

    assert lifecycle.state == SchedulerLifecycleState.RUNNING
    assert lifecycle.is_running is True
    assert lifecycle.manager_started is True
    assert lifecycle.monitor_started is True


@pytest.mark.asyncio
async def test_start_passes_monitor_execution_option(
    manager: FakeSchedulerManager,
    monitor: FakeHealthMonitor,
) -> None:
    lifecycle = SchedulerLifecycle(
        manager,
        health_monitor=monitor,
        monitor_run_immediately=False,
    )

    await lifecycle.start()

    assert monitor.start_arguments == [False]


@pytest.mark.asyncio
async def test_start_is_idempotent(
    lifecycle: SchedulerLifecycle,
    manager: FakeSchedulerManager,
    monitor: FakeHealthMonitor,
) -> None:
    await lifecycle.start()
    await lifecycle.start()

    assert manager.start_calls == 1
    assert monitor.start_calls == 1


@pytest.mark.asyncio
async def test_shutdown_stops_monitor_before_manager(
    manager: FakeSchedulerManager,
    monitor: FakeHealthMonitor,
) -> None:
    events: list[str] = []

    async def monitor_stop() -> None:
        events.append("monitor_stop")
        await original_monitor_stop()

    async def manager_shutdown() -> None:
        events.append("manager_shutdown")
        await original_manager_shutdown()

    original_monitor_stop = monitor.stop
    original_manager_shutdown = manager.shutdown

    monitor.stop = monitor_stop  # type: ignore[method-assign]
    manager.shutdown = manager_shutdown  # type: ignore[method-assign]

    lifecycle = SchedulerLifecycle(
        manager,
        health_monitor=monitor,
    )

    await lifecycle.start()
    await lifecycle.shutdown()

    assert events == ["monitor_stop", "manager_shutdown"]


@pytest.mark.asyncio
async def test_shutdown_resets_lifecycle_state(
    lifecycle: SchedulerLifecycle,
    manager: FakeSchedulerManager,
    monitor: FakeHealthMonitor,
) -> None:
    await lifecycle.start()
    await lifecycle.shutdown()

    assert lifecycle.state == SchedulerLifecycleState.STOPPED
    assert lifecycle.is_running is False
    assert lifecycle.manager_started is False
    assert lifecycle.monitor_started is False
    assert lifecycle.last_error is None

    assert manager.shutdown_calls == 1
    assert monitor.stop_calls == 1


@pytest.mark.asyncio
async def test_shutdown_is_idempotent(
    lifecycle: SchedulerLifecycle,
    manager: FakeSchedulerManager,
    monitor: FakeHealthMonitor,
) -> None:
    await lifecycle.start()

    await lifecycle.shutdown()
    await lifecycle.shutdown()

    assert manager.shutdown_calls == 1
    assert monitor.stop_calls == 1


@pytest.mark.asyncio
async def test_startup_callback_order(
    manager: FakeSchedulerManager,
    monitor: FakeHealthMonitor,
) -> None:
    events: list[str] = []

    def before_start() -> None:
        events.append("before_start")

    async def after_start() -> None:
        events.append("after_start")

    original_start = manager.start

    async def tracked_start() -> None:
        events.append("manager_start")
        await original_start()

    manager.start = tracked_start  # type: ignore[method-assign]

    original_monitor_start = monitor.start

    async def tracked_monitor_start(
        *,
        run_immediately: bool = True,
    ) -> None:
        events.append("monitor_start")
        await original_monitor_start(
            run_immediately=run_immediately,
        )

    monitor.start = tracked_monitor_start  # type: ignore[method-assign]

    lifecycle = SchedulerLifecycle(
        manager,
        health_monitor=monitor,
        before_start=before_start,
        after_start=after_start,
    )

    await lifecycle.start()

    assert events == [
        "before_start",
        "manager_start",
        "monitor_start",
        "after_start",
    ]


@pytest.mark.asyncio
async def test_shutdown_callback_order(
    manager: FakeSchedulerManager,
    monitor: FakeHealthMonitor,
) -> None:
    events: list[str] = []

    lifecycle = SchedulerLifecycle(
        manager,
        health_monitor=monitor,
        before_shutdown=lambda: events.append("before_shutdown"),
        after_shutdown=lambda: events.append("after_shutdown"),
    )

    await lifecycle.start()

    original_monitor_stop = monitor.stop
    original_manager_shutdown = manager.shutdown

    async def tracked_monitor_stop() -> None:
        events.append("monitor_stop")
        await original_monitor_stop()

    async def tracked_manager_shutdown() -> None:
        events.append("manager_shutdown")
        await original_manager_shutdown()

    monitor.stop = tracked_monitor_stop  # type: ignore[method-assign]
    manager.shutdown = tracked_manager_shutdown  # type: ignore[method-assign]

    await lifecycle.shutdown()

    assert events == [
        "before_shutdown",
        "monitor_stop",
        "manager_shutdown",
        "after_shutdown",
    ]


@pytest.mark.asyncio
async def test_startup_failure_sets_failed_state(
    manager: FakeSchedulerManager,
    monitor: FakeHealthMonitor,
) -> None:
    manager.start_error = RuntimeError("Manager startup failed")

    lifecycle = SchedulerLifecycle(
        manager,
        health_monitor=monitor,
    )

    with pytest.raises(
        SchedulerLifecycleError,
        match="Failed to start scheduling subsystem",
    ):
        await lifecycle.start()

    assert lifecycle.state == SchedulerLifecycleState.FAILED
    assert lifecycle.is_running is False
    assert lifecycle.manager_started is False
    assert lifecycle.monitor_started is False
    assert lifecycle.last_error is not None


@pytest.mark.asyncio
async def test_manager_startup_failure_does_not_start_monitor(
    manager: FakeSchedulerManager,
    monitor: FakeHealthMonitor,
) -> None:
    manager.start_error = RuntimeError("Manager startup failed")

    lifecycle = SchedulerLifecycle(
        manager,
        health_monitor=monitor,
    )

    with pytest.raises(SchedulerLifecycleError):
        await lifecycle.start()

    assert monitor.start_calls == 0


@pytest.mark.asyncio
async def test_monitor_startup_failure_rolls_back_manager(
    manager: FakeSchedulerManager,
    monitor: FakeHealthMonitor,
) -> None:
    monitor.start_error = RuntimeError("Monitor startup failed")

    lifecycle = SchedulerLifecycle(
        manager,
        health_monitor=monitor,
    )

    with pytest.raises(SchedulerLifecycleError):
        await lifecycle.start()

    assert manager.start_calls == 1
    assert manager.shutdown_calls == 1

    assert lifecycle.manager_started is False
    assert lifecycle.monitor_started is False
    assert lifecycle.state == SchedulerLifecycleState.FAILED


@pytest.mark.asyncio
async def test_after_start_failure_rolls_back_components(
    manager: FakeSchedulerManager,
    monitor: FakeHealthMonitor,
) -> None:
    async def fail() -> None:
        raise RuntimeError("Post-start callback failed")

    lifecycle = SchedulerLifecycle(
        manager,
        health_monitor=monitor,
        after_start=fail,
    )

    with pytest.raises(SchedulerLifecycleError):
        await lifecycle.start()

    assert monitor.stop_calls == 1
    assert manager.shutdown_calls == 1

    assert lifecycle.manager_started is False
    assert lifecycle.monitor_started is False
    assert lifecycle.state == SchedulerLifecycleState.FAILED


@pytest.mark.asyncio
async def test_startup_rollback_failure_preserves_started_flag(
    manager: FakeSchedulerManager,
    monitor: FakeHealthMonitor,
) -> None:
    monitor.start_error = RuntimeError("Monitor startup failed")
    manager.shutdown_error = RuntimeError("Manager cleanup failed")

    lifecycle = SchedulerLifecycle(
        manager,
        health_monitor=monitor,
    )

    with pytest.raises(SchedulerLifecycleError):
        await lifecycle.start()

    assert lifecycle.manager_started is True
    assert lifecycle.state == SchedulerLifecycleState.FAILED

    manager.shutdown_error = None

    await lifecycle.shutdown()

    assert manager.shutdown_calls == 2
    assert lifecycle.manager_started is False
    assert lifecycle.state == SchedulerLifecycleState.STOPPED


@pytest.mark.asyncio
async def test_shutdown_continues_after_monitor_stop_failure(
    manager: FakeSchedulerManager,
    monitor: FakeHealthMonitor,
) -> None:
    monitor.stop_error = RuntimeError("Monitor stop failed")

    lifecycle = SchedulerLifecycle(
        manager,
        health_monitor=monitor,
    )

    await lifecycle.start()

    with pytest.raises(
        SchedulerLifecycleError,
        match="shutdown operations failed",
    ):
        await lifecycle.shutdown()

    assert manager.shutdown_calls == 1
    assert lifecycle.manager_started is False

    assert lifecycle.monitor_started is True
    assert lifecycle.state == SchedulerLifecycleState.FAILED


@pytest.mark.asyncio
async def test_shutdown_failure_can_be_retried(
    manager: FakeSchedulerManager,
    monitor: FakeHealthMonitor,
) -> None:
    manager.shutdown_error = RuntimeError("Shutdown failed")

    lifecycle = SchedulerLifecycle(
        manager,
        health_monitor=monitor,
    )

    await lifecycle.start()

    with pytest.raises(SchedulerLifecycleError):
        await lifecycle.shutdown()

    assert lifecycle.manager_started is True
    assert lifecycle.monitor_started is False

    manager.shutdown_error = None

    await lifecycle.shutdown()

    assert lifecycle.state == SchedulerLifecycleState.STOPPED
    assert lifecycle.manager_started is False


@pytest.mark.asyncio
async def test_shutdown_runs_all_callbacks_after_failure(
    manager: FakeSchedulerManager,
    monitor: FakeHealthMonitor,
) -> None:
    events: list[str] = []

    def fail_before_shutdown() -> None:
        events.append("before_shutdown")
        raise RuntimeError("Pre-shutdown failed")

    def after_shutdown() -> None:
        events.append("after_shutdown")

    lifecycle = SchedulerLifecycle(
        manager,
        health_monitor=monitor,
        before_shutdown=fail_before_shutdown,
        after_shutdown=after_shutdown,
    )

    await lifecycle.start()

    with pytest.raises(SchedulerLifecycleError):
        await lifecycle.shutdown()

    assert events == [
        "before_shutdown",
        "after_shutdown",
    ]

    assert manager.shutdown_calls == 1
    assert monitor.stop_calls == 1


@pytest.mark.asyncio
async def test_shutdown_without_health_monitor(
    manager: FakeSchedulerManager,
) -> None:
    lifecycle = SchedulerLifecycle(manager)

    await lifecycle.start()
    await lifecycle.shutdown()

    assert manager.start_calls == 1
    assert manager.shutdown_calls == 1
    assert lifecycle.state == SchedulerLifecycleState.STOPPED


@pytest.mark.asyncio
async def test_restart_stops_and_starts_components_again(
    lifecycle: SchedulerLifecycle,
    manager: FakeSchedulerManager,
    monitor: FakeHealthMonitor,
) -> None:
    await lifecycle.start()
    await lifecycle.restart()

    assert manager.start_calls == 2
    assert manager.shutdown_calls == 1

    assert monitor.start_calls == 2
    assert monitor.stop_calls == 1

    assert lifecycle.state == SchedulerLifecycleState.RUNNING


@pytest.mark.asyncio
async def test_restart_from_stopped_state_starts_components(
    lifecycle: SchedulerLifecycle,
    manager: FakeSchedulerManager,
    monitor: FakeHealthMonitor,
) -> None:
    await lifecycle.restart()

    assert manager.start_calls == 1
    assert monitor.start_calls == 1
    assert lifecycle.state == SchedulerLifecycleState.RUNNING


@pytest.mark.asyncio
async def test_sync_callbacks_are_supported(
    manager: FakeSchedulerManager,
) -> None:
    events: list[str] = []

    lifecycle = SchedulerLifecycle(
        manager,
        before_start=lambda: events.append("before_start"),
        after_start=lambda: events.append("after_start"),
        before_shutdown=lambda: events.append("before_shutdown"),
        after_shutdown=lambda: events.append("after_shutdown"),
    )

    await lifecycle.start()
    await lifecycle.shutdown()

    assert events == [
        "before_start",
        "after_start",
        "before_shutdown",
        "after_shutdown",
    ]


@pytest.mark.asyncio
async def test_async_callbacks_are_supported(
    manager: FakeSchedulerManager,
) -> None:
    events: list[str] = []

    async def callback(name: str) -> None:
        events.append(name)

    lifecycle = SchedulerLifecycle(
        manager,
        before_start=lambda: callback("before_start"),
        after_start=lambda: callback("after_start"),
    )

    await lifecycle.start()

    assert events == [
        "before_start",
        "after_start",
    ]


@pytest.mark.asyncio
async def test_start_clears_previous_error_after_successful_restart(
    manager: FakeSchedulerManager,
) -> None:
    manager.start_error = RuntimeError("Initial failure")

    lifecycle = SchedulerLifecycle(manager)

    with pytest.raises(SchedulerLifecycleError):
        await lifecycle.start()

    assert lifecycle.last_error is not None

    manager.start_error = None

    await lifecycle.start()

    assert lifecycle.last_error is None
    assert lifecycle.state == SchedulerLifecycleState.RUNNING


def test_constructor_rejects_missing_manager() -> None:
    with pytest.raises(ValueError, match="manager is required"):
        SchedulerLifecycle(None)


def test_constructor_rejects_manager_without_start() -> None:
    class InvalidManager:
        async def shutdown(self) -> None:
            pass

    with pytest.raises(TypeError, match="start"):
        SchedulerLifecycle(InvalidManager())


def test_constructor_rejects_manager_without_shutdown() -> None:
    class InvalidManager:
        async def start(self) -> None:
            pass

    with pytest.raises(TypeError, match="shutdown"):
        SchedulerLifecycle(InvalidManager())


def test_constructor_rejects_invalid_callback(
    manager: FakeSchedulerManager,
) -> None:
    with pytest.raises(TypeError, match="before_start"):
        SchedulerLifecycle(
            manager,
            before_start="invalid",  # type: ignore[arg-type]
        )


def test_constructor_rejects_non_boolean_monitor_option(
    manager: FakeSchedulerManager,
) -> None:
    with pytest.raises(TypeError, match="boolean"):
        SchedulerLifecycle(
            manager,
            monitor_run_immediately=1,  # type: ignore[arg-type]
        )


def test_constructor_rejects_invalid_health_monitor(
    manager: FakeSchedulerManager,
) -> None:
    with pytest.raises(TypeError, match="health_monitor"):
        SchedulerLifecycle(
            manager,
            health_monitor=object(),
        )


@pytest.mark.asyncio
async def test_last_error_contains_shutdown_failure(
    manager: FakeSchedulerManager,
) -> None:
    manager.shutdown_error = RuntimeError("Database shutdown failed")

    lifecycle = SchedulerLifecycle(manager)

    await lifecycle.start()

    with pytest.raises(SchedulerLifecycleError):
        await lifecycle.shutdown()

    assert lifecycle.last_error is not None
    assert "Database shutdown failed" in lifecycle.last_error


@pytest.mark.asyncio
async def test_start_after_failed_shutdown_is_allowed(
    manager: FakeSchedulerManager,
) -> None:
    lifecycle = SchedulerLifecycle(manager)

    await lifecycle.start()

    manager.shutdown_error = RuntimeError("Shutdown failed")

    with pytest.raises(SchedulerLifecycleError):
        await lifecycle.shutdown()

    manager.shutdown_error = None

    await lifecycle.start()

    assert lifecycle.state == SchedulerLifecycleState.RUNNING
    assert manager.start_calls == 2
