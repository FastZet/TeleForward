"""Configuration models for TeleForward scheduled tasks."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping


class TaskTriggerType(StrEnum):
    """Supported scheduled task trigger types."""

    INTERVAL = "interval"
    CRON = "cron"
    DATE = "date"


@dataclass(frozen=True, slots=True)
class ScheduledTaskConfig:
    """Configuration for registering and executing a scheduled task."""

    task_name: str
    trigger_type: TaskTriggerType
    trigger_config: Mapping[str, Any] = field(default_factory=dict)

    enabled: bool = True

    max_instances: int = 1
    coalesce: bool = True
    misfire_grace_time: int | None = 60

    timeout_seconds: float | None = 300.0

    def __post_init__(self) -> None:
        """Validate and normalise task configuration."""

        if not isinstance(self.task_name, str):
            raise TypeError("task_name must be a string")

        normalised_name = self.task_name.strip().lower()

        if not normalised_name:
            raise ValueError("task_name cannot be empty")

        object.__setattr__(self, "task_name", normalised_name)

        try:
            trigger_type = TaskTriggerType(self.trigger_type)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Unsupported trigger type: {self.trigger_type!r}"
            ) from exc

        object.__setattr__(self, "trigger_type", trigger_type)

        if not isinstance(self.trigger_config, Mapping):
            raise TypeError("trigger_config must be a mapping")

        if not isinstance(self.enabled, bool):
            raise TypeError("enabled must be a boolean")

        if (
            isinstance(self.max_instances, bool)
            or not isinstance(self.max_instances, int)
            or self.max_instances < 1
        ):
            raise ValueError(
                "max_instances must be a positive integer"
            )

        if not isinstance(self.coalesce, bool):
            raise TypeError("coalesce must be a boolean")

        if self.misfire_grace_time is not None:
            if (
                isinstance(self.misfire_grace_time, bool)
                or not isinstance(self.misfire_grace_time, int)
                or self.misfire_grace_time < 1
            ):
                raise ValueError(
                    "misfire_grace_time must be a positive integer or None"
                )

        if self.timeout_seconds is not None:
            if (
                isinstance(self.timeout_seconds, bool)
                or not isinstance(
                    self.timeout_seconds,
                    (int, float),
                )
                or self.timeout_seconds <= 0
            ):
                raise ValueError(
                    "timeout_seconds must be positive or None"
                )

            object.__setattr__(
                self,
                "timeout_seconds",
                float(self.timeout_seconds),
            )

        config_copy = dict(self.trigger_config)

        if any(not isinstance(key, str) for key in config_copy):
            raise ValueError(
                "trigger_config keys must be strings"
            )

        object.__setattr__(self, "trigger_config", config_copy)

    def to_dict(self) -> dict[str, Any]:
        """Return a serialisable representation of the configuration."""

        return {
            "task_name": self.task_name,
            "trigger_type": self.trigger_type.value,
            "trigger_config": dict(self.trigger_config),
            "enabled": self.enabled,
            "max_instances": self.max_instances,
            "coalesce": self.coalesce,
            "misfire_grace_time": self.misfire_grace_time,
            "timeout_seconds": self.timeout_seconds,
        }

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, Any],
    ) -> ScheduledTaskConfig:
        """Construct configuration from a mapping."""

        if not isinstance(data, Mapping):
            raise TypeError("data must be a mapping")

        allowed_fields = {
            "task_name",
            "trigger_type",
            "trigger_config",
            "enabled",
            "max_instances",
            "coalesce",
            "misfire_grace_time",
            "timeout_seconds",
        }

        unknown_fields = set(data) - allowed_fields

        if unknown_fields:
            raise ValueError(
                "Unknown task configuration fields: "
                + ", ".join(sorted(str(item) for item in unknown_fields))
            )

        return cls(**dict(data))
