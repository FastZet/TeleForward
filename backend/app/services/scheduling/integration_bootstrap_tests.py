
"""Regression tests for scheduling bootstrap cleanup and cancellation."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
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


@pytest.mark.asyncio
async def test_bootstrap_success(
    bootstrap: SchedulingIntegrationBootstrap,
) -> None:
    report = await bootstrap.bootstrap()

    assert report.state is BootstrapState.READY
    assert report.context_created is True
    assert report.validation_report is not None
    assert report.validation_report.valid is True
    assert bootstrap.context.is_validated is True


@pytest.mark.asyncio
async def test_bootstrap_is_idempotent(
    bootstrap: SchedulingIntegrationBootstrap,
) -> None:
    first = await bootstrap.bootstrap()
    second = await bootstrap.bootstrap()

    assert first is second


@pytest.mark.asyncio
async def test_concurrent_bootstrap_calls_construct_once(
    components: dict[str, object],
) -> None:
    calls = 0
    started = asyncio.Event()
    finish = asyncio.Event()

    async def manager_factory() -> object:
        nonlocal calls
        calls += 1
        started.set()
        await finish.wait()
        return components["scheduler_manager"]

    factories = make_factories(components)
    factories["scheduler_manager"] = manager_factory

    bootstrap = SchedulingIntegrationBootstrap(factories)

    first = asyncio.create_task(bootstrap.bootstrap())
    await started.wait()

    second = asyncio.create_task(bootstrap.bootstrap())
    finish.set()

    first_report, second_report = await asyncio.gather(
        first,
        second,
    )

    assert first_report is second_report
    assert calls == 1


@pytest.mark.asyncio
async def test_partial_construction_is_cleaned_up_on_factory_failure(
    components: dict[str, object],
) -> None:
    cleanup_order: list[str] = []

    def failing_registry_factory() -> object:
        raise RuntimeError("registry construction failed")

    factories = make_factories(components)
    factories["task_registry"] = failing_registry_factory

    bootstrap = SchedulingIntegrationBootstrap(
        factories,
        cleanup_callbacks={
            "scheduler_manager": (
                lambda component: cleanup_order.append(
                    "scheduler_manager"
                )
            ),
            "job_store": (
                lambda component: cleanup_order.append("job_store")
            ),
        },
    )

    with pytest.raises(SchedulingBootstrapError):
        await bootstrap.bootstrap()

    assert cleanup_order == ["scheduler_manager"]
    assert bootstrap.state is BootstrapState.FAILED
    assert dict(bootstrap.components) == {}


@pytest.mark.asyncio
async def test_partial_construction_cleanup_uses_reverse_order(
    components: dict[str, object],
) -> None:
    cleanup_order: list[str] = []

    def failing_store_factory() -> object:
        raise RuntimeError("store construction failed")

    factories = make_factories(components)
    factories["job_store"] = failing_store_factory

    bootstrap = SchedulingIntegrationBootstrap(
        factories,
        cleanup_callbacks={
            "scheduler_manager": (
                lambda component: cleanup_order.append(
                    "scheduler_manager"
                )
            ),
            "task_registry": (
                lambda component: cleanup_order.append("task_registry")
            ),
            "job_store": (
                lambda component: cleanup_order.append("job_store")
            ),
        },
    )

    with pytest.raises(SchedulingBootstrapError):
        await bootstrap.bootstrap()

    assert cleanup_order == [
        "task_registry",
        "scheduler_manager",
    ]


@pytest.mark.asyncio
async def test_validation_failure_cleans_all_constructed_components(
    components: dict[str, object],
) -> None:
    cleanup_order: list[str] = []

    factories = make_factories(components)
    factories["task_registry"] = lambda: object()

    bootstrap = SchedulingIntegrationBootstrap(
        factories,
        cleanup_callbacks={
            "scheduler_manager": (
                lambda component: cleanup_order.append(
                    "scheduler_manager"
                )
            ),
            "task_registry": (
                lambda component: cleanup_order.append("task_registry")
            ),
            "job_store": (
                lambda component: cleanup_order.append("job_store")
            ),
            "scheduler": (
                lambda component: cleanup_order.append("scheduler")
            ),
        },
    )

    with pytest.raises(SchedulingBootstrapError):
        await bootstrap.bootstrap()

    assert cleanup_order == [
        "scheduler",
        "job_store",
        "task_registry",
        "scheduler_manager",
    ]


@pytest.mark.asyncio
async def test_cleanup_failure_does_not_skip_other_components(
    components: dict[str, object],
) -> None:
    cleanup_order: list[str] = []

    def failing_cleanup(component: object) -> None:
        cleanup_order.append("job_store")
        raise RuntimeError("store cleanup failed")

    bootstrap = SchedulingIntegrationBootstrap(
        make_factories(components),
        cleanup_callbacks={
            "scheduler_manager": (
                lambda component: cleanup_order.append(
                    "scheduler_manager"
                )
            ),
            "job_store": failing_cleanup,
            "task_registry": (
                lambda component: cleanup_order.append("task_registry")
            ),
        },
    )

    await bootstrap.bootstrap()

    with pytest.raises(SchedulingBootstrapError):
        await bootstrap.aclose()

    assert cleanup_order == [
        "job_store",
        "task_registry",
        "scheduler_manager",
    ]
    assert bootstrap.state is BootstrapState.CLOSED
    assert bootstrap.report is not None
    assert "store cleanup failed" in (
        bootstrap.report.error or ""
    )


@pytest.mark.asyncio
async def test_async_cleanup_callbacks_are_supported(
    components: dict[str, object],
) -> None:
    cleanup_order: list[str] = []

    async def cleanup_store(component: object) -> None:
        await asyncio.sleep(0)
        cleanup_order.append("job_store")

    bootstrap = SchedulingIntegrationBootstrap(
        make_factories(components),
        cleanup_callbacks={"job_store": cleanup_store},
    )

    await bootstrap.bootstrap()
    await bootstrap.aclose()

    assert cleanup_order == ["job_store"]


@pytest.mark.asyncio
async def test_cancellation_during_factory_cleans_prior_components(
    components: dict[str, object],
) -> None:
    cleanup_order: list[str] = []
    factory_started = asyncio.Event()
    never_finish = asyncio.Event()

    async def blocking_registry_factory() -> object:
        factory_started.set()
        await never_finish.wait()
        return components["task_registry"]

    factories = make_factories(components)
    factories["task_registry"] = blocking_registry_factory

    bootstrap = SchedulingIntegrationBootstrap(
        factories,
        cleanup_callbacks={
            "scheduler_manager": (
                lambda component: cleanup_order.append(
                    "scheduler_manager"
                )
            ),
        },
    )

    task = asyncio.create_task(bootstrap.bootstrap())
    await factory_started.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert cleanup_order == ["scheduler_manager"]
    assert bootstrap.state is BootstrapState.FAILED
    assert bootstrap.report is not None
    assert bootstrap.report.error == "Bootstrap was cancelled"


@pytest.mark.asyncio
async def test_repeated_cancellation_does_not_interrupt_cleanup(
    components: dict[str, object],
) -> None:
    factory_started = asyncio.Event()
    cleanup_started = asyncio.Event()
    allow_cleanup = asyncio.Event()
    cleanup_finished = asyncio.Event()

    async def blocking_registry_factory() -> object:
        factory_started.set()
        await asyncio.Event().wait()
        return components["task_registry"]

    async def blocking_manager_cleanup(component: object) -> None:
        cleanup_started.set()
        await allow_cleanup.wait()
        cleanup_finished.set()

    factories = make_factories(components)
    factories["task_registry"] = blocking_registry_factory

    bootstrap = SchedulingIntegrationBootstrap(
        factories,
        cleanup_callbacks={
            "scheduler_manager": blocking_manager_cleanup,
        },
    )

    task = asyncio.create_task(bootstrap.bootstrap())
    await factory_started.wait()

    task.cancel()
    await cleanup_started.wait()

    task.cancel()
    await asyncio.sleep(0)

    assert not cleanup_finished.is_set()

    allow_cleanup.set()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert cleanup_finished.is_set()
    assert bootstrap.state is BootstrapState.FAILED


@pytest.mark.asyncio
async def test_aclose_cleans_components_in_reverse_order(
    components: dict[str, object],
) -> None:
    cleanup_order: list[str] = []

    bootstrap = SchedulingIntegrationBootstrap(
        make_factories(components),
        cleanup_callbacks={
            "scheduler_manager": (
                lambda component: cleanup_order.append(
                    "scheduler_manager"
                )
            ),
            "task_registry": (
                lambda component: cleanup_order.append("task_registry")
            ),
            "job_store": (
                lambda component: cleanup_order.append("job_store")
            ),
            "scheduler": (
                lambda component: cleanup_order.append("scheduler")
            ),
        },
    )

    await bootstrap.bootstrap()
    await bootstrap.aclose()

    assert cleanup_order == [
        "scheduler",
        "job_store",
        "task_registry",
        "scheduler_manager",
    ]

    assert bootstrap.state is BootstrapState.CLOSED
    assert dict(bootstrap.components) == {}


@pytest.mark.asyncio
async def test_aclose_is_idempotent(
    components: dict[str, object],
) -> None:
    cleanup_calls = 0

    def cleanup(component: object) -> None:
        nonlocal cleanup_calls
        cleanup_calls += 1

    bootstrap = SchedulingIntegrationBootstrap(
        make_factories(components),
        cleanup_callbacks={"job_store": cleanup},
    )

    await bootstrap.bootstrap()
    await bootstrap.aclose()
    await bootstrap.aclose()

    assert cleanup_calls == 1
    assert bootstrap.state is BootstrapState.CLOSED


@pytest.mark.asyncio
async def test_cancellation_during_aclose_is_deferred(
    components: dict[str, object],
) -> None:
    cleanup_started = asyncio.Event()
    allow_cleanup = asyncio.Event()
    cleanup_finished = asyncio.Event()

    async def blocking_cleanup(component: object) -> None:
        cleanup_started.set()
        await allow_cleanup.wait()
        cleanup_finished.set()

    bootstrap = SchedulingIntegrationBootstrap(
        make_factories(components),
        cleanup_callbacks={"job_store": blocking_cleanup},
    )

    await bootstrap.bootstrap()

    close_task = asyncio.create_task(bootstrap.aclose())
    await cleanup_started.wait()

    close_task.cancel()
    await asyncio.sleep(0)

    assert not cleanup_finished.is_set()

    allow_cleanup.set()

    with pytest.raises(asyncio.CancelledError):
        await close_task

    assert cleanup_finished.is_set()
    assert bootstrap.state is BootstrapState.CLOSED


@pytest.mark.asyncio
async def test_aclose_before_bootstrap_is_allowed(
    bootstrap: SchedulingIntegrationBootstrap,
) -> None:
    await bootstrap.aclose()

    assert bootstrap.state is BootstrapState.CLOSED


@pytest.mark.asyncio
async def test_closed_bootstrap_cannot_restart(
    bootstrap: SchedulingIntegrationBootstrap,
) -> None:
    await bootstrap.bootstrap()
    await bootstrap.aclose()

    with pytest.raises(SchedulingBootstrapError):
        await bootstrap.bootstrap()


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
    assert calls == 2


@pytest.mark.asyncio
async def test_context_unavailable_after_close(
    bootstrap: SchedulingIntegrationBootstrap,
) -> None:
    await bootstrap.bootstrap()
    await bootstrap.aclose()

    with pytest.raises(SchedulingBootstrapError):
        _ = bootstrap.context


@pytest.mark.asyncio
async def test_close_releases_references_without_cleanup(
    components: dict[str, object],
) -> None:
    cleanup_calls = 0

    def cleanup(component: object) -> None:
        nonlocal cleanup_calls
        cleanup_calls += 1

    bootstrap = SchedulingIntegrationBootstrap(
        make_factories(components),
        cleanup_callbacks={"job_store": cleanup},
    )

    await bootstrap.bootstrap()
    bootstrap.close()

    assert bootstrap.state is BootstrapState.CLOSED
    assert cleanup_calls == 0


@pytest.mark.asyncio
async def test_components_property_is_read_only(
    bootstrap: SchedulingIntegrationBootstrap,
) -> None:
    await bootstrap.bootstrap()

    snapshot = bootstrap.components

    with pytest.raises(TypeError):
        snapshot["new_component"] = object()  # type: ignore[index]


@pytest.mark.asyncio
async def test_bootstrap_does_not_start_scheduler(
    components: dict[str, object],
) -> None:
    class TrackingScheduler(FakeScheduler):
        def __init__(self) -> None:
            self.started = False

        def start(self) -> None:
            self.started = True

    scheduler = TrackingScheduler()
    components["scheduler"] = scheduler
    components["scheduler_manager"] = FakeSchedulerManager(scheduler)

    bootstrap = SchedulingIntegrationBootstrap(
        make_factories(components)
    )

    await bootstrap.bootstrap()

    assert scheduler.started is False


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


def test_unknown_cleanup_component_is_rejected(
    components: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        SchedulingIntegrationBootstrap(
            make_factories(components),
            cleanup_callbacks={"unknown": lambda component: None},
        )


def test_cleanup_callback_without_factory_is_rejected(
    components: dict[str, object],
) -> None:
    factories = make_factories(components)
    factories.pop("scheduler")

    with pytest.raises(ValueError):
        SchedulingIntegrationBootstrap(
            factories,
            cleanup_callbacks={
                "scheduler": lambda component: None,
            },
        )


def test_non_callable_cleanup_callback_is_rejected(
    components: dict[str, object],
) -> None:
    with pytest.raises(TypeError):
        SchedulingIntegrationBootstrap(
            make_factories(components),
            cleanup_callbacks={"job_store": object()},
        )


def test_non_mapping_cleanup_callbacks_are_rejected(
    components: dict[str, object],
) -> None:
    with pytest.raises(TypeError):
        SchedulingIntegrationBootstrap(
            make_factories(components),
            cleanup_callbacks="invalid",  # type: ignore[arg-type]
        )
