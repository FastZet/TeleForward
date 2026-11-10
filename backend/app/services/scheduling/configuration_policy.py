"""Policy enforcement for scheduled-task configurations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from app.services.scheduling.configuration import (
    ScheduledTaskConfigurationSet,
)
from app.services.scheduling.task_config import (
    ScheduledTaskConfig,
    TaskTriggerType,
)


@dataclass(frozen=True, slots=True)
class ConfigurationPolicy:
    """Define constraints for accepted scheduling configurations."""

    max_tasks: int = 100
    max_enabled_tasks: int = 50
    allowed_task_names: frozenset[str] | None = None
    denied_task_names: frozenset[str] = field(
        default_factory=frozenset
    )
    allowed_trigger_types: frozenset[TaskTriggerType] = field(
        default_factory=lambda: frozenset(TaskTriggerType)
    )
    minimum_interval_seconds: int = 10
    maximum_interval_seconds: int = 31_536_000
    allow_date_triggers: bool = True
    require_at_least_one_enabled_task: bool = False

    def __post_init__(self) -> None:
        if (
            isinstance(self.max_tasks, bool)
            or not isinstance(self.max_tasks, int)
            or self.max_tasks < 1
        ):
            raise ValueError("max_tasks must be a positive integer")

        if (
            isinstance(self.max_enabled_tasks, bool)
            or not isinstance(self.max_enabled_tasks, int)
            or self.max_enabled_tasks < 0
        ):
            raise ValueError(
                "max_enabled_tasks must be a non-negative integer"
            )

        if (
            isinstance(self.minimum_interval_seconds, bool)
            or not isinstance(self.minimum_interval_seconds, int)
            or self.minimum_interval_seconds < 1
        ):
            raise ValueError(
                "minimum_interval_seconds must be positive"
            )

        if (
            isinstance(self.maximum_interval_seconds, bool)
            or not isinstance(self.maximum_interval_seconds, int)
            or self.maximum_interval_seconds
            < self.minimum_interval_seconds
        ):
            raise ValueError(
                "maximum_interval_seconds must be at least "
                "minimum_interval_seconds"
            )

        if not isinstance(self.allow_date_triggers, bool):
            raise TypeError("allow_date_triggers must be a boolean")

        if not isinstance(
            self.require_at_least_one_enabled_task,
            bool,
        ):
            raise TypeError(
                "require_at_least_one_enabled_task must be a boolean"
            )

        if self.allowed_task_names is not None:
            if not isinstance(self.allowed_task_names, frozenset):
                raise TypeError(
                    "allowed_task_names must be a frozenset or None"
                )

            if any(
                not isinstance(name, str) or not name.strip()
                for name in self.allowed_task_names
            ):
                raise ValueError(
                    "allowed_task_names contains an invalid name"
                )

        if not isinstance(self.denied_task_names, frozenset):
            raise TypeError("denied_task_names must be a frozenset")

        if any(
            not isinstance(name, str) or not name.strip()
            for name in self.denied_task_names
        ):
            raise ValueError(
                "denied_task_names contains an invalid name"
            )

        if not isinstance(self.allowed_trigger_types, frozenset):
            raise TypeError(
                "allowed_trigger_types must be a frozenset"
            )

        if any(
            not isinstance(trigger, TaskTriggerType)
            for trigger in self.allowed_trigger_types
        ):
            raise TypeError(
                "allowed_trigger_types contains an invalid trigger type"
            )


@dataclass(frozen=True, slots=True)
class ConfigurationPolicyViolation:
    """Describe one policy violation."""

    code: str
    message: str
    task_name: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "code": self.code,
            "message": self.message,
            "task_name": self.task_name,
        }


@dataclass(frozen=True, slots=True)
class ConfigurationPolicyResult:
    """Result of evaluating a configuration against a policy."""

    accepted: bool
    total_tasks: int
    enabled_tasks: int
    violations: tuple[ConfigurationPolicyViolation, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "total_tasks": self.total_tasks,
            "enabled_tasks": self.enabled_tasks,
            "violations": [
                violation.to_dict()
                for violation in self.violations
            ],
        }


class ConfigurationPolicyService:
    """Evaluate configuration snapshots against scheduling policies."""

    def __init__(self, policy: ConfigurationPolicy) -> None:
        if not isinstance(policy, ConfigurationPolicy):
            raise TypeError("policy must be a ConfigurationPolicy")

        self._policy = policy

    @property
    def policy(self) -> ConfigurationPolicy:
        return self._policy

    def evaluate(
        self,
        configuration: ScheduledTaskConfigurationSet,
    ) -> ConfigurationPolicyResult:
        """Evaluate a configuration without modifying it."""

        if not isinstance(
            configuration,
            ScheduledTaskConfigurationSet,
        ):
            raise TypeError(
                "configuration must be a "
                "ScheduledTaskConfigurationSet"
            )

        tasks = configuration.to_list()
        enabled_tasks = sum(
            1 for task in tasks if task.enabled
        )

        violations: list[ConfigurationPolicyViolation] = []

        if len(tasks) > self._policy.max_tasks:
            violations.append(
                ConfigurationPolicyViolation(
                    code="maximum_tasks_exceeded",
                    message=(
                        f"Configuration contains {len(tasks)} tasks; "
                        f"maximum allowed is {self._policy.max_tasks}."
                    ),
                )
            )

        if enabled_tasks > self._policy.max_enabled_tasks:
            violations.append(
                ConfigurationPolicyViolation(
                    code="maximum_enabled_tasks_exceeded",
                    message=(
                        f"Configuration contains {enabled_tasks} enabled "
                        "tasks; maximum allowed is "
                        f"{self._policy.max_enabled_tasks}."
                    ),
                )
            )

        if (
            self._policy.require_at_least_one_enabled_task
            and enabled_tasks == 0
        ):
            violations.append(
                ConfigurationPolicyViolation(
                    code="no_enabled_tasks",
                    message="At least one enabled task is required.",
                )
            )

        for task in tasks:
            violations.extend(self._evaluate_task(task))

        return ConfigurationPolicyResult(
            accepted=not violations,
            total_tasks=len(tasks),
            enabled_tasks=enabled_tasks,
            violations=tuple(violations),
        )

    def enforce(
        self,
        configuration: ScheduledTaskConfigurationSet,
    ) -> ConfigurationPolicyResult:
        """Evaluate a configuration and reject policy violations."""

        result = self.evaluate(configuration)

        if not result.accepted:
            details = "; ".join(
                violation.message
                for violation in result.violations
            )

            raise ConfigurationPolicyError(
                f"Configuration rejected by policy: {details}",
                result=result,
            )

        return result

    def _evaluate_task(
        self,
        task: ScheduledTaskConfig,
    ) -> list[ConfigurationPolicyViolation]:
        violations: list[ConfigurationPolicyViolation] = []
        name = task.task_name

        if (
            self._policy.allowed_task_names is not None
            and name not in self._policy.allowed_task_names
        ):
            violations.append(
                ConfigurationPolicyViolation(
                    code="task_not_allowlisted",
                    message=f"Task '{name}' is not permitted.",
                    task_name=name,
                )
            )

        if name in self._policy.denied_task_names:
            violations.append(
                ConfigurationPolicyViolation(
                    code="task_denied",
                    message=f"Task '{name}' is explicitly denied.",
                    task_name=name,
                )
            )

        if task.trigger_type not in self._policy.allowed_trigger_types:
            violations.append(
                ConfigurationPolicyViolation(
                    code="trigger_type_not_allowed",
                    message=(
                        f"Trigger type '{task.trigger_type}' is not "
                        f"permitted for task '{name}'."
                    ),
                    task_name=name,
                )
            )

        if (
            task.trigger_type == TaskTriggerType.DATE
            and not self._policy.allow_date_triggers
        ):
            violations.append(
                ConfigurationPolicyViolation(
                    code="date_trigger_disabled",
                    message=(
                        f"Date triggers are disabled for task '{name}'."
                    ),
                    task_name=name,
                )
            )

        if task.trigger_type == TaskTriggerType.INTERVAL:
            violations.extend(
                self._evaluate_interval(task)
            )

        return violations

    def _evaluate_interval(
        self,
        task: ScheduledTaskConfig,
    ) -> list[ConfigurationPolicyViolation]:
        violations: list[ConfigurationPolicyViolation] = []
        interval = task.trigger_config.get("seconds")

        if interval is None:
            interval = self._interval_from_components(
                task.trigger_config
            )

        if interval is None:
            # Detailed trigger validation remains the responsibility
            # of ConfigurationValidator and TriggerFactory.
            return violations

        if (
            isinstance(interval, bool)
            or not isinstance(interval, (int, float))
        ):
            violations.append(
                ConfigurationPolicyViolation(
                    code="invalid_interval",
                    message=(
                        f"Task '{task.task_name}' has a non-numeric "
                        "interval."
                    ),
                    task_name=task.task_name,
                )
            )
            return violations

        if interval < self._policy.minimum_interval_seconds:
            violations.append(
                ConfigurationPolicyViolation(
                    code="interval_below_minimum",
                    message=(
                        f"Task '{task.task_name}' interval is shorter "
                        f"than {self._policy.minimum_interval_seconds} "
                        "seconds."
                    ),
                    task_name=task.task_name,
                )
            )

        if interval > self._policy.maximum_interval_seconds:
            violations.append(
                ConfigurationPolicyViolation(
                    code="interval_above_maximum",
                    message=(
                        f"Task '{task.task_name}' interval exceeds "
                        f"{self._policy.maximum_interval_seconds} "
                        "seconds."
                    ),
                    task_name=task.task_name,
                )
            )

        return violations

    @staticmethod
    def _interval_from_components(
        trigger_config: Mapping[str, Any],
    ) -> int | float | None:
        """Calculate interval seconds from supported components."""

        units = {
            "weeks": 604800,
            "days": 86400,
            "hours": 3600,
            "minutes": 60,
            "seconds": 1,
        }

        supplied = [
            unit for unit in units if unit in trigger_config
        ]

        if not supplied:
            return None

        total: int | float = 0

        for unit, multiplier in units.items():
            value = trigger_config.get(unit, 0)

            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or value < 0
            ):
                return None

            total += value * multiplier

        return total


class ConfigurationPolicyError(ValueError):
    """Raised when a configuration violates scheduling policy."""

    def __init__(
        self,
        message: str,
        *,
        result: ConfigurationPolicyResult,
    ) -> None:
        super().__init__(message)
        self.result = result
