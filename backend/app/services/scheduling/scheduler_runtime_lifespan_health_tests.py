
"""Tests for scheduler runtime lifespan health diagnostics."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi import FastAPI

from app.services.scheduling.scheduler_lifecycle import (
    SchedulerLifecycleState,
)
from app.services.scheduling.scheduler_runtime import SchedulerRuntime
from app.services.scheduling.scheduler_runtime_integration import (
    install_scheduler_runtime,
)
from app.services.scheduling.scheduler_runtime_lifespan_health import (
    SchedulerLifespanHealthReport,
    SchedulerLifespanHealthStatus,
    SchedulerRuntimeLifespanHealthService,
)
from app.services.scheduling.tasks.task_registry import (
    ScheduledTaskRegistry,
)


class FakeScheduler:
    """Minimal scheduler exposing registered jobs."""

    def __init__(self, jobs: list[object] | None = None) -> None:
        self.jobs = jobs or []

    def get_jobs(self) -> list[object]:
        return list(self.jobs)


class FakeManager:
    """Minimal scheduler manager."""

    def __init__(
        self,
        scheduler: FakeScheduler | None = None,
    ) -> None:
        self.scheduler = scheduler
        self.start_calls = 0
        self.shutdown_calls = 0

    async def start(self) -> None:
        self.start_calls += 1

    async def shutdown(self) -> None:
        self.shutdown_calls += 1


class FakeTask:
    """Minimal registered task for count tests."""

    pass


@pytest.fixture
def manager() -> FakeManager:
    return FakeManager(
        scheduler=FakeScheduler(
            jobs=[object(), object()],
        )
    )


@pytest.fixture
def registry() -> ScheduledTaskRegistry:
    task_registry = ScheduledTaskRegistry()
    task_registry.register("task_one", FakeTask())
    task_registry.register("task_two", FakeTask())
    return task_registry


@pytest.fixture
def runtime(
    manager: FakeManager,
    registry: ScheduledTaskRegistry,
) -> SchedulerRuntime:
    return SchedulerRuntime(
        manager=manager,
        task_registry=registry,
    )


@pytest.fixture
def app(runtime: SchedulerRuntime) -> FastAPI:
    application = FastAPI()
    install_scheduler_runtime(application, runtime)
    return application


@pytest.fixture
def health_service() -> SchedulerRuntimeLifespanHealthService:
    return SchedulerRuntimeLifespanHealthService()


def test_health_service_accepts_optional_application() -> None:
    service = SchedulerRuntimeLifespanHealthService()

    assert service is not None


def test_health_service_rejects_invalid_application() -> None:
    with pytest.raises(TypeError, match="FastAPI"):
        SchedulerRuntimeLifespanHealthService(
            app=object(),  # type: ignore[arg-type]
        )


def test_inspect_requires_application(
    health_service: SchedulerRuntimeLifespanHealthService,
) -> None:
    with pytest.raises(TypeError, match="FastAPI"):
        health_service.inspect()


def test_missing_runtime_is_unavailable(
    health_service: SchedulerRuntimeLifespanHealthService,
) -> None:
    app = FastAPI()

    report = health_service.inspect(app)

    assert report.status == SchedulerLifespanHealthStatus.UNAVAILABLE
    assert report.runtime_installed is False
    assert report.lifecycle_state == "not_installed"
    assert report.is_running is False
    assert report.registered_task_count is None
    assert report.scheduled_job_count is None
    assert "Scheduler runtime is not installed" in report.details


def test_stopped_runtime_is_unavailable(
    app: FastAPI,
    health_service: SchedulerRuntimeLifespanHealthService,
) -> None:
    report = health_service.inspect(app)

    assert report.status == SchedulerLifespanHealthStatus.UNAVAILABLE
    assert report.runtime_installed is True
    assert report.lifecycle_state == SchedulerLifecycleState.STOPPED.value
    assert report.is_running is False
    assert "Scheduler runtime is stopped" in report.details


@pytest.mark.asyncio
async def test_running_runtime_is_healthy(
    app: FastAPI,
    runtime: SchedulerRuntime,
    health_service: SchedulerRuntimeLifespanHealthService,
) -> None:
    await runtime.start()

    try:
        report = health_service.inspect(app)

        assert report.status == SchedulerLifespanHealthStatus.HEALTHY
        assert report.runtime_installed is True
        assert report.lifecycle_state == SchedulerLifecycleState.RUNNING.value
        assert report.is_running is True
    finally:
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_is_healthy_returns_true_for_running_runtime(
    app: FastAPI,
    runtime: SchedulerRuntime,
    health_service: SchedulerRuntimeLifespanHealthService,
) -> None:
    await runtime.start()

    try:
        assert health_service.is_healthy(app) is True
    finally:
        await runtime.shutdown()


def test_is_healthy_returns_false_for_stopped_runtime(
    app: FastAPI,
    health_service: SchedulerRuntimeLifespanHealthService,
) -> None:
    assert health_service.is_healthy(app) is False


def test_task_count_is_reported(
    app: FastAPI,
    health_service: SchedulerRuntimeLifespanHealthService,
) -> None:
    report = health_service.inspect(app)

    assert report.registered_task_count == 2


def test_job_count_is_reported(
    app: FastAPI,
    health_service: SchedulerRuntimeLifespanHealthService,
) -> None:
    report = health_service.inspect(app)

    assert report.scheduled_job_count == 2


def test_report_contains_utc_timestamp(
    app: FastAPI,
    health_service: SchedulerRuntimeLifespanHealthService,
) -> None:
    report = health_service.inspect(app)

    assert report.checked_at.tzinfo is not None
    assert report.checked_at.utcoffset().total_seconds() == 0


def test_report_serializes_to_dictionary(
    app: FastAPI,
    health_service: SchedulerRuntimeLifespanHealthService,
) -> None:
    report = health_service.inspect(app)
    result = report.to_dict()

    assert result["status"] == report.status.value
    assert result["runtime_installed"] is True
    assert result["lifecycle_state"] == "stopped"
    assert isinstance(result["checked_at"], str)
    assert isinstance(result["details"], list)


def test_report_rejects_naive_timestamp() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        SchedulerLifespanHealthReport(
            status=SchedulerLifespanHealthStatus.HEALTHY,
            runtime_installed=True,
            lifecycle_state="running",
            is_running=True,
            registered_task_count=0,
            scheduled_job_count=0,
            checked_at=datetime.now(),
        )


@pytest.mark.parametrize(
    "count_field",
    [
        "registered_task_count",
        "scheduled_job_count",
    ],
)
def test_report_rejects_negative_counts(
    count_field: str,
) -> None:
    values = {
        "status": SchedulerLifespanHealthStatus.HEALTHY,
        "runtime_installed": True,
        "lifecycle_state": "running",
        "is_running": True,
        "registered_task_count": 0,
        "scheduled_job_count": 0,
        "checked_at": datetime.now(timezone.utc),
    }

    values[count_field] = -1

    with pytest.raises(ValueError, match="cannot be negative"):
        SchedulerLifespanHealthReport(**values)


def test_report_normalizes_timestamp_to_utc() -> None:
    from datetime import timedelta

    timestamp = datetime(
        2026,
        11,
        13,
        12,
        0,
        tzinfo=timezone(timedelta(hours=5, minutes=30)),
    )

    report = SchedulerLifespanHealthReport(
        status=SchedulerLifespanHealthStatus.HEALTHY,
        runtime_installed=True,
        lifecycle_state="running",
        is_running=True,
        registered_task_count=1,
        scheduled_job_count=1,
        checked_at=timestamp,
    )

    assert report.checked_at.utcoffset().total_seconds() == 0
    assert report.checked_at.hour == 6
    assert report.checked_at.minute == 30


def test_transitional_state_is_degraded(
    health_service: SchedulerRuntimeLifespanHealthService,
) -> None:
    assert (
        health_service._determine_status(
            lifecycle_state=SchedulerLifecycleState.STARTING.value,
            is_running=False,
            details=[],
        )
        == SchedulerLifespanHealthStatus.DEGRADED
    )

    assert (
        health_service._determine_status(
            lifecycle_state=SchedulerLifecycleState.STOPPING.value,
            is_running=False,
            details=[],
        )
        == SchedulerLifespanHealthStatus.DEGRADED
    )


def test_failed_state_is_failed(
    health_service: SchedulerRuntimeLifespanHealthService,
) -> None:
    assert (
        health_service._determine_status(
            lifecycle_state=SchedulerLifecycleState.FAILED.value,
            is_running=False,
            details=[],
        )
        == SchedulerLifespanHealthStatus.FAILED
    )


def test_unknown_state_is_degraded(
    health_service: SchedulerRuntimeLifespanHealthService,
) -> None:
    details: list[str] = []

    status = health_service._determine_status(
        lifecycle_state="unexpected",
        is_running=False,
        details=details,
    )

    assert status == SchedulerLifespanHealthStatus.DEGRADED
    assert "Scheduler lifecycle state is unknown" in details


def test_running_state_with_false_running_indicator_is_degraded(
    health_service: SchedulerRuntimeLifespanHealthService,
) -> None:
    details: list[str] = []

    status = health_service._determine_status(
        lifecycle_state=SchedulerLifecycleState.RUNNING.value,
        is_running=False,
        details=details,
    )

    assert status == SchedulerLifespanHealthStatus.DEGRADED
    assert any("not running" in item for item in details)


def test_running_state_with_true_running_indicator_is_healthy(
    health_service: SchedulerRuntimeLifespanHealthService,
) -> None:
    assert (
        health_service._determine_status(
            lifecycle_state=SchedulerLifecycleState.RUNNING.value,
            is_running=True,
            details=[],
        )
        == SchedulerLifespanHealthStatus.HEALTHY
    )


def test_task_count_unavailable_returns_none() -> None:
    class RuntimeWithoutRegistry:
        pass

    assert (
        SchedulerRuntimeLifespanHealthService._read_task_count(
            RuntimeWithoutRegistry()
        )
        is None
    )


def test_job_count_unavailable_returns_none() -> None:
    class RuntimeWithoutManager:
        pass

    assert (
        SchedulerRuntimeLifespanHealthService._read_job_count(
            RuntimeWithoutManager()
        )
        is None
    )


def test_job_count_without_scheduler_returns_none() -> None:
    class ManagerWithoutScheduler:
        scheduler = None

    class RuntimeWithoutScheduler:
        manager = ManagerWithoutScheduler()

    assert (
        SchedulerRuntimeLifespanHealthService._read_job_count(
            RuntimeWithoutScheduler()
        )
        is None
    )


def test_task_count_reads_registry_names() -> None:
    class Registry:
        def names(self) -> tuple[str, ...]:
            return ("one", "two", "three")

    class RuntimeWithRegistry:
        task_registry = Registry()

    assert (
        SchedulerRuntimeLifespanHealthService._read_task_count(
            RuntimeWithRegistry()
        )
        == 3
    )


def test_job_count_reads_scheduler_jobs() -> None:
    class Scheduler:
        def get_jobs(self) -> list[object]:
            return [object(), object(), object()]

    class Manager:
        scheduler = Scheduler()

    class RuntimeWithManager:
        manager = Manager()

    assert (
        SchedulerRuntimeLifespanHealthService._read_job_count(
            RuntimeWithManager()
        )
        == 3
    )


def test_get_status_returns_serialized_report(
    app: FastAPI,
    health_service: SchedulerRuntimeLifespanHealthService,
) -> None:
    result = health_service.get_status(app)

    assert result["status"] == SchedulerLifespanHealthStatus.UNAVAILABLE.value
    assert result["runtime_installed"] is True
    assert result["lifecycle_state"] == "stopped"


def test_service_can_use_application_from_constructor(
    app: FastAPI,
) -> None:
    service = SchedulerRuntimeLifespanHealthService(app=app)

    report = service.inspect()

    assert report.runtime_installed is True


def test_explicit_application_overrides_constructor_application(
    app: FastAPI,
    health_service: SchedulerRuntimeLifespanHealthService,
) -> None:
    report = health_service.inspect(app)

    assert report.runtime_installed is True


def test_health_service_rejects_invalid_inspection_application(
    health_service: SchedulerRuntimeLifespanHealthService,
) -> None:
    with pytest.raises(TypeError, match="FastAPI"):
        health_service.inspect(object())  # type: ignore[arg-type]
