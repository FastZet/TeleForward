
"""Tests for the scheduling integration context."""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from app.services.scheduling.integration_context import (
    SchedulingIntegrationContext,
    SchedulingIntegrationContextError,
)
from app.services.scheduling.integration_validator import (
    SchedulingIntegrationError,
    SchedulingIntegrationValidator,
)


class FakeSchedulerManager:
    def __init__(self, scheduler: object) -> None:
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


@pytest.fixture
def components() -> dict[str, object]:
    scheduler = FakeScheduler()

    return {
        "scheduler_manager": FakeSchedulerManager(scheduler),
        "task_registry": FakeTaskRegistry(),
        "job_store": FakeJobStore(),
        "scheduler": scheduler,
    }


def create_context(
    components: dict[str, object],
    **kwargs: object,
) -> SchedulingIntegrationContext:
    return SchedulingIntegrationContext.create(
        scheduler_manager=components["scheduler_manager"],
        task_registry=components["task_registry"],
        job_store=components["job_store"],
        scheduler=components["scheduler"],
        **kwargs,
    )


def test_create_context_successfully_assembles_components(
    components: dict[str, object],
) -> None:
    context = create_context(components)

    assert isinstance(context, SchedulingIntegrationContext)
    assert context.is_validated is True
    assert context.validation_report.valid is True
    assert context.validation_report.components_checked == 4


def test_context_uses_manager_scheduler_when_not_supplied(
    components: dict[str, object],
) -> None:
    context = SchedulingIntegrationContext.create(
        scheduler_manager=components["scheduler_manager"],
        task_registry=components["task_registry"],
        job_store=components["job_store"],
    )

    assert (
        context.get_underlying_component("scheduler")
        is components["scheduler"]
    )


def test_context_rejects_different_scheduler_instance(
    components: dict[str, object],
) -> None:
    with pytest.raises(SchedulingIntegrationContextError):
        SchedulingIntegrationContext.create(
            scheduler_manager=components["scheduler_manager"],
            task_registry=components["task_registry"],
            job_store=components["job_store"],
            scheduler=FakeScheduler(),
        )


def test_context_exposes_all_adapted_components(
    components: dict[str, object],
) -> None:
    context = create_context(components)

    assert set(context.components) == {
        "scheduler_manager",
        "task_registry",
        "job_store",
        "scheduler",
    }


def test_components_mapping_is_read_only(
    components: dict[str, object],
) -> None:
    context = create_context(components)

    assert isinstance(context.components, Mapping)

    with pytest.raises(TypeError):
        context.components["new_component"] = object()  # type: ignore[index]

    with pytest.raises(TypeError):
        del context.components["scheduler"]  # type: ignore[attr-defined]


def test_components_property_returns_fresh_mapping(
    components: dict[str, object],
) -> None:
    context = create_context(components)

    first = context.components
    second = context.components

    assert first is not second
    assert first == second


def test_get_component_returns_canonical_adapter(
    components: dict[str, object],
) -> None:
    context = create_context(components)

    assert context.get_component("scheduler_manager") is (
        context.scheduler_manager
    )
    assert context.get_component("task_registry") is (
        context.task_registry
    )
    assert context.get_component("job_store") is (
        context.job_store
    )
    assert context.get_component("scheduler") is (
        context.scheduler
    )


def test_get_underlying_component_returns_original_instance(
    components: dict[str, object],
) -> None:
    context = create_context(components)

    for name, original in components.items():
        assert context.get_underlying_component(name) is original


def test_unknown_component_raises_key_error(
    components: dict[str, object],
) -> None:
    context = create_context(components)

    with pytest.raises(KeyError):
        context.get_component("unknown")


@pytest.mark.parametrize(
    "component_name",
    [
        "scheduler_manager",
        "task_registry",
        "job_store",
    ],
)
def test_context_rejects_invalid_components(
    components: dict[str, object],
    component_name: str,
) -> None:
    supplied = dict(components)
    supplied[component_name] = object()

    with pytest.raises(SchedulingIntegrationContextError):
        SchedulingIntegrationContext.create(
            scheduler_manager=supplied["scheduler_manager"],
            task_registry=supplied["task_registry"],
            job_store=supplied["job_store"],
        )


def test_context_rejects_invalid_scheduler(
    components: dict[str, object],
) -> None:
    class ManagerWithoutScheduler:
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

    with pytest.raises(SchedulingIntegrationContextError):
        SchedulingIntegrationContext.create(
            scheduler_manager=ManagerWithoutScheduler(),
            task_registry=components["task_registry"],
            job_store=components["job_store"],
        )


def test_context_supports_custom_method_aliases() -> None:
    scheduler = FakeScheduler()

    class LegacyRegistry:
        def add_task(self) -> None:
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

    context = SchedulingIntegrationContext.create(
        scheduler_manager=FakeSchedulerManager(scheduler),
        task_registry=LegacyRegistry(),
        job_store=FakeJobStore(),
        registry_method_aliases={"register": "add_task"},
    )

    assert context.task_registry.register() is None


def test_context_supports_manager_attribute_aliases() -> None:
    scheduler = FakeScheduler()

    class LegacyManager:
        engine = scheduler

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

    context = SchedulingIntegrationContext.create(
        scheduler_manager=LegacyManager(),
        task_registry=FakeTaskRegistry(),
        job_store=FakeJobStore(),
        manager_attribute_aliases={"scheduler": "engine"},
    )

    assert context.scheduler.component is scheduler


def test_context_creation_does_not_start_scheduler(
    components: dict[str, object],
) -> None:
    context = create_context(components)

    assert context.is_validated is True


def test_context_revalidates_components(
    components: dict[str, object],
) -> None:
    context = create_context(components)

    report = context.revalidate()

    assert report.valid is True
    assert report.components_checked == 4


def test_revalidation_detects_removed_method(
    components: dict[str, object],
) -> None:
    context = create_context(components)

    components["scheduler"].add_job = None  # type: ignore[method-assign]

    with pytest.raises(SchedulingIntegrationContextError):
        context.revalidate()


def test_custom_validator_can_be_supplied(
    components: dict[str, object],
) -> None:
    validator = SchedulingIntegrationValidator()

    context = create_context(
        components,
        validator=validator,
    )

    assert context.is_validated is True


def test_invalid_validator_type_is_rejected(
    components: dict[str, object],
) -> None:
    with pytest.raises(TypeError):
        create_context(
            components,
            validator=object(),
        )


def test_revalidate_rejects_invalid_validator_type(
    components: dict[str, object],
) -> None:
    context = create_context(components)

    with pytest.raises(TypeError):
        context.revalidate(object())  # type: ignore[arg-type]


def test_validation_error_is_wrapped(
    components: dict[str, object],
) -> None:
    class FailingValidator(SchedulingIntegrationValidator):
        def validate_or_raise(self, components):
            raise SchedulingIntegrationError("test validation failure")

    with pytest.raises(
        SchedulingIntegrationContextError
    ) as error:
        create_context(
            components,
            validator=FailingValidator(),
        )

    assert isinstance(error.value.__cause__, SchedulingIntegrationError)


def test_unexpected_validator_error_is_not_wrapped(
    components: dict[str, object],
) -> None:
    class BrokenValidator(SchedulingIntegrationValidator):
        def validate_or_raise(self, components):
            raise ValueError("unexpected validator failure")

    with pytest.raises(ValueError, match="unexpected validator failure"):
        create_context(
            components,
            validator=BrokenValidator(),
        )
