
"""
TeleForward forwarding recovery schemas.

Defines:
- Recovery job configuration.
- Retry policies.
- Recovery job controls.
- Recovery progress and results.
- Recovery job filtering.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import Field, model_validator

from app.schemas.common import (
    RequestSchema,
    ResponseSchema,
)


class RecoveryStatusSchema(StrEnum):
    """Possible recovery job states."""

    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    PARTIALLY_COMPLETED = "partially_completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RecoveryScopeSchema(StrEnum):
    """Messages eligible for recovery."""

    FAILED_MESSAGES = "failed_messages"
    INTERRUPTED_MESSAGES = "interrupted_messages"
    ALL_UNDELIVERED = "all_undelivered"


class RetryStrategySchema(StrEnum):
    """Supported retry scheduling strategies."""

    IMMEDIATE = "immediate"
    FIXED_DELAY = "fixed_delay"
    EXPONENTIAL_BACKOFF = "exponential_backoff"


class RecoveryJobCreateRequest(RequestSchema):
    """Create a forwarding recovery job."""

    forwarding_rule_id: int | None = Field(
        default=None,
        gt=0,
    )

    scope: RecoveryScopeSchema = RecoveryScopeSchema.ALL_UNDELIVERED

    retry_strategy: RetryStrategySchema = (
        RetryStrategySchema.EXPONENTIAL_BACKOFF
    )

    max_attempts: int = Field(
        default=5,
        ge=1,
        le=100,
    )

    initial_delay_seconds: float = Field(
        default=5,
        ge=0,
        le=86400,
    )

    maximum_delay_seconds: float = Field(
        default=3600,
        ge=0,
        le=604800,
    )

    backoff_multiplier: float = Field(
        default=2.0,
        gt=1,
        le=10,
    )

    batch_size: int = Field(
        default=50,
        ge=1,
        le=1000,
    )

    include_media: bool = True

    @model_validator(mode="after")
    def validate_retry_configuration(self):
        """Validate retry policy settings."""

        if self.maximum_delay_seconds < self.initial_delay_seconds:
            raise ValueError(
                "maximum_delay_seconds must be greater than or equal "
                "to initial_delay_seconds"
            )

        if self.retry_strategy != RetryStrategySchema.EXPONENTIAL_BACKOFF:
            if self.backoff_multiplier != 2.0:
                raise ValueError(
                    "backoff_multiplier is only configurable "
                    "for exponential_backoff"
                )

        return self


class RecoveryJobControlRequest(RequestSchema):
    """Pause, resume, or cancel a recovery job."""

    action: str = Field(
        pattern=r"^(pause|resume|cancel)$",
    )


class RecoveryRetryRequest(RequestSchema):
    """Request retry of selected failed messages."""

    message_ids: list[int] = Field(
        min_length=1,
        max_length=1000,
    )

    reset_attempt_count: bool = False

    @model_validator(mode="after")
    def validate_message_ids(self):
        """Require unique positive message identifiers."""

        if any(message_id <= 0 for message_id in self.message_ids):
            raise ValueError(
                "message_ids must contain positive IDs"
            )

        if len(set(self.message_ids)) != len(self.message_ids):
            raise ValueError(
                "message_ids must not contain duplicates"
            )

        return self


class RecoveryJobListQuery(RequestSchema):
    """Filter recovery jobs."""

    forwarding_rule_id: int | None = Field(
        default=None,
        gt=0,
    )

    status: RecoveryStatusSchema | None = None

    scope: RecoveryScopeSchema | None = None


class RecoveryJobResponse(ResponseSchema):
    """Recovery job details."""

    id: int

    forwarding_rule_id: int | None = None

    status: RecoveryStatusSchema

    scope: RecoveryScopeSchema

    retry_strategy: RetryStrategySchema

    max_attempts: int

    initial_delay_seconds: float
    maximum_delay_seconds: float
    backoff_multiplier: float

    batch_size: int

    include_media: bool

    total_messages: int | None = None

    processed_messages: int = 0
    recovered_messages: int = 0
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


class RecoveryProgressResponse(ResponseSchema):
    """Live recovery execution progress."""

    job_id: int

    status: RecoveryStatusSchema

    total_messages: int | None = None
    processed_messages: int = 0

    recovered_messages: int = 0
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


class RecoveryResultResponse(ResponseSchema):
    """Summary of a recovery execution."""

    job_id: int

    status: RecoveryStatusSchema

    total_messages: int | None = None
    processed_messages: int

    recovered_messages: int
    skipped_messages: int
    failed_messages: int

    started_at: datetime | None = None
    completed_at: datetime | None = None

    duration_seconds: float | None = Field(
        default=None,
        ge=0,
    )

    error_message: str | None = None
