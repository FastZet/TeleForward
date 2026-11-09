
"""
TeleForward detailed analytics schemas.

Defines:
- Per-account analytics.
- Per-forwarding-rule analytics.
- Comparative analytics.
- Ranked performance breakdowns.
- Analytics report metadata.

These schemas describe API contracts only. Aggregation and
authorisation must be implemented in the analytics service.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import Field, model_validator

from app.schemas.common import RequestSchema, ResponseSchema
from app.schemas.metrics import MetricsPeriodSchema, MetricsRangeSchema


class AnalyticsDimension(StrEnum):
    """Supported analytics grouping dimensions."""

    ACCOUNT = "account"
    FORWARDING_RULE = "forwarding_rule"
    SOURCE_CHAT = "source_chat"
    DESTINATION_CHAT = "destination_chat"


class AnalyticsSortBy(StrEnum):
    """Fields available for sorting analytics results."""

    TOTAL_PROCESSED = "total_processed"
    TOTAL_SUCCEEDED = "total_succeeded"
    TOTAL_FAILED = "total_failed"
    SUCCESS_RATE = "success_rate"
    AVERAGE_PROCESSING_TIME = "average_processing_time"


class AnalyticsSortOrder(StrEnum):
    """Analytics sorting direction."""

    ASC = "asc"
    DESC = "desc"


class AnalyticsQuery(RequestSchema):
    """Filters and options for detailed analytics reports."""

    range: MetricsRangeSchema = MetricsRangeSchema.LAST_7_DAYS

    period: MetricsPeriodSchema = MetricsPeriodSchema.DAY

    start_date: datetime | None = None

    end_date: datetime | None = None

    dimension: AnalyticsDimension = AnalyticsDimension.FORWARDING_RULE

    account_id: int | None = Field(
        default=None,
        gt=0,
    )

    forwarding_rule_id: int | None = Field(
        default=None,
        gt=0,
    )

    sort_by: AnalyticsSortBy = AnalyticsSortBy.TOTAL_PROCESSED

    sort_order: AnalyticsSortOrder = AnalyticsSortOrder.DESC

    limit: int = Field(
        default=20,
        ge=1,
        le=100,
    )

    offset: int = Field(
        default=0,
        ge=0,
    )

    @model_validator(mode="after")
    def validate_analytics_range(self):
        """Validate reporting date boundaries."""

        if self.range == MetricsRangeSchema.CUSTOM:
            if self.start_date is None or self.end_date is None:
                raise ValueError(
                    "Custom analytics range requires start_date and end_date"
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
            and self.end_date <= self.start_date
        ):
            raise ValueError(
                "end_date must be later than start_date"
            )

        return self


class AnalyticsTotals(ResponseSchema):
    """Common processing totals for an analytics dimension."""

    total_processed: int = Field(
        default=0,
        ge=0,
    )

    total_succeeded: int = Field(
        default=0,
        ge=0,
    )

    total_failed: int = Field(
        default=0,
        ge=0,
    )

    total_skipped: int = Field(
        default=0,
        ge=0,
    )

    total_duplicates: int = Field(
        default=0,
        ge=0,
    )

    success_rate: float = Field(
        default=0,
        ge=0,
        le=100,
    )

    failure_rate: float = Field(
        default=0,
        ge=0,
        le=100,
    )

    average_processing_time_ms: float | None = Field(
        default=None,
        ge=0,
    )

    @model_validator(mode="after")
    def validate_rates(self):
        """Prevent success and failure rates from exceeding 100%."""

        if self.success_rate + self.failure_rate > 100.0001:
            raise ValueError(
                "Success and failure rates cannot total more than 100%"
            )

        return self


class AccountAnalyticsItem(AnalyticsTotals):
    """Analytics for one Telegram account."""

    account_id: int = Field(gt=0)

    account_name: str = Field(
        min_length=1,
        max_length=255,
    )

    phone_number: str | None = Field(
        default=None,
        max_length=32,
    )

    is_connected: bool = False

    active_rules: int = Field(
        default=0,
        ge=0,
    )


class ForwardingRuleAnalyticsItem(AnalyticsTotals):
    """Analytics for one forwarding rule."""

    forwarding_rule_id: int = Field(gt=0)

    rule_name: str = Field(
        min_length=1,
        max_length=255,
    )

    account_id: int = Field(gt=0)

    is_enabled: bool = False

    source_chat_name: str | None = Field(
        default=None,
        max_length=255,
    )

    destination_chat_name: str | None = Field(
        default=None,
        max_length=255,
    )


class ChatAnalyticsItem(AnalyticsTotals):
    """Analytics for one source or destination chat."""

    chat_id: int = Field(gt=0)

    chat_name: str = Field(
        min_length=1,
        max_length=255,
    )

    account_id: int = Field(gt=0)

    chat_type: str | None = Field(
        default=None,
        max_length=50,
    )


class AnalyticsBreakdownResponse(ResponseSchema):
    """Paginated analytics breakdown."""

    dimension: AnalyticsDimension

    items: list[
        AccountAnalyticsItem
        | ForwardingRuleAnalyticsItem
        | ChatAnalyticsItem
    ] = Field(default_factory=list)

    total_items: int = Field(
        default=0,
        ge=0,
    )

    limit: int = Field(
        ge=1,
        le=100,
    )

    offset: int = Field(
        default=0,
        ge=0,
    )

    generated_at: datetime

    @model_validator(mode="after")
    def validate_pagination(self):
        """Ensure the returned page does not exceed the total count."""

        if len(self.items) > self.limit:
            raise ValueError(
                "Returned item count cannot exceed the requested limit"
            )

        return self


class AnalyticsComparisonItem(ResponseSchema):
    """Metrics for one side of a comparison."""

    label: str = Field(
        min_length=1,
        max_length=255,
    )

    start_date: datetime

    end_date: datetime

    totals: AnalyticsTotals

    @model_validator(mode="after")
    def validate_comparison_period(self):
        """Validate comparison period boundaries."""

        if (
            self.start_date.tzinfo is None
            or self.end_date.tzinfo is None
        ):
            raise ValueError(
                "Comparison dates must be timezone-aware"
            )

        if self.end_date <= self.start_date:
            raise ValueError(
                "Comparison end_date must be later than start_date"
            )

        return self


class AnalyticsComparisonResponse(ResponseSchema):
    """Comparison between two reporting periods."""

    dimension: AnalyticsDimension

    current: AnalyticsComparisonItem

    previous: AnalyticsComparisonItem

    generated_at: datetime


class AnalyticsReportResponse(ResponseSchema):
    """Complete detailed analytics report."""

    range: MetricsRangeSchema

    period: MetricsPeriodSchema

    start_date: datetime

    end_date: datetime

    totals: AnalyticsTotals

    breakdown: AnalyticsBreakdownResponse

    generated_at: datetime

    @model_validator(mode="after")
    def validate_report_period(self):
        """Validate report date boundaries."""

        if (
            self.start_date.tzinfo is None
            or self.end_date.tzinfo is None
        ):
            raise ValueError(
                "Report dates must be timezone-aware"
            )

        if self.end_date <= self.start_date:
            raise ValueError(
                "Report end_date must be later than start_date"
            )

        return self
