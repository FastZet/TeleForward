"""Scheduling lifecycle events for TeleForward."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Mapping
from uuid import uuid4


class SchedulingEventType(StrEnum):
    """Supported scheduling event types."""

    JOB_CREATED = "job_created"
    JOB_UPDATED = "job_updated"
    JOB_ENABLED = "job_enabled"
    JOB_DISABLED = "job_disabled"
    JOB_DELETED = "job_deleted"
    JOB_RESTORED = "job_restored"

    EXECUTION_STARTED = "execution_started"
    EXECUTION_COMPLETED = "execution_completed"
    EXECUTION_FAILED = "execution_failed"
    EXECUTION_SKIPPED = "execution_skipped"

    EXECUTION_RETRYING = "execution_retrying"
    EXECUTION_RETRY_EXHAUSTED = "execution_retry_exhausted"

    SCHEDULER_STARTED = "scheduler_started"
    SCHEDULER_PAUSED = "scheduler_paused"
    SCHEDULER_RESUMED = "scheduler_resumed"
    SCHEDULER_STOPPED = "scheduler_stopped"

    RESTORATION_COMPLETED = "restoration_completed"
    RESTORATION_FAILED = "restoration_failed"


@dataclass(frozen=True, slots=True)
class SchedulingEvent:
    """Immutable event emitted by scheduling components."""

    event_type: SchedulingEventType
    event_id: str = field(default_factory=lambda: str(uuid4()))
    occurred_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    job_id: str | None = None
    task_name: str | None = None
    execution_id: str | None = None
    message: str | None = None
    data: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.event_type, SchedulingEventType):
            raise TypeError(
                "event_type must be a SchedulingEventType"
            )

        if not isinstance(self.event_id, str) or not self.event_id.strip():
            raise ValueError("event_id cannot be empty")

        if (
            not isinstance(self.occurred_at, datetime)
            or self.occurred_at.tzinfo is None
            or self.occurred_at.utcoffset() is None
        ):
            raise ValueError(
                "occurred_at must be a timezone-aware datetime"
            )

        optional_identifiers = {
            "job_id": self.job_id,
            "task_name": self.task_name,
            "execution_id": self.execution_id,
        }

        for field_name, value in optional_identifiers.items():
            if value is not None and (
                not isinstance(value, str) or not value.strip()
            ):
                raise ValueError(
                    f"{field_name} must be a non-empty string when supplied"
                )

        if self.message is not None and not isinstance(
            self.message,
            str,
        ):
            raise TypeError("message must be a string or None")

        if not isinstance(self.data, Mapping):
            raise TypeError("data must be a mapping")

        object.__setattr__(self, "data", dict(self.data))


class SchedulingEventFactory:
    """Construct common scheduling lifecycle events."""

    @staticmethod
    def job_event(
        event_type: SchedulingEventType,
        *,
        job_id: str,
        task_name: str,
        message: str | None = None,
        data: Mapping[str, Any] | None = None,
    ) -> SchedulingEvent:
        """Create an event associated with a scheduled job."""

        if event_type not in {
            SchedulingEventType.JOB_CREATED,
            SchedulingEventType.JOB_UPDATED,
            SchedulingEventType.JOB_ENABLED,
            SchedulingEventType.JOB_DISABLED,
            SchedulingEventType.JOB_DELETED,
            SchedulingEventType.JOB_RESTORED,
        }:
            raise ValueError(
                "event_type is not a job lifecycle event"
            )

        return SchedulingEvent(
            event_type=event_type,
            job_id=job_id,
            task_name=task_name,
            message=message,
            data=data or {},
        )

    @staticmethod
    def execution_event(
        event_type: SchedulingEventType,
        *,
        job_id: str,
        task_name: str,
        execution_id: str,
        message: str | None = None,
        data: Mapping[str, Any] | None = None,
    ) -> SchedulingEvent:
        """Create an event associated with a task execution."""

        if event_type not in {
            SchedulingEventType.EXECUTION_STARTED,
            SchedulingEventType.EXECUTION_COMPLETED,
            SchedulingEventType.EXECUTION_FAILED,
            SchedulingEventType.EXECUTION_SKIPPED,
            SchedulingEventType.EXECUTION_RETRYING,
            SchedulingEventType.EXECUTION_RETRY_EXHAUSTED,
        }:
            raise ValueError(
                "event_type is not an execution lifecycle event"
            )

        return SchedulingEvent(
            event_type=event_type,
            job_id=job_id,
            task_name=task_name,
            execution_id=execution_id,
            message=message,
            data=data or {},
        )

    @staticmethod
    def scheduler_event(
        event_type: SchedulingEventType,
        *,
        message: str | None = None,
        data: Mapping[str, Any] | None = None,
    ) -> SchedulingEvent:
        """Create an event associated with scheduler state."""

        if event_type not in {
            SchedulingEventType.SCHEDULER_STARTED,
            SchedulingEventType.SCHEDULER_PAUSED,
            SchedulingEventType.SCHEDULER_RESUMED,
            SchedulingEventType.SCHEDULER_STOPPED,
            SchedulingEventType.RESTORATION_COMPLETED,
            SchedulingEventType.RESTORATION_FAILED,
        }:
            raise ValueError(
                "event_type is not a scheduler lifecycle event"
            )

        return SchedulingEvent(
            event_type=event_type,
            message=message,
            data=data or {},
        )
