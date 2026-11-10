"""Monitoring and execution statistics for TeleForward scheduling."""

from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import RLock

from app.services.scheduling.base import (
    ScheduledTaskResult,
    ScheduledTaskStatus,
)


@dataclass(frozen=True, slots=True)
class SchedulerStatistics:
    """Snapshot of scheduler execution statistics."""

    total_executions: int
    completed: int
    failed: int
    skipped: int
    success_rate: float
    failure_rate: float
    last_execution_at: datetime | None
    last_success_at: datetime | None
    last_failure_at: datetime | None

    @property
    def unsuccessful(self) -> int:
        """Return the number of executions that did not complete."""

        return self.failed + self.skipped


@dataclass(frozen=True, slots=True)
class TaskStatistics:
    """Execution statistics for one task implementation."""

    task_name: str
    total_executions: int
    completed: int
    failed: int
    skipped: int
    average_duration_seconds: float
    last_execution_at: datetime | None
    last_failure_at: datetime | None


class SchedulerMonitor:
    """Collect and expose scheduler execution metrics.

    Metrics are maintained in memory. This monitor is intended for
    application monitoring and dashboard summaries, not durable auditing.
    """

    def __init__(
        self,
        *,
        history_size: int = 5000,
    ) -> None:
        if (
            isinstance(history_size, bool)
            or not isinstance(history_size, int)
            or history_size < 1
        ):
            raise ValueError("history_size must be a positive integer")

        self._history: deque[ScheduledTaskResult] = deque(
            maxlen=history_size
        )
        self._totals: Counter[str] = Counter()
        self._task_totals: dict[str, Counter[str]] = {}
        self._duration_totals: Counter[str] = Counter()
        self._last_execution_at: datetime | None = None
        self._last_success_at: datetime | None = None
        self._last_failure_at: datetime | None = None
        self._lock = RLock()

    @property
    def history(self) -> tuple[ScheduledTaskResult, ...]:
        """Return the retained execution history."""

        with self._lock:
            return tuple(self._history)

    def record(self, result: ScheduledTaskResult) -> None:
        """Record one completed task execution."""

        if not isinstance(result, ScheduledTaskResult):
            raise TypeError(
                "result must be a ScheduledTaskResult"
            )

        status = result.status.value

        with self._lock:
            self._history.append(result)

            self._totals["total"] += 1
            self._totals[status] += 1

            task_counter = self._task_totals.setdefault(
                result.task_name,
                Counter(),
            )
            task_counter["total"] += 1
            task_counter[status] += 1

            self._duration_totals[result.task_name] += (
                result.duration_seconds
            )

            if (
                self._last_execution_at is None
                or result.finished_at > self._last_execution_at
            ):
                self._last_execution_at = result.finished_at

            if result.status == ScheduledTaskStatus.COMPLETED:
                if (
                    self._last_success_at is None
                    or result.finished_at > self._last_success_at
                ):
                    self._last_success_at = result.finished_at

            elif result.status == ScheduledTaskStatus.FAILED:
                if (
                    self._last_failure_at is None
                    or result.finished_at > self._last_failure_at
                ):
                    self._last_failure_at = result.finished_at

    def get_statistics(self) -> SchedulerStatistics:
        """Return aggregate execution statistics."""

        with self._lock:
            total = self._totals["total"]
            completed = self._totals[ScheduledTaskStatus.COMPLETED.value]
            failed = self._totals[ScheduledTaskStatus.FAILED.value]
            skipped = self._totals[ScheduledTaskStatus.SKIPPED.value]

            success_rate = (
                completed / total * 100.0 if total else 0.0
            )
            failure_rate = (
                failed / total * 100.0 if total else 0.0
            )

            return SchedulerStatistics(
                total_executions=total,
                completed=completed,
                failed=failed,
                skipped=skipped,
                success_rate=round(success_rate, 2),
                failure_rate=round(failure_rate, 2),
                last_execution_at=self._last_execution_at,
                last_success_at=self._last_success_at,
                last_failure_at=self._last_failure_at,
            )

    def get_task_statistics(
        self,
        task_name: str,
    ) -> TaskStatistics | None:
        """Return statistics for a specific task."""

        if not isinstance(task_name, str) or not task_name.strip():
            raise ValueError("task_name cannot be empty")

        with self._lock:
            counter = self._task_totals.get(task_name)

            if counter is None:
                return None

            total = counter["total"]

            task_results = [
                result
                for result in self._history
                if result.task_name == task_name
            ]

            last_execution = max(
                (result.finished_at for result in task_results),
                default=None,
            )

            last_failure = max(
                (
                    result.finished_at
                    for result in task_results
                    if result.status == ScheduledTaskStatus.FAILED
                ),
                default=None,
            )

            return TaskStatistics(
                task_name=task_name,
                total_executions=total,
                completed=counter[ScheduledTaskStatus.COMPLETED.value],
                failed=counter[ScheduledTaskStatus.FAILED.value],
                skipped=counter[ScheduledTaskStatus.SKIPPED.value],
                average_duration_seconds=(
                    self._duration_totals[task_name] / total
                ),
                last_execution_at=last_execution,
                last_failure_at=last_failure,
            )

    def get_recent_results(
        self,
        *,
        limit: int = 100,
        task_name: str | None = None,
        status: ScheduledTaskStatus | None = None,
    ) -> list[ScheduledTaskResult]:
        """Retrieve recent execution results with optional filters."""

        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or limit < 1
        ):
            raise ValueError("limit must be a positive integer")

        if task_name is not None and (
            not isinstance(task_name, str) or not task_name.strip()
        ):
            raise ValueError("task_name cannot be empty")

        if status is not None and not isinstance(
            status,
            ScheduledTaskStatus,
        ):
            raise TypeError(
                "status must be a ScheduledTaskStatus"
            )

        with self._lock:
            results = reversed(self._history)

            filtered = [
                result
                for result in results
                if (
                    task_name is None
                    or result.task_name == task_name
                )
                and (
                    status is None
                    or result.status == status
                )
            ]

            return filtered[:limit]

    def get_failure_count(
        self,
        *,
        since: datetime | None = None,
        task_name: str | None = None,
    ) -> int:
        """Count retained failures since a specified time."""

        if since is not None:
            if (
                not isinstance(since, datetime)
                or since.tzinfo is None
                or since.utcoffset() is None
            ):
                raise ValueError(
                    "since must be a timezone-aware datetime"
                )

        if task_name is not None and (
            not isinstance(task_name, str) or not task_name.strip()
        ):
            raise ValueError("task_name cannot be empty")

        with self._lock:
            return sum(
                1
                for result in self._history
                if result.status == ScheduledTaskStatus.FAILED
                and (
                    since is None
                    or result.finished_at >= since
                )
                and (
                    task_name is None
                    or result.task_name == task_name
                )
            )

    def get_failure_rate(
        self,
        *,
        window: timedelta = timedelta(hours=24),
        task_name: str | None = None,
    ) -> float:
        """Calculate the failure percentage within a time window."""

        if not isinstance(window, timedelta) or window.total_seconds() <= 0:
            raise ValueError("window must be a positive timedelta")

        if task_name is not None and (
            not isinstance(task_name, str) or not task_name.strip()
        ):
            raise ValueError("task_name cannot be empty")

        cutoff = datetime.now(timezone.utc) - window

        with self._lock:
            results = [
                result
                for result in self._history
                if result.finished_at >= cutoff
                and (
                    task_name is None
                    or result.task_name == task_name
                )
            ]

            if not results:
                return 0.0

            failed = sum(
                result.status == ScheduledTaskStatus.FAILED
                for result in results
            )

            return round(failed / len(results) * 100.0, 2)

    def reset(self) -> None:
        """Clear all in-memory monitoring data."""

        with self._lock:
            self._history.clear()
            self._totals.clear()
            self._task_totals.clear()
            self._duration_totals.clear()
            self._last_execution_at = None
            self._last_success_at = None
            self._last_failure_at = None
