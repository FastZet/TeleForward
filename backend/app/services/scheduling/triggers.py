"""Trigger construction and validation for TeleForward scheduling."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.services.scheduling.job_store import (
    ScheduledJobType,
)

logger = logging.getLogger(__name__)


class TriggerFactory:
    """Construct APScheduler triggers from validated configurations."""

    INTERVAL_FIELDS = {
        "weeks",
        "days",
        "hours",
        "minutes",
        "seconds",
        "start_date",
        "end_date",
        "jitter",
    }

    CRON_FIELDS = {
        "expression",
        "jitter",
    }

    DATE_FIELDS = {
        "run_date",
    }

    @classmethod
    def create(
        cls,
        trigger_type: ScheduledJobType,
        configuration: Mapping[str, Any],
        *,
        timezone_name: str = "UTC",
    ) -> IntervalTrigger | CronTrigger | DateTrigger:
        """Create an APScheduler trigger.

        Args:
            trigger_type: The requested trigger type.
            configuration: Trigger-specific configuration.
            timezone_name: IANA timezone identifier.

        Returns:
            A configured APScheduler trigger.

        Raises:
            TypeError: If the configuration is not a mapping.
            ValueError: If the configuration is invalid.
        """

        if not isinstance(configuration, Mapping):
            raise TypeError("configuration must be a mapping")

        if not isinstance(trigger_type, ScheduledJobType):
            raise TypeError("trigger_type must be a ScheduledJobType")

        timezone = cls._resolve_timezone(timezone_name)
        config = dict(configuration)

        if trigger_type == ScheduledJobType.INTERVAL:
            return cls._create_interval(config, timezone)

        if trigger_type == ScheduledJobType.CRON:
            return cls._create_cron(config, timezone)

        if trigger_type == ScheduledJobType.DATE:
            return cls._create_date(config, timezone)

        raise ValueError(f"Unsupported trigger type: {trigger_type}")

    @classmethod
    def validate(
        cls,
        trigger_type: ScheduledJobType,
        configuration: Mapping[str, Any],
        *,
        timezone_name: str = "UTC",
    ) -> None:
        """Validate a trigger configuration without scheduling a job."""

        cls.create(
            trigger_type,
            configuration,
            timezone_name=timezone_name,
        )

    @classmethod
    def _create_interval(
        cls,
        config: dict[str, Any],
        timezone: ZoneInfo,
    ) -> IntervalTrigger:
        """Build a fixed-interval trigger."""

        cls._reject_unknown_fields(config, cls.INTERVAL_FIELDS)

        interval_fields = (
            "weeks",
            "days",
            "hours",
            "minutes",
            "seconds",
        )

        has_positive_interval = False

        for field in interval_fields:
            value = config.get(field)

            if value is None:
                continue

            if isinstance(value, bool) or not isinstance(
                value, (int, float)
            ):
                raise ValueError(
                    f"Interval field '{field}' must be numeric"
                )

            if value < 0:
                raise ValueError(
                    f"Interval field '{field}' cannot be negative"
                )

            if value > 0:
                has_positive_interval = True

        if not has_positive_interval:
            raise ValueError(
                "At least one positive interval value is required"
            )

        start_date = cls._parse_datetime(
            config.get("start_date"),
            field_name="start_date",
        )
        end_date = cls._parse_datetime(
            config.get("end_date"),
            field_name="end_date",
        )

        if (
            start_date is not None
            and end_date is not None
            and end_date <= start_date
        ):
            raise ValueError("end_date must be later than start_date")

        jitter = cls._validate_jitter(config.get("jitter"))

        arguments = {
            field: config[field]
            for field in interval_fields
            if field in config
        }

        return IntervalTrigger(
            **arguments,
            start_date=start_date,
            end_date=end_date,
            timezone=timezone,
            jitter=jitter,
        )

    @classmethod
    def _create_cron(
        cls,
        config: dict[str, Any],
        timezone: ZoneInfo,
    ) -> CronTrigger:
        """Build a cron trigger from a five-field expression."""

        cls._reject_unknown_fields(config, cls.CRON_FIELDS)

        expression = config.get("expression")

        if not isinstance(expression, str) or not expression.strip():
            raise ValueError("Cron expression cannot be empty")

        fields = expression.split()

        if len(fields) != 5:
            raise ValueError(
                "Cron expression must contain exactly five fields: "
                "minute hour day month day_of_week"
            )

        minute, hour, day, month, day_of_week = fields

        jitter = cls._validate_jitter(config.get("jitter"))

        try:
            return CronTrigger(
                minute=minute,
                hour=hour,
                day=day,
                month=month,
                day_of_week=day_of_week,
                timezone=timezone,
                jitter=jitter,
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Invalid cron expression: {expression}"
            ) from exc

    @classmethod
    def _create_date(
        cls,
        config: dict[str, Any],
        timezone: ZoneInfo,
    ) -> DateTrigger:
        """Build a one-time date trigger."""

        cls._reject_unknown_fields(config, cls.DATE_FIELDS)

        if "run_date" not in config:
            raise ValueError("Date trigger requires run_date")

        run_date = cls._parse_datetime(
            config["run_date"],
            field_name="run_date",
        )

        if run_date is None:
            raise ValueError("run_date cannot be empty")

        return DateTrigger(
            run_date=run_date,
            timezone=timezone,
        )

    @staticmethod
    def _resolve_timezone(timezone_name: str) -> ZoneInfo:
        """Resolve an IANA timezone identifier."""

        if (
            not isinstance(timezone_name, str)
            or not timezone_name.strip()
        ):
            raise ValueError("timezone_name cannot be empty")

        try:
            return ZoneInfo(timezone_name.strip())
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(
                f"Unknown or unavailable timezone: {timezone_name}"
            ) from exc

    @staticmethod
    def _parse_datetime(
        value: datetime | str | None,
        *,
        field_name: str,
    ) -> datetime | None:
        """Parse a datetime and require an explicit timezone."""

        if value is None:
            return None

        if isinstance(value, str):
            try:
                value = datetime.fromisoformat(value)
            except ValueError as exc:
                raise ValueError(
                    f"{field_name} must be a valid ISO 8601 datetime"
                ) from exc

        if not isinstance(value, datetime):
            raise TypeError(
                f"{field_name} must be a datetime or ISO 8601 string"
            )

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(
                f"{field_name} must be timezone-aware"
            )

        return value

    @staticmethod
    def _validate_jitter(value: Any) -> int | None:
        """Validate APScheduler trigger jitter."""

        if value is None:
            return None

        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("jitter must be an integer")

        if value < 0:
            raise ValueError("jitter cannot be negative")

        return value

    @staticmethod
    def _reject_unknown_fields(
        config: Mapping[str, Any],
        allowed_fields: set[str],
    ) -> None:
        """Reject unsupported trigger configuration fields."""

        unknown = set(config) - allowed_fields

        if unknown:
            raise ValueError(
                "Unsupported trigger configuration fields: "
                + ", ".join(sorted(unknown))
            )
