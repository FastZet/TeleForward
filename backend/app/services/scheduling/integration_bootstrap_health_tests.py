
"""Tests for scheduling integration bootstrap health reporting."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from app.services.scheduling.integration_bootstrap import (
    BootstrapState,
    SchedulingBootstrapError,
    SchedulingIntegrationBootstrap,
)
from app.services.scheduling.integration_bootstrap_health import (
    BootstrapHealthReport,
    BootstrapHealthStatus,
    SchedulingBootstrapHealthService,
)


class FakeScheduler:
    def add_job(self) -> None:
        pass

    def get_job(self) -> None:
        pass

    def get_jobs(self) -> list[object]:
        return []

    def remove_job(self) -> None:
        pass

    def start(self) -> None:
        pass

    def shutdown(self) -> None:
        pass

    def pause(self) -> None:
        pass

    def resume(self) -> None:
        pass


class FakeSchedulerManager:
    def __init__(self, scheduler: FakeScheduler) -> None:
        self.scheduler = scheduler

    def create_job(self) -> None:
        pass

    def update_job(self) -> None:
        pass

    def delete_job(self) -> None:
        pass

    def enable_job(self) -> None:
        pass

    def disable_job(self) -> None:
        pass

    def list_jobs(self) -> list[str]:
        return []

    def restore_jobs(self) -> int:
        return 0

    def start(self) -> None:
        pass

    def shutdown(self) -> None:
        pass


class FakeTaskRegistry:
    def register(self) -> None:
        pass

    def get(self) -> None:
        pass

    def get_optional(self) -> None:
        pass

    def unregister(self) -> None:
        pass

    def contains(self) -> bool:
        return False

    def names(self) -> tuple[str, ...]:
        return ()

    def get_all(self) -> tuple[object, ...]:
        return ()


class FakeJobStore:
    def add(self) -> None:
        pass

    def get(self) -> None:
        pass

    def list_all(self) -> list[object]:
        return []

    def update(self) -> None:
        pass

    def delete(self) -> None:
        pass

    def close(self) -> None:
        pass


@pytest.fixture
def components() -> dict[str, object]:
    scheduler = FakeScheduler()

    return {
        "scheduler_manager": FakeSchedulerManager(scheduler),
        "task_registry": FakeTaskRegistry(),
        "job_store": FakeJobStore(),
        "scheduler": scheduler,
    }


def make_factories(
    components: dict[str, object],
) -> dict[str, Callable[[], Any]]:
    return {
        name: (lambda component=component: component)
        for name, component in components.items()
    }


@pytest.fixture
def bootstrap(
    components: dict[str, object],
) -> SchedulingIntegrationBootstrap:
    return SchedulingIntegrationBootstrap(
        make_factories(components)
    )


@pytest.fixture
def health_service() -> SchedulingBootstrapHealthService:
    return SchedulingBootstrapHealthService()


@pytest.mark.asyncio
async def test_unbound_service_reports_unavailable(
    health_service: SchedulingBootstrapHealthService,
) -> None:
    report = health_service.inspect()

    assert report.status is BootstrapHealthStatus.UNAVAILABLE
    assert report.bootstrap_state is BootstrapState.NOT_STARTED
    assert report.context_available is False
    assert report.required_components_available is False
    assert report.validation_passed is None
    assert set(report.missing_components) == {
        "scheduler_manager",
        "task_registry",
        "job_store",
    }


@pytest.mark.asyncio
async def test_unbound_service_is_not_healthy(
    health_service: SchedulingBootstrapHealthService,
) -> None:
    assert health_service.is_healthy() is False


@pytest.mark.asyncio
async def test_not_started_bootstrap_reports_unavailable(
    bootstrap: SchedulingIntegrationBootstrap,
) -> None:
    service = SchedulingBootstrapHealthService(bootstrap)

    report = service.inspect()

    assert report.status is BootstrapHealthStatus.UNAVAILABLE
    assert report.bootstrap_state is BootstrapState.NOT_STARTED
    assert report.context_available is False


@pytest.mark.asyncio
async def test_successful_bootstrap_reports_healthy(
    bootstrap: SchedulingIntegrationBootstrap,
) -> None:
    await bootstrap.bootstrap()

    service = SchedulingBootstrapHealthService(bootstrap)
    report = service.inspect()

    assert report.status is BootstrapHealthStatus.HEALTHY
    assert report.bootstrap_state is BootstrapState.READY
    assert report.context_available is True
    assert report.required_components_available is True
    assert report.validation_passed is True
    assert report.missing_components == ()


@pytest.mark.asyncio
async def test_successful_bootstrap_lists_required_components(
    bootstrap: SchedulingIntegrationBootstrap,
) -> None:
    await bootstrap.bootstrap()

    report = SchedulingBootstrapHealthService(
        bootstrap
    ).inspect()

    assert set(report.available_components) == {
        "scheduler_manager",
        "task_registry",
        "job_store",
    }


@pytest.mark.asyncio
async def test_health_report_has_timezone_aware_timestamp(
    bootstrap: SchedulingIntegrationBootstrap,
) -> None:
    await bootstrap.bootstrap()

    report = SchedulingBootstrapHealthService(
        bootstrap
    ).inspect()

    assert report.checked_at.tzinfo is not None
    assert report.checked_at.utcoffset() is not None


@pytest.mark.asyncio
async def test_failed_bootstrap_reports_failed(
    components: dict[str, object],
) -> None:
    factories = make_factories(components)
    factories["task_registry"] = lambda: None

    bootstrap = SchedulingIntegrationBootstrap(factories)

    with pytest.raises(SchedulingBootstrapError):
        await bootstrap.bootstrap()

    report = SchedulingBootstrapHealthService(
        bootstrap
    ).inspect()

    assert report.status is BootstrapHealthStatus.FAILED
    assert report.bootstrap_state is BootstrapState.FAILED
    assert report.context_available is False
    assert report.validation_passed is None


@pytest.mark.asyncio
async def test_failed_bootstrap_reports_missing_components(
    components: dict[str, object],
) -> None:
    factories = make_factories(components)
    factories["task_registry"] = lambda: None

    bootstrap = SchedulingIntegrationBootstrap(factories)

    with pytest.raises(SchedulingBootstrapError):
        await bootstrap.bootstrap()

    report = SchedulingBootstrapHealthService(
        bootstrap
    ).inspect()

    assert "scheduler_manager" in report.missing_components
    assert "task_registry" in report.missing_components
    assert "job_store" in report.missing_components


@pytest.mark.asyncio
async def test_cleanup_failures_are_reported(
    components: dict[str, object],
) -> None:
    factories = make_factories(components)
    factories["task_registry"] = lambda: None

    def failing_cleanup(component: object) -> None:
        raise RuntimeError("manager cleanup failure")

    bootstrap = SchedulingIntegrationBootstrap(
        factories,
        cleanup_callbacks={
            "scheduler_manager": failing_cleanup,
        },
    )

    with pytest.raises(SchedulingBootstrapError):
        await bootstrap.bootstrap()

    report = SchedulingBootstrapHealthService(
        bootstrap
    ).inspect()

    assert report.status is BootstrapHealthStatus.FAILED
    assert report.cleanup_failures
    assert any(
        "manager cleanup failure" in failure
        for failure in report.cleanup_failures
    )


@pytest.mark.asyncio
async def test_bootstrap_error_is_in_health_details(
    components: dict[str, object],
) -> None:
    factories = make_factories(components)
    factories["job_store"] = lambda: None

    bootstrap = SchedulingIntegrationBootstrap(factories)

    with pytest.raises(SchedulingBootstrapError):
        await bootstrap.bootstrap()

    report = SchedulingBootstrapHealthService(
        bootstrap
    ).inspect()

    assert any(
        "Bootstrap error:" in detail
        for detail in report.details
    )


@pytest.mark.asyncio
async def test_closed_bootstrap_reports_unavailable(
    bootstrap: SchedulingIntegrationBootstrap,
) -> None:
    await bootstrap.bootstrap()
    await bootstrap.aclose()

    report = SchedulingBootstrapHealthService(
        bootstrap
    ).inspect()

    assert report.status is BootstrapHealthStatus.UNAVAILABLE
    assert report.bootstrap_state is BootstrapState.CLOSED
    assert report.context_available is False


@pytest.mark.asyncio
async def test_get_status_returns_health_classification(
    bootstrap: SchedulingIntegrationBootstrap,
) -> None:
    await bootstrap.bootstrap()

    service = SchedulingBootstrapHealthService(bootstrap)

    assert service.get_status() is BootstrapHealthStatus.HEALTHY


@pytest.mark.asyncio
async def test_is_healthy_returns_true_after_success(
    bootstrap: SchedulingIntegrationBootstrap,
) -> None:
    await bootstrap.bootstrap()

    service = SchedulingBootstrapHealthService(bootstrap)

    assert service.is_healthy() is True


@pytest.mark.asyncio
async def test_is_healthy_returns_false_after_close(
    bootstrap: SchedulingIntegrationBootstrap,
) -> None:
    await bootstrap.bootstrap()
    await bootstrap.aclose()

    service = SchedulingBootstrapHealthService(bootstrap)

    assert service.is_healthy() is False


@pytest.mark.asyncio
async def test_bind_attaches_bootstrap(
    bootstrap: SchedulingIntegrationBootstrap,
) -> None:
    service = SchedulingBootstrapHealthService()

    service.bind(bootstrap)

    await bootstrap.bootstrap()

    assert service.get_status() is BootstrapHealthStatus.HEALTHY


def test_bind_rejects_invalid_bootstrap(
    health_service: SchedulingBootstrapHealthService,
) -> None:
    with pytest.raises(TypeError):
        health_service.bind(object())  # type: ignore[arg-type]


def test_bootstrap_property_rejects_unbound_service(
    health_service: SchedulingBootstrapHealthService,
) -> None:
    with pytest.raises(RuntimeError):
        _ = health_service.bootstrap


def test_health_report_serializes_to_dictionary(
    health_service: SchedulingBootstrapHealthService,
) -> None:
    report = health_service.inspect()
    payload = report.to_dict()

    assert payload["status"] == "unavailable"
    assert payload["bootstrap_state"] == "not_started"
    assert isinstance(payload["available_components"], list)
    assert isinstance(payload["missing_components"], list)
    assert isinstance(payload["checked_at"], str)


def test_health_report_contains_json_compatible_values(
    health_service: SchedulingBootstrapHealthService,
) -> None:
    payload = health_service.inspect().to_dict()

    assert isinstance(payload["status"], str)
    assert isinstance(payload["bootstrap_state"], str)
    assert isinstance(payload["context_available"], bool)
    assert isinstance(payload["required_components_available"], bool)
    assert isinstance(payload["details"], list)


def test_health_report_rejects_naive_timestamp() -> None:
    from datetime import datetime

    with pytest.raises(ValueError):
        BootstrapHealthReport(
            status=BootstrapHealthStatus.UNAVAILABLE,
            bootstrap_state=BootstrapState.NOT_STARTED,
            context_available=False,
            required_components_available=False,
            available_components=(),
            missing_components=(),
            validation_passed=None,
            cleanup_failures=(),
            checked_at=datetime(2026, 1, 1),
            details=(),
        )


def test_health_report_rejects_non_tuple_details() -> None:
    from datetime import UTC, datetime

    with pytest.raises(TypeError):
        BootstrapHealthReport(
            status=BootstrapHealthStatus.UNAVAILABLE,
            bootstrap_state=BootstrapState.NOT_STARTED,
            context_available=False,
            required_components_available=False,
            available_components=(),
            missing_components=(),
            validation_passed=None,
            cleanup_failures=(),
            checked_at=datetime.now(UTC),
            details=["invalid"],  # type: ignore[arg-type]
        )


def test_cleanup_failure_parser_handles_empty_error() -> None:
    assert (
        SchedulingBootstrapHealthService._extract_cleanup_failures(
            None
        )
        == ()
    )


def test_cleanup_failure_parser_handles_missing_marker() -> None:
    assert (
        SchedulingBootstrapHealthService._extract_cleanup_failures(
            "ordinary bootstrap failure"
        )
        == ()
    )


def test_cleanup_failure_parser_extracts_multiple_failures() -> None:
    result = (
        SchedulingBootstrapHealthService._extract_cleanup_failures(
            "bootstrap failed; cleanup failures: "
            "scheduler_manager: manager failed; "
            "job_store: store failed"
        )
    )

    assert result == (
        "scheduler_manager: manager failed",
        "job_store: store failed",
    )
