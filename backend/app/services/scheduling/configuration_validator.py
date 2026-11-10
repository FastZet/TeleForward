"""Validation utilities for scheduled-task configurations."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from typing import Any

from app.services.scheduling.task_config import (
    ScheduledTaskConfig,
    TaskTriggerType,
)


class TaskConfigurationValidationError(ValueError):
    """Raised when a scheduled-task configuration is invalid."""


class ScheduledTaskConfigurationValidator:
    """Validate task and trigger configuration structures."""

    INTERVAL_FIELDS = frozenset({
        "weeks",
        "days",
        "hours",
        "minutes",
        "seconds",
        "start_date",
        "end_date",
        "timezone",
        "jitter",
    })

    CRON_FIELDS = frozenset({
        "year",
        "month",
        "week",
        "day",
        "day_of_week",
        "hour",
        "minute",
        "second",
        "start_date",
        "end_date",
        "timezone",
        "jitter",
    })

    DATE_FIELDS = frozenset({
        "run_date",
        "timezone",
    })

    INTERVAL_COMPONENTS = (
        "weeks",
        "days",
        "hours",
        "minutes",
        "seconds",
    )

    def validate(
        self,
        config: ScheduledTaskConfig,
    ) -> None:
        """Validate a complete scheduled-task configuration."""

        if not isinstance(config, ScheduledTaskConfig):
            raise TypeError(
                "config must be a ScheduledTaskConfig instance"
            )

        self.validate_trigger(
            config.trigger_type,
            config.trigger_config,
        )

    def validate_trigger(
        self,
        trigger_type: TaskTriggerType | str,
        trigger_config: Mapping[str, Any],
    ) -> None:
        """Validate trigger-specific configuration."""

        try:
            trigger = TaskTriggerType(trigger_type)
        except (TypeError, ValueError) as exc:
            raise TaskConfigurationValidationError(
                f"Unsupported trigger type: {trigger_type!r}"
            ) from exc

        if not isinstance(trigger_config, Mapping):
            raise TaskConfigurationValidationError(
                "trigger_config must be a mapping"
            )

        if any(not isinstance(key, str) for key in trigger_config):
            raise TaskConfigurationValidationError(
                "Trigger configuration keys must be strings"
            )

        if trigger is TaskTriggerType.INTERVAL:
            self._validate_interval(trigger_config)
        elif trigger is TaskTriggerType.CRON:
            self._validate_cron(trigger_config)
        elif trigger is TaskTriggerType.DATE:
            self._validate_date(trigger_config)

    def _validate_interval(
        self,
        config: Mapping[str, Any],
    ) -> None:
        self._reject_unknown_fields(config, self.INTERVAL_FIELDS)

        supplied_components = [
            field
            for field in self.INTERVAL_COMPONENTS
            if field in config
        ]

        if not supplied_components:
            raise TaskConfigurationValidationError(
                "Interval trigger requires at least one time component"
            )

        total_seconds = 0.0

        for field in self.INTERVAL_COMPONENTS:
            if field not in config:
                continue

            value = self._positive_number(config[field], field)
            multiplier = {
                "weeks": 604800,
                "days": 86400,
                "hours": 3600,
                "minutes": 60,
                "seconds": 1,
            }[field]

            total_seconds += value * multiplier

        if total_seconds <= 0:
            raise TaskConfigurationValidationError(
                "Interval duration must be greater than zero"
            )

        self._validate_common_date_fields(config)

        if "jitter" in config:
            self._non_negative_number(config["jitter"], "jitter")

    def _validate_cron(
        self,
        config: Mapping[str, Any],
    ) -> None:
        self._reject_unknown_fields(config, self.CRON_FIELDS)

        if not config:
            raise TaskConfigurationValidationError(
                "Cron trigger configuration cannot be empty"
            )

        for field in (
            "year",
            "month",
            "week",
            "day",
            "day_of_week",
            "hour",
            "minute",
            "second",
        ):
            if field not in config:
                continue

            value = config[field]

            if isinstance(value, bool) or not isinstance(
                value,
                (str, int),
            ):
                raise TaskConfigurationValidationError(
                    f"Cron field {field!r} must be a string or integer"
                )

            if isinstance(value, str) and not value.strip():
                raise TaskConfigurationValidationError(
                    f"Cron field {field!r} cannot be empty"
                )

        self._validate_common_date_fields(config)

        if "jitter" in config:
            self._non_negative_number(config["jitter"], "jitter")

    def _validate_date(
        self,
        config: Mapping[str, Any],
    ) -> None:
        self._reject_unknown_fields(config, self.DATE_FIELDS)

        if "run_date" not in config:
            raise TaskConfigurationValidationError(
                "Date trigger requires a run_date"
            )

        run_date = config["run_date"]

        if isinstance(run_date, datetime):
            return

        if isinstance(run_date, date):
            return

        if isinstance(run_date, str):
            try:
                datetime.fromisoformat(run_date)
            except ValueError as exc:
                raise TaskConfigurationValidationError(
                    "run_date must be a valid ISO 8601 date or datetime"
                ) from exc
            return

        raise TaskConfigurationValidationError(
            "run_date must be a date, datetime, or ISO 8601 string"
        )

    def _validate_common_date_fields(
        self,
        config: Mapping[str, Any],
    ) -> None:
        for field in ("start_date", "end_date"):
            if field not in config:
                continue

            value = config[field]

            if isinstance(value, (date, datetime)):
                continue

            if isinstance(value, str):
                try:
                    datetime.fromisoformat(value)
                except ValueError as exc:
                    raise TaskConfigurationValidationError(
                        f"{field} must be a valid ISO 8601 date or datetime"
                    ) from exc
                continue

            raise TaskConfigurationValidationError(
                f"{field} must be a date, datetime, or ISO 8601 string"
            )

        if "timezone" in config:
            timezone = config["timezone"]

            if not isinstance(timezone, str) or not timezone.strip():
                raise TaskConfigurationValidationError(
                    "timezone must be a non-empty string"
                )

    @staticmethod
    def _positive_number(value: Any, field: str) -> float:
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or value <= 0
        ):
            raise TaskConfigurationValidationError(
                f"{field} must be a positive number"
            )

        return float(value)

    @staticmethod
    def _non_negative_number(value: Any, field: str) -> float:
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or value < 0
        ):
            raise TaskConfigurationValidationError(
                f"{field} must be a non-negative number"
            )

        return float(value)

    @staticmethod
    def _reject_unknown_fields(
        config: Mapping[str, Any],
        allowed_fields: frozenset[str],
    ) -> None:
        unknown_fields = set(config) - allowed_fields

        if unknown_fields:
            raise TaskConfigurationValidationError(
                "Unsupported trigger configuration fields: "
                + ", ".join(sorted(unknown_fields))
            )
