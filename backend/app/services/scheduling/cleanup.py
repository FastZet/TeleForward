"""Maintenance and cleanup services for TeleForward scheduling."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.services.scheduling.history import (
    ExecutionHistoryEntry,
    ExecutionHistoryRepository,
    ExecutionHistoryStatus,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SchedulingCleanupPolicy:
    """Retention and recovery configuration."""

    history_retention_days: int = 90
    stale_execution_minutes: int = 30
    batch_size: int = 500

    def __post_init__(self) -> None:
        for name in (
            "history_retention_days",
            "stale_execution_minutes",
            "batch_size",
        ):
            value = getattr(self, name)

            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value <= 0
            ):
                raise ValueError(f"{name} must be a positive integer")

        if self.batch_size > 1000:
            raise ValueError("batch_size cannot exceed 1000")


@dataclass(frozen=True, slots=True)
class SchedulingCleanupResult:
    """Summary of a scheduling maintenance operation."""

    started_at: datetime
    finished_at: datetime
    deleted_history_records: int
    recovered_stale_executions: int
    failed_recoveries: int

    @property
    def duration_seconds(self) -> float:
        """Return the maintenance execution duration."""

        return (
            self.finished_at - self.started_at
        ).total_seconds()


class SchedulingCleanupService:
    """Perform scheduling history maintenance and recovery."""

    def __init__(
        self,
        *,
        history_repository: ExecutionHistoryRepository,
        policy: SchedulingCleanupPolicy | None = None,
    ) -> None:
        if not isinstance(
            history_repository,
            ExecutionHistoryRepository,
        ):
            raise TypeError(
                "history_repository must be an "
                "ExecutionHistoryRepository"
            )

        self._history = history_repository
        self._policy = policy or SchedulingCleanupPolicy()

    async def run(self) -> SchedulingCleanupResult:
        """Run all configured cleanup operations."""

        started_at = datetime.now(timezone.utc)

        recovered, failed = await self.recover_stale_executions(
            reference_time=started_at,
        )

        deleted = await self.prune_execution_history(
            reference_time=started_at,
        )

        finished_at = datetime.now(timezone.utc)

        result = SchedulingCleanupResult(
            started_at=started_at,
            finished_at=finished_at,
            deleted_history_records=deleted,
            recovered_stale_executions=recovered,
            failed_recoveries=failed,
        )

        logger.info(
            "Scheduling cleanup completed: deleted=%d recovered=%d "
            "failed_recoveries=%d duration=%.3fs",
            result.deleted_history_records,
            result.recovered_stale_executions,
            result.failed_recoveries,
            result.duration_seconds,
        )

        return result

    async def prune_execution_history(
        self,
        *,
        reference_time: datetime | None = None,
    ) -> int:
        """Delete execution history older than the retention period."""

        now = reference_time or datetime.now(timezone.utc)
        self._validate_datetime(now)

        cutoff = now - timedelta(
            days=self._policy.history_retention_days,
        )

        deleted = await self._history.delete_before(cutoff)

        logger.info(
            "Pruned %d scheduling history records older than %s",
            deleted,
            cutoff.isoformat(),
        )

        return deleted

    async def recover_stale_executions(
        self,
        *,
        reference_time: datetime | None = None,
    ) -> tuple[int, int]:
        """Mark abandoned running executions as failed.

        Returns:
            A tuple containing:
            - Number of successfully recovered records.
            - Number of records whose recovery failed.
        """

        now = reference_time or datetime.now(timezone.utc)
        self._validate_datetime(now)

        stale_before = now - timedelta(
            minutes=self._policy.stale_execution_minutes,
        )

        recovered = 0
        failed = 0
        offset = 0

        while True:
            entries = await self._history.list_history(
                status=ExecutionHistoryStatus.RUNNING,
                started_before=stale_before,
                limit=self._policy.batch_size,
                offset=offset,
            )

            if not entries:
                break

            for entry in entries:
                try:
                    updated = await self._mark_failed(
                        entry,
                        now=now,
                    )

                    if updated:
                        recovered += 1

                except Exception:
                    failed += 1

                    logger.exception(
                        "Could not recover stale execution %s",
                        entry.execution_id,
                    )

            # Successfully updated records no longer match RUNNING.
            # Failed records remain in the result set, so advancing
            # the offset prevents repeatedly processing them.
            offset += len(entries)

            if len(entries) < self._policy.batch_size:
                break

        logger.info(
            "Stale execution recovery completed: recovered=%d failed=%d",
            recovered,
            failed,
        )

        return recovered, failed

    async def _mark_failed(
        self,
        entry: ExecutionHistoryEntry,
        *,
        now: datetime,
    ) -> bool:
        """Convert an abandoned execution into a failed record."""

        if entry.status != ExecutionHistoryStatus.RUNNING:
            return False

        duration = max(
            0.0,
            (now - entry.started_at).total_seconds(),
        )

        details = dict(entry.details)
        details["recovery"] = {
            "reason": "execution_timeout_or_process_restart",
            "recovered_at": now.isoformat(),
        }

        recovered_entry = ExecutionHistoryEntry(
            execution_id=entry.execution_id,
            job_id=entry.job_id,
            task_name=entry.task_name,
            status=ExecutionHistoryStatus.FAILED,
            started_at=entry.started_at,
            finished_at=now,
            duration_seconds=duration,
            error=(
                "Execution was left running beyond the configured "
                "stale-execution threshold"
            ),
            details=details,
        )

        return await self._history.update(recovered_entry)

    @staticmethod
    def _validate_datetime(value: datetime) -> None:
        if (
            not isinstance(value, datetime)
            or value.tzinfo is None
            or value.utcoffset() is None
        ):
            raise ValueError(
                "reference_time must be timezone-aware"
            )
