
"""Tests for scheduling component adapters."""

from __future__ import annotations

import pytest

from app.services.scheduling.component_adapters import (
    ComponentAdapter,
    ComponentAdapterError,
    JobStoreAdapter,
    SchedulerEngineAdapter,
    SchedulerManagerAdapter,
    TaskRegistryAdapter,
    adapt_component,
)
from app.services.scheduling.integration_contracts import (
    InterfaceContract,
)


class FakeSchedulerManager:
    def create_job(self, job_id: str) -> str:
        return f"created:{job_id}"

    def update_job(self, job_id: str) -> str:
        return f"updated:{job_id}"

    def delete_job(self, job_id: str) -> str:
        return f"deleted:{job_id}"

    def enable_job(self, job_id: str) -> str:
        return f"enabled:{job_id}"

    def disable_job(self, job_id: str) -> str:
        return f"disabled:{job_id}"

    def list_jobs(self) -> list[str]:
        return ["job-1"]

    def restore_jobs(self) -> int:
        return 1

    def start(self) -> str:
        return "started"

    def shutdown(self) -> str:
        return "stopped"

    scheduler = "fake-scheduler"


class FakeTaskRegistry:
    def register(self) -> str:
        return "registered"

    def get(self) -> str:
        return "task"

    def get_optional(self) -> str | None:
        return None

    def unregister(self) -> str:
        return "unregistered"

    def contains(self) -> bool:
        return True

    def names(self) -> tuple[str, ...]:
        return ("task",)

    def get_all(self) -> tuple[str, ...]:
        return ("task",)


class FakeJobStore:
    def add(self) -> str:
        return "added"

    def get(self) -> str:
        return "job"

    def list_all(self) -> list[str]:
        return ["job"]

    def update(self) -> str:
        return "updated"

    def delete(self) -> str:
        return "deleted"

    def close(self) -> str:
        return "closed"


class FakeScheduler:
    def add_job(self) -> str:
        return "added"

    def get_job(self) -> str:
        return "job"

    def get_jobs(self) -> list[str]:
        return ["job"]

    def remove_job(self) -> str:
        return "removed"

    def start(self) -> str:
        return "started"

    def shutdown(self) -> str:
        return "stopped"

    def pause(self) -> str:
        return "paused"

    def resume(self) -> str:
        return "resumed"


def test_scheduler_manager_adapter_delegates_methods() -> None:
    manager = FakeSchedulerManager()
    adapter = SchedulerManagerAdapter(manager)

    assert adapter.create_job("job-1") == "created:job-1"
    assert adapter.update_job("job-1") == "updated:job-1"
    assert adapter.delete_job("job-1") == "deleted:job-1"
    assert adapter.enable_job("job-1") == "enabled:job-1"
    assert adapter.disable_job("job-1") == "disabled:job-1"
    assert adapter.list_jobs() == ["job-1"]
    assert adapter.restore_jobs() == 1
    assert adapter.start() == "started"
    assert adapter.shutdown() == "stopped"


def test_scheduler_manager_adapter_exposes_scheduler() -> None:
    adapter = SchedulerManagerAdapter(FakeSchedulerManager())

    assert adapter.scheduler == "fake-scheduler"


def test_task_registry_adapter_delegates_methods() -> None:
    adapter = TaskRegistryAdapter(FakeTaskRegistry())

    assert adapter.register() == "registered"
    assert adapter.get() == "task"
    assert adapter.get_optional() is None
    assert adapter.unregister() == "unregistered"
    assert adapter.contains() is True
    assert adapter.names() == ("task",)
    assert adapter.get_all() == ("task",)


def test_job_store_adapter_delegates_methods() -> None:
    adapter = JobStoreAdapter(FakeJobStore())

    assert adapter.add() == "added"
    assert adapter.get() == "job"
    assert adapter.list_all() == ["job"]
    assert adapter.update() == "updated"
    assert adapter.delete() == "deleted"
    assert adapter.close() == "closed"


def test_scheduler_engine_adapter_delegates_methods() -> None:
    adapter = SchedulerEngineAdapter(FakeScheduler())

    assert adapter.add_job() == "added"
    assert adapter.get_job() == "job"
    assert adapter.get_jobs() == ["job"]
    assert adapter.remove_job() == "removed"
    assert adapter.start() == "started"
    assert adapter.shutdown() == "stopped"
    assert adapter.pause() == "paused"
    assert adapter.resume() == "resumed"


def test_method_aliases_are_supported() -> None:
    class LegacyRegistry:
        def add_task(self) -> str:
            return "added"

        def get_task(self) -> str:
            return "retrieved"

        def get_optional_task(self) -> None:
            return None

        def remove_task(self) -> str:
            return "removed"

        def has_task(self) -> bool:
            return True

        def list_names(self) -> tuple[str, ...]:
            return ("task",)

        def list_all_tasks(self) -> tuple[str, ...]:
            return ("task",)

    adapter = TaskRegistryAdapter(
        LegacyRegistry(),
        method_aliases={
            "register": "add_task",
            "get": "get_task",
            "get_optional": "get_optional_task",
            "unregister": "remove_task",
            "contains": "has_task",
            "names": "list_names",
            "get_all": "list_all_tasks",
        },
    )

    assert adapter.register() == "added"
    assert adapter.get() == "retrieved"
    assert adapter.unregister() == "removed"
    assert adapter.contains() is True


