
"""Tests for the scheduler runtime facade."""

from __future__ import annotations

from typing import Any
from unittest.mock import Mock

import pytest

from app.services.scheduling.scheduler_lifecycle import (
    SchedulerLifecycle,
    SchedulerLifecycleState,
)
from app.services.scheduling.scheduler_runtime import (
    SchedulerRuntime,
    SchedulerRuntimeError,
)
from app.services.scheduling.tasks.task_registry import (
    ScheduledTaskRegistry,
)


class FakeManager:
    """Test double for the scheduling manager."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.results: dict[str, Any] = {}
        self.errors: dict[str, Exception] = {}

    async def start(self) -> None:
        self.calls.append(("start", (), {}))
        self._raise_if_configured("start")

    async def shutdown(self) -> None:
        self.calls.append(("shutdown", (), {}))
        self._raise_if_configured("shutdown")

    async def create_job(self, *args: Any, **kwargs: Any) -> Any:
        return self._record("create_job", *args, **kwargs)

    async def update_job(self, *args: Any, **kwargs: Any) -> Any:
        return self._record("update_job", *args, **kwargs)

    async def delete_job(self, *args: Any, **kwargs: Any) -> Any:
        return self._record("delete_job", *args, **kwargs)

    async def enable_job(self, *args: Any, **kwargs: Any) -> Any:
        return self._record("enable_job", *args, **kwargs)

    async def disable_job(self, *args: Any, **kwargs: Any) -> Any:
        return self._record("disable_job", *args, **kwargs)

    async def list_jobs(self, *args: Any, **kwargs: Any) -> Any:
        return self._record("list_jobs", *args, **kwargs)

    async def restore_jobs(self, *args: Any, **kwargs: Any) -> Any:
        return self._record("restore_jobs", *args, **kwargs)

    def _record(
        self,
        name: str,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        self.calls.append((name, args, kwargs))
        self._raise_if_configured(name)
        return self.results.get(name)

    def _raise_if_configured(self, name: str) -> None:
        error = self.errors.get(name)

        if error is not None:
            raise error


@pytest.fixture
def manager() -> FakeManager:
    return FakeManager()


@pytest.fixture
def registry() -> Mock:
    """Return a registry test double satisfying the concrete type check."""

    instance = Mock(spec=ScheduledTaskRegistry)
    instance.get_all.return_value = []
    instance.names.return_value = ()
    instance.get_optional.return_value = None
    instance.contains.return_value = False
    return instance


@pytest.fixture
def runtime(
    manager: FakeManager,
    registry: Mock,
) -> SchedulerRuntime:
    return SchedulerRuntime(manager, registry)


def test_runtime_accepts_valid_dependencies(
    manager: FakeManager,
    registry: Mock,
) -> None:
    runtime = SchedulerRuntime(manager, registry)

    assert runtime.manager is manager
    assert runtime.task_registry is registry
    assert isinstance(runtime.lifecycle, SchedulerLifecycle)


def test_runtime_rejects_missing_manager(
    registry: Mock,
) -> None:
    with pytest.raises(ValueError, match="manager is required"):
        SchedulerRuntime(None, registry)


def test_runtime_rejects_invalid_task_registry(
    manager: FakeManager,
) -> None:
    with pytest.raises(TypeError, match="ScheduledTaskRegistry"):
        SchedulerRuntime(manager, object())  # type: ignore[arg-type]


def test_runtime_rejects_invalid_lifecycle(
    manager: FakeManager,
    registry: Mock,
) -> None:
    with pytest.raises(TypeError, match="SchedulerLifecycle"):
        SchedulerRuntime(
            manager,
            registry,
            lifecycle=object(),  # type: ignore[arg-type]
        )


def test_runtime_rejects_callbacks_with_existing_lifecycle(
    manager: FakeManager,
    registry: Mock,
) -> None:
    lifecycle = SchedulerLifecycle(manager)

    with pytest.raises(ValueError, match="callbacks"):
        SchedulerRuntime(
            manager,
            registry,
            lifecycle=lifecycle,
            before_start=lambda: None,
        )


def test_runtime_rejects_monitor_with_existing_lifecycle(
    manager: FakeManager,
    registry: Mock,
) -> None:
    lifecycle = SchedulerLifecycle(manager)

    with pytest.raises(ValueError, match="health_monitor"):
        SchedulerRuntime(
            manager,
            registry,
            lifecycle=lifecycle,
            health_monitor=object(),
        )


def test_runtime_exposes_initial_state(
    runtime: SchedulerRuntime,
) -> None:
    assert runtime.state == SchedulerLifecycleState.STOPPED
    assert runtime.is_running is False
    assert runtime.last_error is None


@pytest.mark.asyncio
async def test_start_delegates_to_lifecycle(
    runtime: SchedulerRuntime,
    manager: FakeManager,
) -> None:
    await runtime.start()

    assert runtime.is_running is True
    assert manager.calls == [("start", (), {})]


@pytest.mark.asyncio
async def test_shutdown_delegates_to_lifecycle(
    runtime: SchedulerRuntime,
    manager: FakeManager,
) -> None:
    await runtime.start()
    await runtime.shutdown()

    assert runtime.state == SchedulerLifecycleState.STOPPED
    assert [call[0] for call in manager.calls] == [
        "start",
        "shutdown",
    ]


@pytest.mark.asyncio
async def test_restart_delegates_to_lifecycle(
    runtime: SchedulerRuntime,
    manager: FakeManager,
) -> None:
    await runtime.start()
    await runtime.restart()

    assert runtime.is_running is True
    assert [call[0] for call in manager.calls] == [
        "start",
        "shutdown",
        "start",
    ]


@pytest.mark.asyncio
async def test_start_logs_and_propagates_failure(
    manager: FakeManager,
    registry: Mock,
) -> None:
    manager.errors["start"] = RuntimeError("Startup failed")
    runtime = SchedulerRuntime(manager, registry)

    with pytest.raises(Exception, match="Failed to start scheduling subsystem"):
        await runtime.start()

    assert runtime.state == SchedulerLifecycleState.FAILED
    assert runtime.last_error is not None


@pytest.mark.asyncio
async def test_shutdown_logs_and_propagates_failure(
    manager: FakeManager,
    registry: Mock,
) -> None:
    runtime = SchedulerRuntime(manager, registry)

    await runtime.start()

    manager.errors["shutdown"] = RuntimeError("Shutdown failed")

    with pytest.raises(SchedulerLifecycleError):
        await runtime.shutdown()

    assert runtime.state == SchedulerLifecycleState.FAILED


@pytest.mark.asyncio
async def test_register_task_delegates_to_registry(
    runtime: SchedulerRuntime,
    registry: Mock,
) -> None:
    task = object()

    runtime.register_task(task)

    registry.register.assert_called_once_with(task)


@pytest.mark.asyncio
async def test_register_tasks_delegates_batch(
    runtime: SchedulerRuntime,
    registry: Mock,
) -> None:
    tasks = [object(), object()]

    runtime.register_tasks(tasks)

    registry.register_many.assert_called_once_with(tasks)


def test_get_task_returns_registered_task(
    runtime: SchedulerRuntime,
    registry: Mock,
) -> None:
    task = object()
    registry.get_optional.return_value = task

    assert runtime.get_task("cleanup") is task

    registry.get_optional.assert_called_once_with("cleanup")


def test_get_task_raises_when_task_is_missing(
    runtime: SchedulerRuntime,
    registry: Mock,
) -> None:
    registry.get_optional.return_value = None

    with pytest.raises(
        SchedulerRuntimeError,
        match="Scheduled task is not registered",
    ):
        runtime.get_task("missing")


def test_get_task_optional_returns_task_or_none(
    runtime: SchedulerRuntime,
    registry: Mock,
) -> None:
    task = object()
    registry.get_optional.return_value = task

    assert runtime.get_task_optional("cleanup") is task

    registry.get_optional.return_value = None

    assert runtime.get_task_optional("missing") is None


def test_unregister_task_removes_registered_task(
    runtime: SchedulerRuntime,
    registry: Mock,
) -> None:
    task = object()
    registry.get_optional.return_value = task

    result = runtime.unregister_task("cleanup")

    assert result is task
    registry.unregister.assert_called_once_with("cleanup")


def test_unregister_task_raises_when_missing(
    runtime: SchedulerRuntime,
    registry: Mock,
) -> None:
    registry.get_optional.return_value = None

    with pytest.raises(SchedulerRuntimeError):
        runtime.unregister_task("missing")

    registry.unregister.assert_not_called()


def test_has_task_delegates_to_registry(
    runtime: SchedulerRuntime,
    registry: Mock,
) -> None:
    registry.contains.return_value = True

    assert runtime.has_task("cleanup") is True

    registry.contains.assert_called_once_with("cleanup")


def test_get_registered_task_names(
    runtime: SchedulerRuntime,
    registry: Mock,
) -> None:
    registry.names.return_value = ("cleanup", "backup")

    assert runtime.get_registered_task_names() == (
        "cleanup",
        "backup",
    )


def test_get_registered_tasks(
    runtime: SchedulerRuntime,
    registry: Mock,
) -> None:
    tasks = [object(), object()]
    registry.get_all.return_value = tasks

    result = runtime.get_registered_tasks()

    assert result == tuple(tasks)
    assert isinstance(result, tuple)


@pytest.mark.asyncio
async def test_create_job_delegates_arguments(
    runtime: SchedulerRuntime,
    manager: FakeManager,
) -> None:
    expected = {"job_id": "job-1"}
    manager.results["create_job"] = expected

    result = await runtime.create_job(
        "forwarding",
        trigger_type="interval",
        seconds=60,
    )

    assert result is expected
    assert manager.calls[-1] == (
        "create_job",
        ("forwarding",),
        {"trigger_type": "interval", "seconds": 60},
    )


@pytest.mark.asyncio
async def test_update_job_delegates_arguments(
    runtime: SchedulerRuntime,
    manager: FakeManager,
) -> None:
    await runtime.update_job(
        "job-1",
        enabled=False,
    )

    assert manager.calls[-1] == (
        "update_job",
        ("job-1",),
        {"enabled": False},
    )


@pytest.mark.asyncio
async def test_delete_job_delegates_arguments(
    runtime: SchedulerRuntime,
    manager: FakeManager,
) -> None:
    await runtime.delete_job("job-1")

    assert manager.calls[-1] == (
        "delete_job",
        ("job-1",),
        {},
    )


@pytest.mark.asyncio
async def test_enable_job_delegates_arguments(
    runtime: SchedulerRuntime,
    manager: FakeManager,
) -> None:
    await runtime.enable_job("job-1")

    assert manager.calls[-1] == (
        "enable_job",
        ("job-1",),
        {},
    )


@pytest.mark.asyncio
async def test_disable_job_delegates_arguments(
    runtime: SchedulerRuntime,
    manager: FakeManager,
) -> None:
    await runtime.disable_job("job-1")

    assert manager.calls[-1] == (
        "disable_job",
        ("job-1",),
        {},
    )


@pytest.mark.asyncio
async def test_list_jobs_delegates_arguments(
    runtime: SchedulerRuntime,
    manager: FakeManager,
) -> None:
    expected = ["job-1", "job-2"]
    manager.results["list_jobs"] = expected

    result = await runtime.list_jobs(enabled=True)

    assert result is expected
    assert manager.calls[-1] == (
        "list_jobs",
        (),
        {"enabled": True},
    )


@pytest.mark.asyncio
async def test_restore_jobs_delegates_arguments(
    runtime: SchedulerRuntime,
    manager: FakeManager,
) -> None:
    expected = {"restored": 2}
    manager.results["restore_jobs"] = expected

    result = await runtime.restore_jobs()

    assert result is expected
    assert manager.calls[-1] == (
        "restore_jobs",
        (),
        {},
    )


@pytest.mark.asyncio
async def test_missing_manager_operation_raises(
    runtime: SchedulerRuntime,
) -> None:
    with pytest.raises(
        SchedulerRuntimeError,
        match="does not implement",
    ):
        await runtime._call_manager("unknown_operation")


@pytest.mark.asyncio
async def test_manager_operation_error_is_wrapped(
    runtime: SchedulerRuntime,
    manager: FakeManager,
) -> None:
    manager.errors["create_job"] = ValueError("Invalid job")

    with pytest.raises(
        SchedulerRuntimeError,
        match="Scheduler operation failed: create_job",
    ) as error:
        await runtime.create_job("invalid")

    assert isinstance(error.value.__cause__, ValueError)


@pytest.mark.asyncio
async def test_sync_manager_operation_is_supported(
    runtime: SchedulerRuntime,
    manager: FakeManager,
) -> None:
    expected = {"result": "sync"}

    def synchronous_operation(value: str) -> dict[str, str]:
        assert value == "test"
        return expected

    manager.synchronous_operation = synchronous_operation

    result = await runtime._call_manager(
        "synchronous_operation",
        "test",
    )

    assert result is expected


@pytest.mark.asyncio
async def test_async_manager_operation_is_supported(
    runtime: SchedulerRuntime,
    manager: FakeManager,
) -> None:
    expected = {"result": "async"}

    async def asynchronous_operation(value: str) -> dict[str, str]:
        assert value == "test"
        return expected

    manager.asynchronous_operation = asynchronous_operation

    result = await runtime._call_manager(
        "asynchronous_operation",
        "test",
    )

    assert result is expected


@pytest.mark.asyncio
async def test_runtime_status_before_start(
    runtime: SchedulerRuntime,
) -> None:
    status = runtime.get_status()

    assert status["state"] == "stopped"
    assert status["is_running"] is False
    assert status["last_error"] is None
    assert status["manager_started"] is False
    assert status["monitor_started"] is False
    assert status["registered_task_count"] == 0
    assert status["registered_task_names"] == []


@pytest.mark.asyncio
async def test_runtime_status_after_start(
    runtime: SchedulerRuntime,
    registry: Mock,
) -> None:
    registry.get_all.return_value = [object(), object()]
    registry.names.return_value = ("cleanup", "backup")

    await runtime.start()

    status = runtime.get_status()

    assert status["state"] == "running"
    assert status["is_running"] is True
    assert status["manager_started"] is True
    assert status["registered_task_count"] == 2
    assert status["registered_task_names"] == [
        "cleanup",
        "backup",
    ]


@pytest.mark.asyncio
async def test_runtime_status_after_shutdown(
    runtime: SchedulerRuntime,
) -> None:
    await runtime.start()
    await runtime.shutdown()

    status = runtime.get_status()

    assert status["state"] == "stopped"
    assert status["is_running"] is False
    assert status["manager_started"] is False


@pytest.mark.asyncio
async def test_existing_lifecycle_is_reused(
    manager: FakeManager,
    registry: Mock,
) -> None:
    lifecycle = SchedulerLifecycle(manager)

    runtime = SchedulerRuntime(
        manager,
        registry,
        lifecycle=lifecycle,
    )

    assert runtime.lifecycle is lifecycle


@pytest.mark.asyncio
async def test_runtime_accepts_optional_health_monitor(
    manager: FakeManager,
    registry: Mock,
) -> None:
    monitor = Mock()
    monitor.start = Mock()
    monitor.stop = Mock()

    async def start(*, run_immediately: bool = True) -> None:
        monitor.start_calls += 1

    async def stop() -> None:
        monitor.stop_calls += 1

    monitor.start_calls = 0
    monitor.stop_calls = 0
    monitor.start = start
    monitor.stop = stop

    runtime = SchedulerRuntime(
        manager,
        registry,
        health_monitor=monitor,
    )

    await runtime.start()

    assert monitor.start_calls == 1
    assert runtime.lifecycle.monitor_started is True

    await runtime.shutdown()

    assert monitor.stop_calls == 1
    assert runtime.lifecycle.monitor_started is False
