
"""Tests for scheduling integration bootstrap."""

from __future__ import annotations

from typing import Any

import pytest

from app.services.scheduling.integration_bootstrap import (
    BootstrapState,
    SchedulingBootstrapError,
    SchedulingIntegrationBootstrap,
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
) -> dict[str, Any]:
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


def test_initial_state_is_not_started(
    bootstrap: SchedulingIntegrationBootstrap,
) -> None:
    assert bootstrap.state is BootstrapState.NOT_STARTED
    assert bootstrap.report is None


@pytest.mark.asyncio
async def test_bootstrap_with_sync_factories(
    bootstrap: SchedulingIntegrationBootstrap,
) -> None:
    report = await bootstrap.bootstrap()

    assert report.state is BootstrapState.READY
    assert report.context_created is True
    assert report.validation_report is not None
    assert report.validation_report.valid is True
    assert bootstrap.state is BootstrapState.READY


@pytest.mark.asyncio
async def test_bootstrap_with_async_factories(
    components: dict[str, object],
) -> None:
    async def factory(component: object) -> object:
        return component

    factories = {
        name: (
            lambda component=component: factory(component)
        )
        for name, component in components.items()
    }

    bootstrap = SchedulingIntegrationBootstrap(factories)

    report = await bootstrap.bootstrap()

    assert report.state is BootstrapState.READY
    assert bootstrap.state is BootstrapState.READY


@pytest.mark.asyncio
async def test_bootstrap_uses_manager_scheduler_when_optional_factory_absent(
    components: dict[str, object],
) -> None:
    factories = make_factories(components)
    factories.pop("scheduler")

    bootstrap = SchedulingIntegrationBootstrap(factories)

    report = await bootstrap.bootstrap()

    assert report.context_created is True
    assert (
        bootstrap.context.scheduler.component
        is components["scheduler"]
    )


@pytest.mark.asyncio
async def test_bootstrap_is_idempotent_when_ready(
    bootstrap: SchedulingIntegrationBootstrap,
) -> None:
    first = await bootstrap.bootstrap()
    second = await bootstrap.bootstrap()

    assert first is second
    assert bootstrap.state is BootstrapState.READY


@pytest.mark.asyncio
async def test_bootstrap_exposes_context_after_success(
    bootstrap: SchedulingIntegrationBootstrap,
) -> None:
    await bootstrap.bootstrap()

    assert bootstrap.context.is_validated is True


@pytest.mark.asyncio
async def test_context_is_unavailable_before_bootstrap(
    bootstrap: SchedulingIntegrationBootstrap,
) -> None:
    with pytest.raises(SchedulingBootstrapError):
        _ = bootstrap.context


@pytest.mark.asyncio
async def test_factory_returning_none_fails_bootstrap(
    components: dict[str, object],
) -> None:
    factories = make_factories(components)
    factories["job_store"] = lambda: None

    bootstrap = SchedulingIntegrationBootstrap(factories)

    with pytest.raises(SchedulingBootstrapError):
        await bootstrap.bootstrap()

    assert bootstrap.state is BootstrapState.FAILED
    assert bootstrap.context if False else bootstrap.report is not None
    assert bootstrap.report.state is BootstrapState.FAILED


@pytest.mark.asyncio
async def test_factory_exception_fails_bootstrap(
    components: dict[str, object],
) -> None:
    factories = make_factories(components)

    def failing_factory() -> object:
        raise RuntimeError("factory failure")

    factories["task_registry"] = failing_factory

    bootstrap = SchedulingIntegrationBootstrap(factories)

    with pytest.raises(SchedulingBootstrapError) as error:
        await bootstrap.bootstrap()

    assert isinstance(error.value.__cause__, RuntimeError)
    assert bootstrap.state is BootstrapState.FAILED
    assert bootstrap.report is not None
    assert "factory failure" in bootstrap.report.error


@pytest.mark.asyncio
async def test_invalid_component_fails_bootstrap(
    components: dict[str, object],
) -> None:
    factories = make_factories(components)
    factories["task_registry"] = object

    bootstrap = SchedulingIntegrationBootstrap(factories)

    with pytest.raises(SchedulingBootstrapError):
        await bootstrap.bootstrap()

    assert bootstrap.state is BootstrapState.FAILED


def test_missing_required_factory_is_rejected() -> None:
    with pytest.raises(ValueError):
        SchedulingIntegrationBootstrap(
            {"scheduler_manager": lambda: object()}
        )


