
"""Tests for scheduling subsystem integration validation."""

from __future__ import annotations

import pytest

from app.services.scheduling.integration_validator import (
    ComponentRequirement,
    IntegrationValidationReport,
    SchedulingIntegrationError,
    SchedulingIntegrationValidator,
)


class FakeSchedulerManager:
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

    scheduler = object()


class FakeTaskRegistry:
    def register(self) -> None:
        pass

    def get(self) -> None:
        pass

    def get_optional(self) -> None:
        pass

    def unregister(self) -> None:
        pass

    def contains(self) -> None:
        pass

    def names(self) -> None:
        pass

    def get_all(self) -> None:
        pass


class FakeJobStore:
    def add(self) -> None:
        pass

    def get(self) -> None:
        pass

    def list_all(self) -> None:
        pass

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

    def get_jobs(self) -> None:
        pass

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
def validator() -> SchedulingIntegrationValidator:
    return SchedulingIntegrationValidator()


@pytest.fixture
def valid_components() -> dict[str, object]:
    return {
        "scheduler_manager": FakeSchedulerManager(),
        "task_registry": FakeTaskRegistry(),
        "job_store": FakeJobStore(),
        "scheduler": FakeScheduler(),
    }


def test_default_requirements_validate_successfully(
    validator: SchedulingIntegrationValidator,
    valid_components: dict[str, object],
) -> None:
    report = validator.validate(valid_components)

    assert isinstance(report, IntegrationValidationReport)
    assert report.valid is True
    assert report.components_checked == 4
    assert report.components_valid == 4
    assert report.components_invalid == 0
    assert report.errors == ()


def test_validate_or_raise_returns_valid_report(
    validator: SchedulingIntegrationValidator,
    valid_components: dict[str, object],
) -> None:
    report = validator.validate_or_raise(valid_components)

    assert report.valid is True


def test_missing_components_are_reported(
    validator: SchedulingIntegrationValidator,
) -> None:
    report = validator.validate({})

    assert report.valid is False
    assert report.components_invalid == 4
    assert len(report.errors) == 4


def test_missing_component_reports_required_interface(
    validator: SchedulingIntegrationValidator,
) -> None:
    report = validator.validate({})

    manager_result = next(
        result
        for result in report.results
        if result.component == "scheduler_manager"
    )

    assert "create_job" in manager_result.missing_methods
    assert "scheduler" in manager_result.missing_attributes


def test_incomplete_component_reports_missing_methods(
    validator: SchedulingIntegrationValidator,
) -> None:
    class IncompleteRegistry:
        def register(self) -> None:
            pass

        def get(self) -> None:
            pass

    report = validator.validate(
        {"task_registry": IncompleteRegistry()}
    )

    result = next(
        item
        for item in report.results
        if item.component == "task_registry"
    )

    assert result.valid is False
    assert "unregister" in result.missing_methods
    assert "names" in result.missing_methods


def test_non_callable_method_is_reported_as_missing(
    validator: SchedulingIntegrationValidator,
) -> None:
    class InvalidRegistry:
        register = "not callable"

    report = validator.validate(
        {"task_registry": InvalidRegistry()}
    )

    result = next(
        item
        for item in report.results
        if item.component == "task_registry"
    )

    assert "register" in result.missing_methods


def test_missing_attribute_is_reported(
    validator: SchedulingIntegrationValidator,
) -> None:
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

    report = validator.validate(
        {"scheduler_manager": IncompleteManager()}
    )

    result = next(
        item
        for item in report.results
        if item.component == "scheduler_manager"
    )

    assert result.valid is False
    assert result.missing_attributes == ("scheduler",)


def test_validate_or_raise_rejects_invalid_components(
    validator: SchedulingIntegrationValidator,
) -> None:
    with pytest.raises(SchedulingIntegrationError) as error:
        validator.validate_or_raise({})

    assert "integration validation failed" in str(error.value).lower()


def test_custom_requirements_are_supported() -> None:
    custom_validator = SchedulingIntegrationValidator(
        requirements=(
            ComponentRequirement(
                component="custom_worker",
                methods=("execute", "stop"),
                attributes=("worker_id",),
            ),
        )
    )

    class Worker:
        worker_id = "worker-1"

        def execute(self) -> None:
            pass

        def stop(self) -> None:
            pass

    report = custom_validator.validate(
        {"custom_worker": Worker()}
    )

    assert report.valid is True
    assert report.components_checked == 1


def test_custom_requirements_report_missing_interfaces() -> None:
    custom_validator = SchedulingIntegrationValidator(
        requirements=(
            ComponentRequirement(
                component="custom_worker",
                methods=("execute",),
                attributes=("worker_id",),
            ),
        )
    )

    report = custom_validator.validate(
        {"custom_worker": object()}
    )

    assert report.valid is False
    assert report.errors == (
        "custom_worker: missing methods: execute",
        "custom_worker: missing attributes: worker_id",
    )


def test_empty_requirements_are_rejected() -> None:
    with pytest.raises(ValueError):
        SchedulingIntegrationValidator(requirements=())


def test_duplicate_component_names_are_rejected() -> None:
    requirements = (
        ComponentRequirement("worker", methods=("execute",)),
        ComponentRequirement("worker", methods=("stop",)),
    )

    with pytest.raises(ValueError):
        SchedulingIntegrationValidator(requirements=requirements)


def test_duplicate_method_requirements_are_rejected() -> None:
    with pytest.raises(ValueError):
        SchedulingIntegrationValidator(
            requirements=(
                ComponentRequirement(
                    "worker",
                    methods=("execute", "execute"),
                ),
            )
        )


def test_duplicate_attribute_requirements_are_rejected() -> None:
    with pytest.raises(ValueError):
        SchedulingIntegrationValidator(
            requirements=(
                ComponentRequirement(
                    "worker",
                    methods=(),
                    attributes=("worker_id", "worker_id"),
                ),
            )
        )


def test_empty_component_name_is_rejected() -> None:
    with pytest.raises(ValueError):
        SchedulingIntegrationValidator(
            requirements=(
                ComponentRequirement(
                    " ",
                    methods=("execute",),
                ),
            )
        )


@pytest.mark.parametrize(
    "invalid_components",
    [
        None,
        [],
        "invalid",
        object(),
    ],
)
def test_validate_rejects_non_dictionary_components(
    validator: SchedulingIntegrationValidator,
    invalid_components: object,
) -> None:
    with pytest.raises(TypeError):
        validator.validate(invalid_components)  # type: ignore[arg-type]


def test_report_counts_are_consistent(
    validator: SchedulingIntegrationValidator,
    valid_components: dict[str, object],
) -> None:
    del valid_components["job_store"]

    report = validator.validate(valid_components)

    assert report.components_checked == (
        report.components_valid + report.components_invalid
    )
    assert report.components_invalid == 1
    assert report.valid is False
