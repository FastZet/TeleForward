"""Operational metrics for TeleForward scheduling."""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Mapping


class ExecutionMetricStatus(StrEnum):
    """Execution outcomes tracked by the metrics collector."""

    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True, slots=True)
class TaskMetricsSnapshot:
    """Metrics for an individual scheduled task."""

    task_name: str
    total_executions: int
    completed_executions: int
    failed_executions: int
    skipped_executions: int
    total_duration_seconds: float
    average_duration_seconds: float
    minimum_duration_seconds: float
    maximum_duration_seconds: float
    last_execution_at: datetime | None
    last_failure_at: datetime | None

    @property
    def failure_rate_percent(self) -> float:
        """Return the percentage of executions that failed."""

        if self.total_executions == 0:
            return 0.0

        return (
            self.failed_executions
            / self.total_executions
        ) * 100.0


@dataclass(frozen=True, slots=True)
class SchedulingMetricsSnapshot:
    """Immutable snapshot of scheduling metrics."""

    collected_at: datetime
    total_executions: int
    completed_executions: int
    failed_executions: int
    skipped_executions: int
    total_duration_seconds: float
    average_duration_seconds: float
    minimum_duration_seconds: float
    maximum_duration_seconds: float
    last_execution_at: datetime | None
    last_failure_at: datetime | None
    tasks: Mapping[str, TaskMetricsSnapshot]

    @property
    def failure_rate_percent(self) -> float:
        """Return the overall execution failure percentage."""

        if self.total_executions == 0:
            return 0.0

        return (
            self.failed_executions
            / self.total_executions
        ) * 100.0


@dataclass(slots=True)
class _TaskMetrics:
    """Mutable internal metrics for one task."""

    total: int = 0
    completed: int = 0
    failed: int = 0
    skipped: int = 0
    total_duration: float = 0.0
    minimum_duration: float = math.inf
    maximum_duration: float = 0.0
    last_execution_at: datetime | None = None
    last_failure_at: datetime | None = None


