"""Tests for scheduling configuration API schemas."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.services.scheduling.configuration_schemas import (
    ConfigurationReplaceRequest,
    ConfigurationResponseSchema,
    ConfigurationTaskUpdateRequest,
    ConfigurationValidationErrorSchema,
    ConfigurationValidationResponseSchema,
    ScheduledTaskConfigSchema,
)
from app.services.scheduling.task_config import TaskTriggerType


def valid_task_payload(
    *,
    task_name: str = "telegram_sync",
    enabled: bool = True,
) -> dict:
    """Return a valid interval-triggered task payload."""

    return {
        "task_name": task_name,
        "trigger_type": TaskTriggerType.INTERVAL,
        "trigger_config": {"seconds": 60},
        "enabled": enabled,
        "max_instances": 1,
        "coalesce": True,
        "misfire_grace_time": 60,
        "timeout_seconds": 30.0,
    }


class TestScheduledTaskConfigSchema:
    def test_valid_task_configuration(self) -> None:
        schema = ScheduledTaskConfigSchema.model_validate(
            valid_task_payload()
        )

        assert schema.task_name == "telegram_sync"
        assert schema.trigger_type == TaskTriggerType.INTERVAL
        assert schema.trigger_config == {"seconds": 60}
        assert schema.enabled is True

    def test_task_name_cannot_be_empty(self) -> None:
        payload = valid_task_payload(task_name="")

        with pytest.raises(ValidationError):
            ScheduledTaskConfigSchema.model_validate(payload)

    def test_task_name_cannot_contain_whitespace(self) -> None:
        payload = valid_task_payload(
            task_name="telegram sync"
        )

        with pytest.raises(ValidationError):
            ScheduledTaskConfigSchema.model_validate(payload)

    def test_unknown_fields_are_rejected(self) -> None:
        payload = valid_task_payload()
        payload["unexpected_field"] = True

        with pytest.raises(ValidationError):
            ScheduledTaskConfigSchema.model_validate(payload)

    def test_max_instances_must_be_positive(self) -> None:
        payload = valid_task_payload()
        payload["max_instances"] = 0

        with pytest.raises(ValidationError):
            ScheduledTaskConfigSchema.model_validate(payload)

    def test_timeout_must_be_positive(self) -> None:
        payload = valid_task_payload()
        payload["timeout_seconds"] = 0

        with pytest.raises(ValidationError):
            ScheduledTaskConfigSchema.model_validate(payload)

    def test_to_domain_conversion(self) -> None:
        schema = ScheduledTaskConfigSchema.model_validate(
            valid_task_payload()
        )

        domain = schema.to_domain()

        assert domain.task_name == schema.task_name
        assert domain.trigger_type == schema.trigger_type
        assert domain.enabled == schema.enabled


class TestConfigurationReplaceRequest:
    def test_valid_configuration_replacement(self) -> None:
        request = ConfigurationReplaceRequest(
            tasks=[
                valid_task_payload(task_name="telegram_sync"),
                valid_task_payload(
                    task_name="session_maintenance"
                ),
            ]
        )

        assert len(request.tasks) == 2

        domain = request.to_domain()

        assert len(domain.to_list()) == 2

    def test_duplicate_task_names_are_rejected(self) -> None:
        payload = valid_task_payload()

        with pytest.raises(ValidationError):
            ConfigurationReplaceRequest(
                tasks=[
                    payload,
                    payload,
                ]
            )

    def test_empty_task_list_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ConfigurationReplaceRequest(tasks=[])

    def test_configuration_size_limit_is_enforced(self) -> None:
        tasks = [
            valid_task_payload(
                task_name=f"task_{index}"
            )
            for index in range(501)
        ]

        with pytest.raises(ValidationError):
            ConfigurationReplaceRequest(tasks=tasks)


class TestConfigurationTaskUpdateRequest:
    def test_partial_update_is_supported(self) -> None:
        request = ConfigurationTaskUpdateRequest(
            enabled=False
        )

        assert request.changes() == {"enabled": False}

    def test_explicit_false_is_preserved(self) -> None:
        request = ConfigurationTaskUpdateRequest(
            enabled=False,
            coalesce=False,
        )

        changes = request.changes()

        assert changes["enabled"] is False
        assert changes["coalesce"] is False

    def test_empty_update_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ConfigurationTaskUpdateRequest()

    def test_invalid_max_instances_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ConfigurationTaskUpdateRequest(
                max_instances=0
            )

    def test_unknown_update_fields_are_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ConfigurationTaskUpdateRequest.model_validate(
                {"unknown": "value"}
            )


class TestConfigurationResponseSchema:
    def test_response_conversion(self) -> None:
        request = ConfigurationReplaceRequest(
            tasks=[
                valid_task_payload(
                    task_name="telegram_sync",
                    enabled=True,
                ),
                valid_task_payload(
                    task_name="session_maintenance",
                    enabled=False,
                ),
            ]
        )

        domain = request.to_domain()
        response = ConfigurationResponseSchema.from_domain(
            domain
        )

        assert response.total_tasks == 2
        assert response.enabled_tasks == 1
        assert response.disabled_tasks == 1
        assert len(response.tasks) == 2


class TestConfigurationValidationSchemas:
    def test_validation_error_schema(self) -> None:
        error = ConfigurationValidationErrorSchema(
            field="task_name",
            message="Task name is required",
            error_type="value_error",
        )

        assert error.field == "task_name"
        assert error.error_type == "value_error"

    def test_valid_validation_response(self) -> None:
        response = ConfigurationValidationResponseSchema(
            valid=True
        )

        assert response.valid is True
        assert response.errors == []
        assert response.warnings == []

    def test_invalid_validation_response(self) -> None:
        response = ConfigurationValidationResponseSchema(
            valid=False,
            errors=[
                ConfigurationValidationErrorSchema(
                    field="trigger_config",
                    message="Invalid interval",
                    error_type="value_error",
                )
            ],
        )

        assert response.valid is False
        assert len(response.errors) == 1
