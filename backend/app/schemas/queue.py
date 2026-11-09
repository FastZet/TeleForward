
"""
TeleForward processing queue schemas.

Defines:
- Queue task statuses.
- Queue listing filters.
- Queue task responses.
- Queue statistics.
- Retry operation results.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from app.schemas.common import (
    RequestSchema,
    ResponseSchema,
)


class QueueTaskStatusSchema(StrEnum):
    """Lifecycle states of a persistent queue task."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class QueueTaskListQuery(RequestSchema):
    """Filtering parameters for processing queue listings."""

    status: QueueTaskStatusSchema | None = None

    task_type: str | None = Field(
        default=None,
        max_length=100,
    )

    priority_min: int | None = None
    priority_max: int | None = None

    date_from: datetime | None = None
    date_to: datetime | None = None

    search: str | None = Field(
        default=None,
        max_length=500,
    )


class QueueTaskResponse(ResponseSchema):
    """Detailed representation of a persistent queue task."""

    id: int

    task_type: str
    status: QueueTaskStatusSchema

    priority: int

    attempts: int = Field(ge=0)
    max_attempts: int = Field(ge=1)

    scheduled_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None

    last_error: str | None = None

    created_at: datetime
    updated_at: datetime


class QueueTaskSummaryResponse(ResponseSchema):
    """Compact queue task representation for dashboard listings."""

    id: int

    task_type: str
    status: QueueTaskStatusSchema

    priority: int

    attempts: int
    max_attempts: int

    scheduled_at: datetime | None = None
    created_at: datetime


class QueueStatisticsResponse(ResponseSchema):
    """Aggregated processing queue statistics."""

    total: int = Field(ge=0)

    pending: int = Field(ge=0)
    processing: int = Field(ge=0)
    completed: int = Field(ge=0)
    failed: int = Field(ge=0)
    cancelled: int = Field(ge=0)

    @property
    def active(self) -> int:
        """Return the number of tasks awaiting or undergoing processing."""
        return self.pending + self.processing


class QueueRetryResponse(ResponseSchema):
    """Result of requesting a failed task to be retried."""

    task_id: int

    previous_status: QueueTaskStatusSchema
    current_status: QueueTaskStatusSchema

    message: str