class SchedulingMetricsCollector:
    """Thread-safe in-memory scheduling metrics collector.

    Metrics are cumulative until reset. They are not persisted and
    are lost when the application process restarts.
    """

    def __init__(
        self,
        *,
        max_tracked_tasks: int = 1000,
    ) -> None:
        if (
            isinstance(max_tracked_tasks, bool)
            or not isinstance(max_tracked_tasks, int)
            or max_tracked_tasks < 1
        ):
            raise ValueError(
                "max_tracked_tasks must be a positive integer"
            )

        self._max_tracked_tasks = max_tracked_tasks
        self._lock = threading.RLock()

        self._tasks: dict[str, _TaskMetrics] = {}

        self._total = 0
        self._completed = 0
        self._failed = 0
        self._skipped = 0

        self._total_duration = 0.0
        self._minimum_duration = math.inf
        self._maximum_duration = 0.0

        self._last_execution_at: datetime | None = None
        self._last_failure_at: datetime | None = None

    def record_execution(
        self,
        *,
        task_name: str,
        status: ExecutionMetricStatus,
        duration_seconds: float,
        occurred_at: datetime | None = None,
    ) -> None:
        """Record the outcome and duration of an execution."""

        if not isinstance(task_name, str) or not task_name.strip():
            raise ValueError("task_name cannot be empty")

        if not isinstance(status, ExecutionMetricStatus):
            raise TypeError(
                "status must be an ExecutionMetricStatus"
            )

        if (
            isinstance(duration_seconds, bool)
            or not isinstance(duration_seconds, (int, float))
            or not math.isfinite(duration_seconds)
            or duration_seconds < 0
        ):
            raise ValueError(
                "duration_seconds must be a finite non-negative number"
            )

        timestamp = occurred_at or datetime.now(timezone.utc)

        self._validate_timestamp(timestamp)

        duration = float(duration_seconds)

        with self._lock:
            task_metrics = self._get_or_create_task(task_name)

            self._total += 1
            task_metrics.total += 1

            self._total_duration += duration
            task_metrics.total_duration += duration

            self._minimum_duration = min(
                self._minimum_duration,
                duration,
            )
            self._maximum_duration = max(
                self._maximum_duration,
                duration,
            )

            task_metrics.minimum_duration = min(
                task_metrics.minimum_duration,
                duration,
            )
            task_metrics.maximum_duration = max(
                task_metrics.maximum_duration,
                duration,
            )

            if status == ExecutionMetricStatus.COMPLETED:
                self._completed += 1
                task_metrics.completed += 1

            elif status == ExecutionMetricStatus.FAILED:
                self._failed += 1
                task_metrics.failed += 1
                self._last_failure_at = timestamp
                task_metrics.last_failure_at = timestamp

            elif status == ExecutionMetricStatus.SKIPPED:
                self._skipped += 1
                task_metrics.skipped += 1

            self._last_execution_at = timestamp
            task_metrics.last_execution_at = timestamp

    def snapshot(self) -> SchedulingMetricsSnapshot:
        """Return a consistent snapshot of all collected metrics."""

        with self._lock:
            tasks = {
                name: self._build_task_snapshot(name, metrics)
                for name, metrics in self._tasks.items()
            }

            average_duration = (
                self._total_duration / self._total
                if self._total
                else 0.0
            )

            return SchedulingMetricsSnapshot(
                collected_at=datetime.now(timezone.utc),
                total_executions=self._total,
                completed_executions=self._completed,
                failed_executions=self._failed,
                skipped_executions=self._skipped,
                total_duration_seconds=self._total_duration,
                average_duration_seconds=average_duration,
                minimum_duration_seconds=(
                    self._minimum_duration
                    if self._total
                    else 0.0
                ),
                maximum_duration_seconds=self._maximum_duration,
                last_execution_at=self._last_execution_at,
                last_failure_at=self._last_failure_at,
                tasks=tasks,
            )

    def get_task_metrics(
        self,
        task_name: str,
    ) -> TaskMetricsSnapshot | None:
        """Return metrics for a specific task."""

        if not isinstance(task_name, str) or not task_name.strip():
            raise ValueError("task_name cannot be empty")

        with self._lock:
            metrics = self._tasks.get(task_name)

            if metrics is None:
                return None

            return self._build_task_snapshot(
                task_name,
                metrics,
            )

    def reset(self) -> None:
        """Reset all collected metrics."""

        with self._lock:
            self._tasks.clear()

            self._total = 0
            self._completed = 0
            self._failed = 0
            self._skipped = 0

            self._total_duration = 0.0
            self._minimum_duration = math.inf
            self._maximum_duration = 0.0

            self._last_execution_at = None
            self._last_failure_at = None

    def _get_or_create_task(
        self,
        task_name: str,
    ) -> _TaskMetrics:
        """Get an existing task metric or create a new one."""

        metrics = self._tasks.get(task_name)

        if metrics is not None:
            return metrics

        if len(self._tasks) >= self._max_tracked_tasks:
            raise RuntimeError(
                "Maximum tracked task count reached; "
                "metrics were not recorded"
            )

        metrics = _TaskMetrics()
        self._tasks[task_name] = metrics

        return metrics

    @staticmethod
    def _build_task_snapshot(
        task_name: str,
        metrics: _TaskMetrics,
    ) -> TaskMetricsSnapshot:
        """Convert mutable task metrics into an immutable snapshot."""

        average = (
            metrics.total_duration / metrics.total
            if metrics.total
            else 0.0
        )

        return TaskMetricsSnapshot(
            task_name=task_name,
            total_executions=metrics.total,
            completed_executions=metrics.completed,
            failed_executions=metrics.failed,
            skipped_executions=metrics.skipped,
            total_duration_seconds=metrics.total_duration,
            average_duration_seconds=average,
            minimum_duration_seconds=(
                metrics.minimum_duration
                if metrics.total
                else 0.0
            ),
            maximum_duration_seconds=metrics.maximum_duration,
            last_execution_at=metrics.last_execution_at,
            last_failure_at=metrics.last_failure_at,
        )

    @staticmethod
    def _validate_timestamp(value: datetime) -> None:
        if (
            not isinstance(value, datetime)
            or value.tzinfo is None
            or value.utcoffset() is None
        ):
            raise ValueError(
                "occurred_at must be timezone-aware"
            )
