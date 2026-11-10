"""Persistent execution history for TeleForward scheduling."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Callable, Mapping

from sqlalchemy import DateTime, Float, Index, JSON, String, delete, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.services.scheduling.serialization import to_json_compatible

logger = logging.getLogger(__name__)


class ExecutionHistoryStatus(StrEnum):
    """Possible scheduled execution outcomes."""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True, slots=True)
class ExecutionHistoryEntry:
    """Domain representation of a scheduled task execution."""

    execution_id: str
    job_id: str
    task_name: str
    status: ExecutionHistoryStatus
    started_at: datetime
    finished_at: datetime | None = None
    duration_seconds: float | None = None
    error: str | None = None
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("execution_id", "job_id", "task_name"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} cannot be empty")

        if not isinstance(self.status, ExecutionHistoryStatus):
            raise TypeError(
                "status must be an ExecutionHistoryStatus"
            )

        self._validate_datetime("started_at", self.started_at)

        if self.finished_at is not None:
            self._validate_datetime("finished_at", self.finished_at)

            if self.finished_at < self.started_at:
                raise ValueError(
                    "finished_at cannot precede started_at"
                )

        if self.duration_seconds is not None:
            if (
                isinstance(self.duration_seconds, bool)
                or not isinstance(self.duration_seconds, (int, float))
                or self.duration_seconds < 0
            ):
                raise ValueError(
                    "duration_seconds must be non-negative"
                )

        if self.error is not None and not isinstance(self.error, str):
            raise TypeError("error must be a string or None")

        if not isinstance(self.details, Mapping):
            raise TypeError("details must be a mapping")

        object.__setattr__(self, "details", dict(self.details))

    @staticmethod
    def _validate_datetime(name: str, value: datetime) -> None:
        if (
            not isinstance(value, datetime)
            or value.tzinfo is None
            or value.utcoffset() is None
        ):
            raise ValueError(f"{name} must be timezone-aware")


class ScheduledExecutionRecord(Base):
    """Database model for scheduled execution history."""

    __tablename__ = "scheduled_execution_history"

    __table_args__ = (
        Index(
            "ix_scheduled_execution_job_started",
            "job_id",
            "started_at",
        ),
        Index(
            "ix_scheduled_execution_status_started",
            "status",
            "started_at",
        ),
    )

    execution_id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
    )

    job_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        index=True,
    )

    task_name: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    duration_seconds: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    error: Mapped[str | None] = mapped_column(
        String(4000),
        nullable=True,
    )

    details: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )


class ExecutionHistoryError(RuntimeError):
    """Raised when execution history operations fail."""


class ExecutionHistoryRepository:
    """Store and retrieve scheduled execution history."""

    def __init__(
        self,
        session_factory: Callable[[], AsyncSession],
    ) -> None:
        if not callable(session_factory):
            raise TypeError("session_factory must be callable")

        self._session_factory = session_factory

    async def record(
        self,
        entry: ExecutionHistoryEntry,
    ) -> None:
        """Insert a new execution history entry."""

        if not isinstance(entry, ExecutionHistoryEntry):
            raise TypeError(
                "entry must be an ExecutionHistoryEntry"
            )

        try:
            async with self._session_factory() as session:
                async with session.begin():
                    existing = await session.get(
                        ScheduledExecutionRecord,
                        entry.execution_id,
                    )

                    if existing is not None:
                        raise ValueError(
                            "Execution history entry already exists: "
                            f"{entry.execution_id}"
                        )

                    session.add(self._to_record(entry))

        except SQLAlchemyError as exc:
            logger.exception(
                "Failed to record execution %s",
                entry.execution_id,
            )
            raise ExecutionHistoryError(
                f"Could not record execution {entry.execution_id}"
            ) from exc

    async def update(
        self,
        entry: ExecutionHistoryEntry,
    ) -> bool:
        """Update an existing execution history entry.

        Returns False when the execution does not exist.
        """

        if not isinstance(entry, ExecutionHistoryEntry):
            raise TypeError(
                "entry must be an ExecutionHistoryEntry"
            )

        try:
            async with self._session_factory() as session:
                async with session.begin():
                    record = await session.get(
                        ScheduledExecutionRecord,
                        entry.execution_id,
                    )

                    if record is None:
                        return False

                    self._apply_entry(record, entry)

                return True

        except SQLAlchemyError as exc:
            logger.exception(
                "Failed to update execution %s",
                entry.execution_id,
            )
            raise ExecutionHistoryError(
                f"Could not update execution {entry.execution_id}"
            ) from exc

    async def get(
        self,
        execution_id: str,
    ) -> ExecutionHistoryEntry | None:
        """Retrieve an execution history entry by ID."""

        self._validate_identifier(execution_id, "execution_id")

        try:
            async with self._session_factory() as session:
                record = await session.get(
                    ScheduledExecutionRecord,
                    execution_id,
                )

                return (
                    self._to_entry(record)
                    if record is not None
                    else None
                )

        except SQLAlchemyError as exc:
            logger.exception(
                "Failed to retrieve execution %s",
                execution_id,
            )
            raise ExecutionHistoryError(
                f"Could not retrieve execution {execution_id}"
            ) from exc

    async def list_history(
        self,
        *,
        job_id: str | None = None,
        status: ExecutionHistoryStatus | None = None,
        started_after: datetime | None = None,
        started_before: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ExecutionHistoryEntry]:
        """Retrieve execution history with optional filters."""

        if job_id is not None:
            self._validate_identifier(job_id, "job_id")

        if status is not None and not isinstance(
            status,
            ExecutionHistoryStatus,
        ):
            raise TypeError(
                "status must be an ExecutionHistoryStatus or None"
            )

        for name, value in (
            ("started_after", started_after),
            ("started_before", started_before),
        ):
            if value is not None:
                ExecutionHistoryEntry._validate_datetime(name, value)

        if (
            started_after is not None
            and started_before is not None
            and started_after > started_before
        ):
            raise ValueError(
                "started_after cannot be later than started_before"
            )

        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 1000
        ):
            raise ValueError("limit must be between 1 and 1000")

        if (
            isinstance(offset, bool)
            or not isinstance(offset, int)
            or offset < 0
        ):
            raise ValueError("offset must be non-negative")

        statement = select(ScheduledExecutionRecord)

        if job_id is not None:
            statement = statement.where(
                ScheduledExecutionRecord.job_id == job_id
            )

        if status is not None:
            statement = statement.where(
                ScheduledExecutionRecord.status == status.value
            )

        if started_after is not None:
            statement = statement.where(
                ScheduledExecutionRecord.started_at >= started_after
            )

        if started_before is not None:
            statement = statement.where(
                ScheduledExecutionRecord.started_at <= started_before
            )

        statement = (
            statement
            .order_by(
                ScheduledExecutionRecord.started_at.desc(),
                ScheduledExecutionRecord.execution_id.desc(),
            )
            .offset(offset)
            .limit(limit)
        )

        try:
            async with self._session_factory() as session:
                result = await session.scalars(statement)

                return [
                    self._to_entry(record)
                    for record in result.all()
                ]

        except SQLAlchemyError as exc:
            logger.exception("Failed to list execution history")
            raise ExecutionHistoryError(
                "Could not list execution history"
            ) from exc

    async def delete_before(
        self,
        cutoff: datetime,
    ) -> int:
        """Delete history entries older than a timestamp."""

        ExecutionHistoryEntry._validate_datetime(
            "cutoff",
            cutoff,
        )

        try:
            async with self._session_factory() as session:
                async with session.begin():
                    statement = delete(
                        ScheduledExecutionRecord
                    ).where(
                        ScheduledExecutionRecord.started_at < cutoff
                    )

                    result = await session.execute(statement)

                    return int(result.rowcount or 0)

        except SQLAlchemyError as exc:
            logger.exception(
                "Failed to prune execution history"
            )
            raise ExecutionHistoryError(
                "Could not prune execution history"
            ) from exc

    @staticmethod
    def _to_record(
        entry: ExecutionHistoryEntry,
    ) -> ScheduledExecutionRecord:
        """Convert a domain entry into a database record."""

        details = to_json_compatible(dict(entry.details))

        if not isinstance(details, dict):
            raise TypeError("Execution details must serialize to a dictionary")

        return ScheduledExecutionRecord(
            execution_id=entry.execution_id,
            job_id=entry.job_id,
            task_name=entry.task_name,
            status=entry.status.value,
            started_at=entry.started_at,
            finished_at=entry.finished_at,
            duration_seconds=entry.duration_seconds,
            error=entry.error,
            details=details,
        )

    @staticmethod
    def _apply_entry(
        record: ScheduledExecutionRecord,
        entry: ExecutionHistoryEntry,
    ) -> None:
        """Copy domain entry fields to an existing database record."""

        replacement = ExecutionHistoryRepository._to_record(entry)

        record.job_id = replacement.job_id
        record.task_name = replacement.task_name
        record.status = replacement.status
        record.started_at = replacement.started_at
        record.finished_at = replacement.finished_at
        record.duration_seconds = replacement.duration_seconds
        record.error = replacement.error
        record.details = replacement.details

    @staticmethod
    def _to_entry(
        record: ScheduledExecutionRecord,
    ) -> ExecutionHistoryEntry:
        """Convert a database record into a domain entry."""

        started_at = record.started_at
        finished_at = record.finished_at

        # SQLite may return naive datetimes for timezone-aware columns.
        # Normalise these values as UTC because writes are expected to
        # use timezone-aware timestamps.
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)

        if finished_at is not None and finished_at.tzinfo is None:
            finished_at = finished_at.replace(tzinfo=timezone.utc)

        try:
            return ExecutionHistoryEntry(
                execution_id=record.execution_id,
                job_id=record.job_id,
                task_name=record.task_name,
                status=ExecutionHistoryStatus(record.status),
                started_at=started_at,
                finished_at=finished_at,
                duration_seconds=record.duration_seconds,
                error=record.error,
                details=dict(record.details or {}),
            )

        except (TypeError, ValueError) as exc:
            raise ExecutionHistoryError(
                "Invalid persisted execution history record: "
                f"{record.execution_id}"
            ) from exc

    @staticmethod
    def _validate_identifier(
        value: str,
        name: str,
    ) -> None:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} cannot be empty")