def test_attribute_aliases_are_supported() -> None:
    class LegacyManager(FakeSchedulerManager):
        scheduler = None
        engine = "legacy-engine"

    adapter = SchedulerManagerAdapter(
        LegacyManager(),
        attribute_aliases={"scheduler": "engine"},
    )

    assert adapter.scheduler == "legacy-engine"


def test_component_property_returns_underlying_instance() -> None:
    manager = FakeSchedulerManager()
    adapter = SchedulerManagerAdapter(manager)

    assert adapter.component is manager


def test_contract_property_returns_contract() -> None:
    adapter = SchedulerManagerAdapter(FakeSchedulerManager())

    assert isinstance(adapter.contract, InterfaceContract)
    assert adapter.contract.name == "scheduler_manager"


def test_missing_required_method_is_rejected() -> None:
    class IncompleteRegistry:
        pass

    with pytest.raises(ComponentAdapterError) as error:
        TaskRegistryAdapter(IncompleteRegistry())

    assert "missing methods" in str(error.value)


def test_missing_required_attribute_is_rejected() -> None:
    class IncompleteManager:
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

        def list_jobs(self) -> None:
            pass

        def restore_jobs(self) -> None:
            pass

        def start(self) -> None:
            pass

        def shutdown(self) -> None:
            pass

    with pytest.raises(ComponentAdapterError) as error:
        SchedulerManagerAdapter(IncompleteManager())

    assert "missing attributes" in str(error.value)


def test_non_callable_method_is_rejected() -> None:
    class InvalidRegistry(FakeTaskRegistry):
        register = "not-callable"

    with pytest.raises(ComponentAdapterError):
        TaskRegistryAdapter(InvalidRegistry())


def test_none_component_is_rejected() -> None:
    with pytest.raises(TypeError):
        ComponentAdapter(
            None,
            InterfaceContract("test", ("execute",)),
        )


def test_invalid_contract_is_rejected() -> None:
    with pytest.raises(TypeError):
        ComponentAdapter(
            object(),
            object(),  # type: ignore[arg-type]
        )


def test_unknown_canonical_method_alias_is_rejected() -> None:
    with pytest.raises(ComponentAdapterError):
        TaskRegistryAdapter(
            FakeTaskRegistry(),
            method_aliases={"unknown": "register"},
        )


def test_empty_underlying_method_alias_is_rejected() -> None:
    with pytest.raises(ValueError):
        TaskRegistryAdapter(
            FakeTaskRegistry(),
            method_aliases={"register": " "},
        )


def test_unknown_attribute_alias_is_rejected() -> None:
    with pytest.raises(ComponentAdapterError):
        SchedulerManagerAdapter(
            FakeSchedulerManager(),
            attribute_aliases={"unknown": "scheduler"},
        )


def test_unexposed_attribute_raises_attribute_error() -> None:
    adapter = TaskRegistryAdapter(FakeTaskRegistry())

    with pytest.raises(AttributeError):
        _ = adapter.internal_state


def test_adapt_component_creates_correct_adapter() -> None:
    cases = (
        ("scheduler_manager", FakeSchedulerManager, SchedulerManagerAdapter),
        ("task_registry", FakeTaskRegistry, TaskRegistryAdapter),
        ("job_store", FakeJobStore, JobStoreAdapter),
        ("scheduler", FakeScheduler, SchedulerEngineAdapter),
    )

    for name, factory, expected_type in cases:
        adapter = adapt_component(name, factory())
        assert isinstance(adapter, expected_type)


def test_adapt_component_supports_method_aliases() -> None:
    class LegacyRegistry(FakeTaskRegistry):
        def add_task(self) -> str:
            return "added"

    adapter = adapt_component(
        "task_registry",
        LegacyRegistry(),
        method_aliases={"register": "add_task"},
    )

    assert adapter.register() == "added"


def test_adapt_component_supports_manager_attribute_aliases() -> None:
    class LegacyManager(FakeSchedulerManager):
        engine = "legacy-engine"

    adapter = adapt_component(
        "scheduler_manager",
        LegacyManager(),
        attribute_aliases={"scheduler": "engine"},
    )

    assert adapter.scheduler == "legacy-engine"


def test_adapt_component_rejects_attribute_aliases_for_other_components() -> None:
    with pytest.raises(ValueError):
        adapt_component(
            "task_registry",
            FakeTaskRegistry(),
            attribute_aliases={"registry": "tasks"},
        )


def test_adapt_component_rejects_unknown_component() -> None:
    with pytest.raises(ValueError):
        adapt_component("unknown", object())


def test_adapter_does_not_transform_return_values() -> None:
    manager = FakeSchedulerManager()
    adapter = SchedulerManagerAdapter(manager)

    result = adapter.list_jobs()

    assert result == ["job-1"]
