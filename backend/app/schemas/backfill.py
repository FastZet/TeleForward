
"""
TeleForward historical message backfill schemas.

Defines:
- Backfill job creation and configuration.
- Historical message range selection.
- Backfill execution status.
- Progress and result reporting.
- Backfill listing and filtering.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import Field, model_validator

from app.schemas.common import (
    RequestSchema,
    ResponseSchema,
)


class BackfillStatusSchema(StrEnum):
    """Possible backfill job states."""

    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    PARTIALLY_COMPLETED = "partially_completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class BackfillRangeTypeSchema(StrEnum):
    """Supported historical message range selection methods."""

    ALL_AVAILABLE = "all_available"
    MESSAGE_ID = "message_id"
    DATE_RANGE = "date_range"
    LAST_MESSAGES = "last_messages"


class BackfillJobCreateRequest(RequestSchema):
    """Create a historical message backfill job."""

    forwarding_rule_id: int = Field(
        gt=0,
    )

    range_type: BackfillRangeTypeSchema = (
        BackfillRangeTypeSchema.ALL_AVAILABLE
    )

    start_message_id: int | None = Field(
        default=None,
        gt=0,
    )

    end_message_id: int | None = Field(
        default=None,
        gt=0,
    )

    start_date: datetime | None = None

    end_date: datetime | None = None

    last_messages_count: int | None = Field(
        default=None,
        gt=0,
        le=100000,
    )

    batch_size: int = Field(
        default=100,
        ge=1,
        le=1000,
    )

    delay_between_batches_seconds: float = Field(
        default=1.0,
        ge=0,
        le=3600,
    )

    skip_existing: bool = True

    include_media: bool = True

    @model_validator(mode="after")
    def validate_range_configuration(self):
        """Ensure the selected range has valid parameters."""

        if self.range_type == BackfillRangeTypeSchema.MESSAGE_ID:
            if self.start_message_id is None:
                raise ValueError(
                    "start_message_id is required for message_id range"
                )

            if (
                self.end_message_id is not None
                and self.end_message_id < self.start_message_id
            ):
                raise ValueError(
                    "end_message_id must be greater than or equal "
                    "to start_message_id"
                )

        elif self.range_type == BackfillRangeTypeSchema.DATE_RANGE:
            if self.start_date is None:
                raise ValueError(
                    "start_date is required for date_range"
                )

            if self.end_date is not None and self.end_date < self.start_date:
                raise ValueError(
                    "end_date must be later than or equal to start_date"
                )

            if (
                self.start_date.tzinfo is None
                or (
                    self.end_date is not None
                    and self.end_date.tzinfo is None
                )
            ):
                raise ValueError(
                    "Backfill dates must include timezone information"
                )

        elif self.range_type == BackfillRangeTypeSchema.LAST_MESSAGES:
            if self.last_messages_count is None:
                raise ValueError(
                    "last_messages_count is required for last_messages"
                )

        if self.range_type != BackfillRangeTypeSchema.MESSAGE_ID:
            if (
                self.start_message_id is not None
                or self.end_message_id is not None
            ):
                raise ValueError(
                    "Message ID boundaries are only valid "
                    "for message_id range"
                )

        if self.range_type != BackfillRangeTypeSchema.DATE_RANGE:
            if self.start_date is not None or self.end_date is not None:
                raise ValueError(
                    "Date boundaries are only valid for date_range"
                )

        if self.range_type != BackfillRangeTypeSchema.LAST_MESSAGES:
            if self.last_messages_count is not None:
                raise ValueError(
                    "last_messages_count is only valid "
                    "for last_messages range"
                )

        return self


class BackfillJobControlRequest(RequestSchema):
    """Control an existing backfill job."""

    action: str = Field(
        pattern=r"^(pause|resume|cancel)$",
    )


class BackfillJobListQuery(RequestSchema):
    """Filter backfill jobs."""

    forwarding_rule_id: int | None = Field(
        default=None,
        gt=0,
    )

    status: BackfillStatusSchema | None = None


class BackfillJobResponse(ResponseSchema):
    """Backfill job details."""

    id: int

    forwarding_rule_id: int

    status: BackfillStatusSchema

    range_type: BackfillRangeTypeSchema

    start_message_id: int | None = None
    end_message_id: int | None = None

    start_date: datetime | None = None
    end_date: datetime | None = None

    last_messages_count: int | None = None

    batch_size: int

    delay_between_batches_seconds: float

    skip_existing: bool
    include_media: bool

    total_messages: int | None = None
    processed_messages: int = 0
    forwarded_messages: int = 0
    skipped_messages: int = 0
    failed_messages: int = 0

    progress_percentage: float = Field(
        default=0,
        ge=0,
        le=100,
    )

    error_message: str | None = None

    started_at: datetime | None = None
    completed_at: datetime | None = None

    created_at: datetime
    updated_at: datetime


class BackfillProgressResponse(ResponseSchema):
    """Live progress information for a backfill job."""

    job_id: int

    status: BackfillStatusSchema

    total_messages: int | None = None
    processed_messages: int = 0

    forwarded_messages: int = 0
    skipped_messages: int = 0
    failed_messages: int = 0

    progress_percentage: float = Field(
        default=0,
        ge=0,
        le=100,
    )

    current_message_id: int | None = None

    estimated_remaining_seconds: float | None = Field(
        default=None,
        ge=0,
    )


class BackfillResultResponse(ResponseSchema):
    """Summary of a completed or interrupted backfill job."""

    job_id: int

    status: BackfillStatusSchema

    total_messages: int | None = None
    processed_messages: int

    forwarded_messages: int
    skipped_messages: int
    failed_messages: int

    started_at: datetime | None = None
    completed_at: datetime | None = None

    duration_seconds: float | None = Field(
        default=None,
        ge=0,
    )

    error_message: str | None = None
