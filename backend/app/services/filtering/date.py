"""
TeleForward date and time filtering utilities.

Provides date-based matching operations for Telegram messages.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


@dataclass(frozen=True, slots=True)
class DateFilterResult:
    """Result of date and time filtering."""

    matched: bool
    reason: str


@dataclass(frozen=True, slots=True)
class DateFilterConfig:
    """Configuration for date and time restrictions."""

    start_datetime: datetime | None = None
    end_datetime: datetime | None = None

    start_date: date | None = None
    end_date: date | None = None

    start_time: time | None = None
    end_time: time | None = None

    weekdays: frozenset[int] = frozenset()

    timezone_name: str = "UTC"

    include_start: bool = True
    include_end: bool = True


class DateFilter:
    """Evaluate message dates against configurable time restrictions."""

    def validate_config(
        self,
        config: DateFilterConfig,
    ) -> None:
        """Validate date, time and timezone configuration."""
        if (
            config.start_datetime is not None
            and config.start_datetime.tzinfo is None
        ):
            raise ValueError(
                "start_datetime must be timezone-aware."
            )

        if (
            config.end_datetime is not None
            and config.end_datetime.tzinfo is None
        ):
            raise ValueError(
                "end_datetime must be timezone-aware."
            )

        if (
            config.start_datetime is not None
            and config.end_datetime is not None
            and config.start_datetime > config.end_datetime
        ):
            raise ValueError(
                "start_datetime cannot be later than end_datetime."
            )

        if (
            config.start_date is not None
            and config.end_date is not None
            and config.start_date > config.end_date
        ):
            raise ValueError(
                "start_date cannot be later than end_date."
            )

        if any(
            not isinstance(day, int)
            or isinstance(day, bool)
            or day < 0
            or day > 6
            for day in config.weekdays
        ):
            raise ValueError(
                "Weekdays must be integers between 0 and 6."
            )

        try:
            ZoneInfo(config.timezone_name)
        except (ZoneInfoNotFoundError, TypeError) as exc:
            raise ValueError(
                f"Invalid timezone: {config.timezone_name!r}"
            ) from exc

    def matches(
        self,
        message_datetime: datetime,
        config: DateFilterConfig,
    ) -> DateFilterResult:
        """Determine whether a message timestamp satisfies the filters."""
        self.validate_config(config)

        if message_datetime.tzinfo is None:
            raise ValueError(
                "Message datetime must be timezone-aware."
            )

        target_timezone = ZoneInfo(config.timezone_name)

        local_datetime = message_datetime.astimezone(
            target_timezone
        )

        if config.start_datetime is not None:
            start = config.start_datetime.astimezone(
                target_timezone
            )

            if config.include_start:
                if local_datetime < start:
                    return DateFilterResult(
                        False,
                        "Message is earlier than the start datetime.",
                    )
            elif local_datetime <= start:
                return DateFilterResult(
                    False,
                    "Message is not later than the start datetime.",
                )

        if config.end_datetime is not None:
            end = config.end_datetime.astimezone(
                target_timezone
            )

            if config.include_end:
                if local_datetime > end:
                    return DateFilterResult(
                        False,
                        "Message is later than the end datetime.",
                    )
            elif local_datetime >= end:
                return DateFilterResult(
                    False,
                    "Message is not earlier than the end datetime.",
                )

        if (
            config.start_date is not None
            and local_datetime.date() < config.start_date
        ):
            return DateFilterResult(
                False,
                "Message is earlier than the configured start date.",
            )

        if (
            config.end_date is not None
            and local_datetime.date() > config.end_date
        ):
            return DateFilterResult(
                False,
                "Message is later than the configured end date.",
            )

        if config.weekdays and local_datetime.weekday() not in config.weekdays:
            return DateFilterResult(
                False,
                "Message was sent on an excluded weekday.",
            )

        if config.start_time is not None or config.end_time is not None:
            if not self._matches_time_window(
                local_datetime.time().replace(tzinfo=None),
                config.start_time,
                config.end_time,
            ):
                return DateFilterResult(
                    False,
                    "Message falls outside the permitted time window.",
                )

        return DateFilterResult(
            True,
            "Message satisfies all date and time restrictions.",
        )

    @staticmethod
    def _matches_time_window(
        value: time,
        start: time | None,
        end: time | None,
    ) -> bool:
        """
        Evaluate a time-of-day window.

        Supports overnight windows, for example 22:00–06:00.
        """
        if start is None:
            return value <= end

        if end is None:
            return value >= start

        if start <= end:
            return start <= value <= end

        # Overnight window crossing midnight.
        return value >= start or value <= end

    @staticmethod
    def relative_window(
        *,
        days: int,
        reference: datetime | None = None,
    ) -> tuple[datetime, datetime]:
        """Return a UTC interval covering the previous N days."""
        if isinstance(days, bool) or not isinstance(days, int) or days < 1:
            raise ValueError("days must be a positive integer.")

        end = reference or datetime.now(timezone.utc)

        if end.tzinfo is None:
            raise ValueError("Reference datetime must be timezone-aware.")

        end = end.astimezone(timezone.utc)
        start = end - timedelta(days=days)

        return start, end
