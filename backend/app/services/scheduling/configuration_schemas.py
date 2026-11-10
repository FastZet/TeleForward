"""Pydantic schemas for scheduling configuration APIs."""

from __future__ import annotations

from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.services.scheduling.configuration import (
    ScheduledTaskConfigurationSet,
)
from app.services.scheduling.task_config import (
    ScheduledTaskConfig,
    TaskTriggerType,
)


class ScheduledTaskConfigSchema(BaseModel):
    """Validated representation of a scheduled task configuration."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
    )

    task_name: str = Field(
        min_length=1,
        max_length=128,
    )
    trigger_type: TaskTriggerType
    trigger_config: dict[str, Any] = Field(
        default_factory=dict,
    )
    enabled: bool = True
    max_instances: int = Field(
        default=1,
        ge=1,
        le=100,
    )
    coalesce: bool = True
    misfire_grace_time: int | None = Field(
        default=60,
        ge=1,
    )
    timeout_seconds: float | None = Field(
        default=None,
        gt=0,
        le=86400,
    )

    @field_validator("task_name")
    @classmethod
    def validate_task_name(cls, value: str) -> str:
        if not value:
            raise ValueError("task_name must not be empty")

        if any(character.isspace() for character in value):
            raise ValueError(
                "task_name must not contain whitespace"
            )

        return value

    @field_validator("trigger_config")
    @classmethod
    def validate_trigger_config(
        cls,
        value: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError("trigger_config must be an object")

        return value

    def to_domain(self) -> ScheduledTaskConfig:
        """Convert this schema into the scheduling domain model."""

        return ScheduledTaskConfig.from_dict(
            self.model_dump(mode="python")
        )

    @classmethod
    def from_domain(
        cls,
        configuration: ScheduledTaskConfig,
    ) -> ScheduledTaskConfigSchema:
        """Create a schema from a domain configuration."""

        return cls.model_validate(configuration.to_dict())


class ConfigurationReplaceRequest(BaseModel):
    """Request to replace the active task configuration."""

    model_config = ConfigDict(extra="forbid")

    tasks: list[ScheduledTaskConfigSchema] = Field(
        min_length=1,
        max_length=500,
    )

    @model_validator(mode="after")
    def validate_unique_task_names(
        self,
    ) -> ConfigurationReplaceRequest:
        names = [task.task_name for task in self.tasks]

        if len(names) != len(set(names)):
            raise ValueError(
                "Configuration contains duplicate task names"
            )

        return self

    def to_domain(self) -> ScheduledTaskConfigurationSet:
        """Convert the request into a domain configuration set."""

        return ScheduledTaskConfigurationSet.from_iterable(
            task.to_domain()
            for task in self.tasks
        )


class ConfigurationTaskUpdateRequest(BaseModel):
    """Request to update an existing task configuration."""

    model_config = ConfigDict(extra="forbid")

    trigger_type: TaskTriggerType | None = None
    trigger_config: dict[str, Any] | None = None
    enabled: bool | None = None
    max_instances: int | None = Field(
        default=None,
        ge=1,
        le=100,
    )
    coalesce: bool | None = None
    misfire_grace_time: int | None = Field(
        default=None,
        ge=1,
    )
    timeout_seconds: float | None = Field(
        default=None,
        gt=0,
        le=86400,
    )

    @model_validator(mode="after")
    def require_at_least_one_update(
        self,
    ) -> ConfigurationTaskUpdateRequest:
        if not self.model_fields_set:
            raise ValueError(
                "At least one configuration field must be supplied"
            )

        return self

    def changes(self) -> dict[str, Any]:
        """Return only fields explicitly supplied by the caller."""

        return self.model_dump(
            exclude_unset=True,
            mode="python",
        )


class ConfigurationTaskResponseSchema(BaseModel):
    """Public response representation of a task configuration."""

    model_config = ConfigDict(extra="forbid")

    task_name: str
    trigger_type: TaskTriggerType
    trigger_config: dict[str, Any]
    enabled: bool
    max_instances: int
    coalesce: bool
    misfire_grace_time: int | None
    timeout_seconds: float | None

    @classmethod
    def from_domain(
        cls,
        configuration: ScheduledTaskConfig,
    ) -> ConfigurationTaskResponseSchema:
        return cls.model_validate(configuration.to_dict())


class ConfigurationResponseSchema(BaseModel):
    """Public response representation of the complete configuration."""

    model_config = ConfigDict(extra="forbid")

    total_tasks: int
    enabled_tasks: int
    disabled_tasks: int
    tasks: list[ConfigurationTaskResponseSchema]

    @classmethod
    def from_domain(
        cls,
        configuration: ScheduledTaskConfigurationSet,
    ) -> ConfigurationResponseSchema:
        tasks = configuration.to_list()

        return cls(
            total_tasks=len(tasks),
            enabled_tasks=sum(
                task.enabled for task in tasks
            ),
            disabled_tasks=sum(
                not task.enabled for task in tasks
            ),
            tasks=[
                ConfigurationTaskResponseSchema.from_domain(task)
                for task in tasks
            ],
        )


class ConfigurationValidationErrorSchema(BaseModel):
    """Structured configuration validation error."""

    model_config = ConfigDict(extra="forbid")

    field: str
    message: str
    error_type: str


class ConfigurationValidationResponseSchema(BaseModel):
    """Result of validating a configuration request."""

    model_config = ConfigDict(extra="forbid")

    valid: bool
    errors: list[ConfigurationValidationErrorSchema] = Field(
        default_factory=list,
    )
    warnings: list[str] = Field(
        default_factory=list,
    )
