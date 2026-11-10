"""Base abstractions for TeleForward scheduled tasks."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Mapping


class ScheduledTaskStatus(StrEnum):
    """Possible outcomes of a scheduled task execution."""

    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True, slots=True)
class ScheduledTaskContext:
    """Runtime context supplied to a scheduled task."""

    job_id: str
    execution_id: str
    scheduled_at: datetime
    started_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.job_id.strip():
            raise ValueError("job_id cannot be empty")

        if not self.execution_id.strip():
            raise ValueError("execution_id cannot be empty")

        if self.scheduled_at.tzinfo is None:
            raise ValueError("scheduled_at must be timezone-aware")

        if self.started_at.tzinfo is None:
            raise ValueError("started_at must be timezone-aware")


@dataclass(frozen=True, slots=True)
class ScheduledTaskResult:
    """Standardised result returned by a scheduled task."""

    job_id: str
    execution_id: str
    task_name: str
    status: ScheduledTaskStatus
    started_at: datetime
    finished_at: datetime
    message: str | None = None
    error: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.job_id.strip():
            raise ValueError("job_id cannot be empty")

        if not self.execution_id.strip():
            raise ValueError("execution_id cannot be empty")

        if not self.task_name.strip():
            raise ValueError("task_name cannot be empty")

        if self.started_at.tzinfo is None:
            raise ValueError("started_at must be timezone-aware")

        if self.finished_at.tzinfo is None:
            raise ValueError("finished_at must be timezone-aware")

        if self.finished_at < self.started_at:
            raise ValueError("finished_at cannot precede started_at")

        if self.status == ScheduledTaskStatus.FAILED and not self.error:
            raise ValueError("Failed tasks must provide an error")

        if self.status != ScheduledTaskStatus.FAILED and self.error:
            raise ValueError("Only failed tasks may provide an error")

    @property
    def duration_seconds(self) -> float:
        """Return the execution duration in seconds."""

        return max(
            0.0,
            (self.finished_at - self.started_at).total_seconds(),
        )


class BaseScheduledTask(ABC):
    """Abstract base class for executable scheduled tasks.

    Subclasses implement execute() and provide a stable task name.
    Scheduling, persistence, retries, and concurrency are handled by
    the scheduling infrastructure rather than individual task classes.
    """

    name: str

    def __init__(self, *, enabled: bool = True) -> None:
        self.enabled = enabled

        task_name = getattr(self, "name", None)
        if not isinstance(task_name, str) or not task_name.strip():
            raise ValueError(
                f"{self.__class__.__name__} must define a non-empty name"
            )

        self.name = task_name.strip()

    @abstractmethod
    async def execute(
        self,
        context: ScheduledTaskContext,
    ) -> ScheduledTaskResult:
        """Execute the scheduled task."""

    def validate_context(self, context: ScheduledTaskContext) -> None:
        """Validate the context before task execution."""

        if not isinstance(context, ScheduledTaskContext):
            raise TypeError(
                "context must be a ScheduledTaskContext instance"
            )

    def skipped_result(
        self,
        context: ScheduledTaskContext,
        *,
        reason: str,
    ) -> ScheduledTaskResult:
        """Build a standard skipped-task result."""

        self.validate_context(context)

        finished_at = datetime.now(timezone.utc)

        return ScheduledTaskResult(
            job_id=context.job_id,
            execution_id=context.execution_id,
            task_name=self.name,
            status=ScheduledTaskStatus.SKIPPED,
            started_at=context.started_at,
            finished_at=max(finished_at, context.started_at),
            message=reason,
        )

    def failed_result(
        self,
        context: ScheduledTaskContext,
        *,
        error: str,
    ) -> ScheduledTaskResult:
        """Build a standard failed-task result."""

        self.validate_context(context)

        if not error.strip():
            raise ValueError("error cannot be empty")

        finished_at = datetime.now(timezone.utc)

        return ScheduledTaskResult(
            job_id=context.job_id,
            execution_id=context.execution_id,
            task_name=self.name,
            status=ScheduledTaskStatus.FAILED,
            started_at=context.started_at,
            finished_at=max(finished_at, context.started_at),
            error=error,
        )
