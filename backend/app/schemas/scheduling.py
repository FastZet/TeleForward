
"""
TeleForward scheduling schemas.

Defines:
- Schedule execution statuses.
- Schedule recurrence types.
- Schedule creation and update requests.
- Schedule responses.
- Schedule execution history.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import Field, model_validator

from app.schemas.common import (
    RequestSchema,
    ResponseSchema,
)


class ScheduleStatusSchema(StrEnum):
    """Lifecycle states of a scheduled operation."""

    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ScheduleTypeSchema(StrEnum):
    """Supported schedule recurrence patterns."""

    ONCE = "once"
    INTERVAL = "interval"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    CRON = "cron"


class ScheduleExecutionStatusSchema(StrEnum):
    """Execution outcomes for scheduled operations."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class ScheduleCreateRequest(RequestSchema):
    """Request to create a scheduled forwarding operation."""

    name: str = Field(
        min_length=1,
        max_length=150,
    )

    description: str | None = Field(
        default=None,
        max_length=500,
    )

    forwarding_rule_id: int = Field(
        gt=0,
    )

    schedule_type: ScheduleTypeSchema

    timezone: str = Field(
        default="UTC",
        min_length=1,
        max_length=100,
    )

    start_at: datetime

    end_at: datetime | None = None

    interval_seconds: int | None = Field(
        default=None,
        ge=1,
        le=31536000,
    )

    cron_expression: str | None = Field(
        default=None,
        max_length=100,
    )

    weekdays: list[int] | None = Field(
        default=None,
    )

    day_of_month: int | None = Field(
        default=None,
        ge=1,
        le=31,
    )

    max_executions: int | None = Field(
        default=None,
        ge=1,
    )

    @model_validator(mode="after")
    def validate_schedule_configuration(self):
        """Validate recurrence-specific configuration."""

        if self.end_at is not None and self.end_at <= self.start_at:
            raise ValueError("end_at must be later than start_at")

        if self.schedule_type == ScheduleTypeSchema.INTERVAL:
            if self.interval_seconds is None:
                raise ValueError(
                    "interval_seconds is required for interval schedules"
                )

        elif self.interval_seconds is not None:
            raise ValueError(
                "interval_seconds is only valid for interval schedules"
            )

        if self.schedule_type == ScheduleTypeSchema.CRON:
            if not self.cron_expression:
                raise ValueError(
                    "cron_expression is required for cron schedules"
                )

        elif self.cron_expression is not None:
            raise ValueError(
                "cron_expression is only valid for cron schedules"
            )

        if self.schedule_type == ScheduleTypeSchema.WEEKLY:
            if not self.weekdays:
                raise ValueError(
                    "weekdays must be provided for weekly schedules"
                )

        elif self.weekdays is not None:
            raise ValueError(
                "weekdays are only valid for weekly schedules"
            )

        if self.weekdays is not None:
            if any(day not in range(7) for day in self.weekdays):
                raise ValueError(
                    "weekdays must contain values from 0 to 6"
                )

            if len(set(self.weekdays)) != len(self.weekdays):
                raise ValueError("weekdays must not contain duplicates")

        if self.schedule_type == ScheduleTypeSchema.MONTHLY:
            if self.day_of_month is None:
                raise ValueError(
                    "day_of_month is required for monthly schedules"
                )

        elif self.day_of_month is not None:
            raise ValueError(
                "day_of_month is only valid for monthly schedules"
            )

        if self.schedule_type == ScheduleTypeSchema.ONCE:
            if any(
                value is not None
                for value in (
                    self.interval_seconds,
                    self.cron_expression,
                    self.weekdays,
                    self.day_of_month,
                )
            ):
                raise ValueError(
                    "One-time schedules cannot define recurrence settings"
                )

        return self


class ScheduleUpdateRequest(RequestSchema):
    """Request to update an existing schedule."""

    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=150,
    )

    description: str | None = Field(
        default=None,
        max_length=500,
    )

    schedule_type: ScheduleTypeSchema | None = None

    timezone: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
    )

    start_at: datetime | None = None
    end_at: datetime | None = None

    interval_seconds: int | None = Field(
        default=None,
        ge=1,
        le=31536000,
    )

    cron_expression: str | None = Field(
        default=None,
        max_length=100,
    )

    weekdays: list[int] | None = None

    day_of_month: int | None = Field(
        default=None,
        ge=1,
        le=31,
    )

    max_executions: int | None = Field(
        default=None,
        ge=1,
    )


class ScheduleListQuery(RequestSchema):
    """Filtering parameters for scheduled operations."""

    forwarding_rule_id: int | None = Field(
        default=None,
        gt=0,
    )

    status: ScheduleStatusSchema | None = None

    schedule_type: ScheduleTypeSchema | None = None

    date_from: datetime | None = None
    date_to: datetime | None = None


class ScheduleResponse(ResponseSchema):
    """Detailed scheduled operation representation."""

    id: int

    name: str
    description: str | None = None

    forwarding_rule_id: int

    schedule_type: ScheduleTypeSchema
    status: ScheduleStatusSchema

    timezone: str

    start_at: datetime
    end_at: datetime | None = None

    next_run_at: datetime | None = None
    last_run_at: datetime | None = None

    interval_seconds: int | None = None
    cron_expression: str | None = None

    weekdays: list[int] | None = None
    day_of_month: int | None = None

    execution_count: int
    max_executions: int | None = None

    created_at: datetime
    updated_at: datetime


class ScheduleExecutionResponse(ResponseSchema):
    """Individual scheduled execution history entry."""

    id: int

    schedule_id: int

    status: ScheduleExecutionStatusSchema

    scheduled_for: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None

    error_message: str | None = None

    created_at: datetime


class ScheduleControlResponse(ResponseSchema):
    """Result of a schedule control operation."""

    schedule_id: int

    previous_status: ScheduleStatusSchema
    current_status: ScheduleStatusSchema

    message: str