def test_unknown_factory_name_is_rejected(
    components: dict[str, object],
) -> None:
    factories = make_factories(components)
    factories["unknown"] = lambda: object()

    with pytest.raises(ValueError):
        SchedulingIntegrationBootstrap(factories)


def test_non_callable_factory_is_rejected(
    components: dict[str, object],
) -> None:
    factories = make_factories(components)
    factories["job_store"] = object()

    with pytest.raises(TypeError):
        SchedulingIntegrationBootstrap(factories)


def test_invalid_factory_mapping_is_rejected() -> None:
    with pytest.raises(TypeError):
        SchedulingIntegrationBootstrap(
            None  # type: ignore[arg-type]
        )


def test_invalid_validator_type_is_rejected(
    components: dict[str, object],
) -> None:
    with pytest.raises(TypeError):
        SchedulingIntegrationBootstrap(
            make_factories(components),
            validator=object(),  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_close_releases_context(
    bootstrap: SchedulingIntegrationBootstrap,
) -> None:
    await bootstrap.bootstrap()

    bootstrap.close()

    assert bootstrap.state is BootstrapState.CLOSED
    assert bootstrap.report is not None
    assert bootstrap.report.context_created is False

    with pytest.raises(SchedulingBootstrapError):
        _ = bootstrap.context


@pytest.mark.asyncio
async def test_closed_bootstrap_cannot_restart(
    bootstrap: SchedulingIntegrationBootstrap,
) -> None:
    await bootstrap.bootstrap()
    bootstrap.close()

    with pytest.raises(SchedulingBootstrapError):
        await bootstrap.bootstrap()


@pytest.mark.asyncio
async def test_close_before_bootstrap_is_allowed(
    bootstrap: SchedulingIntegrationBootstrap,
) -> None:
    bootstrap.close()

    assert bootstrap.state is BootstrapState.CLOSED


@pytest.mark.asyncio
async def test_close_does_not_close_underlying_job_store(
    components: dict[str, object],
) -> None:
    class TrackingJobStore(FakeJobStore):
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    store = TrackingJobStore()
    components["job_store"] = store
    components["scheduler_manager"] = FakeSchedulerManager(
        components["scheduler"]  # type: ignore[arg-type]
    )

    bootstrap = SchedulingIntegrationBootstrap(
        make_factories(components)
    )

    await bootstrap.bootstrap()
    bootstrap.close()

    assert store.closed is False


@pytest.mark.asyncio
async def test_bootstrap_does_not_start_scheduler(
    components: dict[str, object],
) -> None:
    scheduler = components["scheduler"]

    class TrackingScheduler(FakeScheduler):
        def __init__(self) -> None:
            self.started = False

        def start(self) -> None:
            self.started = True

    tracking_scheduler = TrackingScheduler()

    components["scheduler"] = tracking_scheduler
    components["scheduler_manager"] = FakeSchedulerManager(
        tracking_scheduler
    )

    bootstrap = SchedulingIntegrationBootstrap(
        make_factories(components)
    )

    await bootstrap.bootstrap()

    assert tracking_scheduler.started is False


@pytest.mark.asyncio
async def test_failed_bootstrap_can_be_retried(
    components: dict[str, object],
) -> None:
    calls = 0

    def initially_failing_factory() -> object:
        nonlocal calls
        calls += 1

        if calls == 1:
            raise RuntimeError("temporary failure")

        return components["task_registry"]

    factories = make_factories(components)
    factories["task_registry"] = initially_failing_factory

    bootstrap = SchedulingIntegrationBootstrap(factories)

    with pytest.raises(SchedulingBootstrapError):
        await bootstrap.bootstrap()

    report = await bootstrap.bootstrap()

    assert report.state is BootstrapState.READY
    assert bootstrap.state is BootstrapState.READY


@pytest.mark.asyncio
async def test_failed_bootstrap_clears_context(
    components: dict[str, object],
) -> None:
    factories = make_factories(components)
    factories["job_store"] = lambda: None

    bootstrap = SchedulingIntegrationBootstrap(factories)

    with pytest.raises(SchedulingBootstrapError):
        await bootstrap.bootstrap()

    assert bootstrap._context is None


@pytest.mark.asyncio
async def test_bootstrap_report_records_failure(
    components: dict[str, object],
) -> None:
    factories = make_factories(components)
    factories["job_store"] = lambda: None

    bootstrap = SchedulingIntegrationBootstrap(factories)

    with pytest.raises(SchedulingBootstrapError):
        await bootstrap.bootstrap()

    assert bootstrap.report is not None
    assert bootstrap.report.state is BootstrapState.FAILED
    assert bootstrap.report.error is not None
