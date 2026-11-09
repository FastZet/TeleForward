
"""
TeleForward metrics and analytics schemas.

Defines:
- Dashboard summary metrics.
- Forwarding performance statistics.
- Queue processing metrics.
- Delivery success and failure statistics.
- Time-series analytics.
- Metrics query filters.

Metrics are derived from persisted application records and should
not be treated as authoritative accounting records.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import Field, model_validator

from app.schemas.common import RequestSchema, ResponseSchema


class MetricsPeriodSchema(StrEnum):
    """Supported analytics aggregation periods."""

    HOUR = "hour"
    DAY = "day"
    WEEK = "week"
    MONTH = "month"


class MetricsRangeSchema(StrEnum):
    """Predefined dashboard reporting ranges."""

    LAST_HOUR = "last_hour"
    LAST_24_HOURS = "last_24_hours"
    LAST_7_DAYS = "last_7_days"
    LAST_30_DAYS = "last_30_days"
    LAST_90_DAYS = "last_90_days"
    CUSTOM = "custom"


class MetricsQuery(RequestSchema):
    """Filters for retrieving application metrics."""

    range: MetricsRangeSchema = MetricsRangeSchema.LAST_24_HOURS

    period: MetricsPeriodSchema = MetricsPeriodSchema.HOUR

    start_date: datetime | None = None

    end_date: datetime | None = None

    account_id: int | None = Field(
        default=None,
        gt=0,
    )

    forwarding_rule_id: int | None = Field(
        default=None,
        gt=0,
    )

    @model_validator(mode="after")
    def validate_metrics_range(self):
        """Validate custom reporting date boundaries."""

        if self.range == MetricsRangeSchema.CUSTOM:
            if self.start_date is None or self.end_date is None:
                raise ValueError(
                    "Custom metrics range requires start_date and end_date"
                )

        if self.start_date is not None:
            if self.start_date.tzinfo is None:
                raise ValueError(
                    "start_date must be timezone-aware"
                )

        if self.end_date is not None:
            if self.end_date.tzinfo is None:
                raise ValueError(
                    "end_date must be timezone-aware"
                )

        if (
            self.start_date is not None
            and self.end_date is not None
            and self.end_date < self.start_date
        ):
            raise ValueError(
                "end_date must be later than or equal to start_date"
            )

        return self


class DashboardSummaryMetrics(ResponseSchema):
    """High-level dashboard statistics."""

    total_telegram_accounts: int = Field(
        default=0,
        ge=0,
    )

    connected_telegram_accounts: int = Field(
        default=0,
        ge=0,
    )

    total_forwarding_rules: int = Field(
        default=0,
        ge=0,
    )

    active_forwarding_rules: int = Field(
        default=0,
        ge=0,
    )

    total_messages_received: int = Field(
        default=0,
        ge=0,
    )

    total_messages_forwarded: int = Field(
        default=0,
        ge=0,
    )

    total_messages_failed: int = Field(
        default=0,
        ge=0,
    )

    pending_queue_jobs: int = Field(
        default=0,
        ge=0,
    )

    processing_queue_jobs: int = Field(
        default=0,
        ge=0,
    )

    failed_queue_jobs: int = Field(
        default=0,
        ge=0,
    )

    active_scheduled_jobs: int = Field(
        default=0,
        ge=0,
    )

    generated_at: datetime


class ForwardingMetrics(ResponseSchema):
    """Forwarding performance statistics."""

    total_attempts: int = Field(
        default=0,
        ge=0,
    )

    successful_deliveries: int = Field(
        default=0,
        ge=0,
    )

    failed_deliveries: int = Field(
        default=0,
        ge=0,
    )

    skipped_messages: int = Field(
        default=0,
        ge=0,
    )

    duplicate_messages: int = Field(
        default=0,
        ge=0,
    )

    success_rate_percent: float = Field(
        default=0,
        ge=0,
        le=100,
    )

    failure_rate_percent: float = Field(
        default=0,
        ge=0,
        le=100,
    )

    average_delivery_time_ms: float | None = Field(
        default=None,
        ge=0,
    )

    messages_per_minute: float = Field(
        default=0,
        ge=0,
    )


class QueueMetrics(ResponseSchema):
    """Background queue performance statistics."""

    pending_jobs: int = Field(
        default=0,
        ge=0,
    )

    processing_jobs: int = Field(
        default=0,
        ge=0,
    )

    completed_jobs: int = Field(
        default=0,
        ge=0,
    )

    failed_jobs: int = Field(
        default=0,
        ge=0,
    )

    cancelled_jobs: int = Field(
        default=0,
        ge=0,
    )

    average_wait_time_ms: float | None = Field(
        default=None,
        ge=0,
    )

    average_processing_time_ms: float | None = Field(
        default=None,
        ge=0,
    )

    oldest_pending_job_at: datetime | None = None

    measured_at: datetime


class MetricsDataPoint(ResponseSchema):
    """One time-series measurement."""

    timestamp: datetime

    received: int = Field(
        default=0,
        ge=0,
    )

    forwarded: int = Field(
        default=0,
        ge=0,
    )

    failed: int = Field(
        default=0,
        ge=0,
    )

    skipped: int = Field(
        default=0,
        ge=0,
    )


class MetricsTimeSeriesResponse(ResponseSchema):
    """Time-series analytics response."""

    period: MetricsPeriodSchema

    start_date: datetime

    end_date: datetime

    timezone: str

    points: list[MetricsDataPoint] = Field(
        default_factory=list,
    )

    @model_validator(mode="after")
    def validate_time_range(self):
        """Ensure the returned time range is valid."""

        if self.end_date < self.start_date:
            raise ValueError(
                "end_date must be later than or equal to start_date"
            )

        if (
            self.start_date.tzinfo is None
            or self.end_date.tzinfo is None
        ):
            raise ValueError(
                "Time-series boundaries must be timezone-aware"
            )

        return self


class MetricsOverviewResponse(ResponseSchema):
    """Combined analytics response for the dashboard."""

    summary: DashboardSummaryMetrics

    forwarding: ForwardingMetrics

    queue: QueueMetrics

    time_series: MetricsTimeSeriesResponse

    generated_at: datetime
