"""Health diagnostics for TeleForward scheduling."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Any

from app.services.scheduling.manager import SchedulingManager
from app.services.scheduling.monitor import SchedulerMonitor
from app.services.scheduling.scheduler import SchedulerService


class SchedulerHealthStatus(StrEnum):
    """Overall scheduler health states."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    STOPPED = "stopped"


@dataclass(frozen=True, slots=True)
class SchedulerHealthCheck:
    """Result of an individual scheduling health check."""

    name: str
    healthy: bool
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SchedulerHealthReport:
    """Structured health report for the scheduling subsystem."""

    status: SchedulerHealthStatus
    checked_at: datetime
    checks: tuple[SchedulerHealthCheck, ...]
    total_jobs: int
    enabled_jobs: int
    registered_tasks: int
    recent_failure_count: int
    recent_failure_rate: float

    @property
    def healthy(self) -> bool:
        """Return whether the subsystem is fully healthy."""

        return self.status == SchedulerHealthStatus.HEALTHY

    @property
    def degraded(self) -> bool:
        """Return whether the subsystem has degraded operation."""

        return self.status == SchedulerHealthStatus.DEGRADED


class SchedulerHealthService:
    """Inspect the operational health of scheduling components."""

    def __init__(
        self,
        *,
        scheduler: SchedulerService,
        manager: SchedulingManager,
        monitor: SchedulerMonitor,
        failure_window: timedelta = timedelta(hours=24),
        degraded_failure_rate: float = 10.0,
        unhealthy_failure_rate: float = 50.0,
    ) -> None:
        if not isinstance(scheduler, SchedulerService):
            raise TypeError(
                "scheduler must be a SchedulerService"
            )

        if not isinstance(manager, SchedulingManager):
            raise TypeError(
                "manager must be a SchedulingManager"
            )

        if not isinstance(monitor, SchedulerMonitor):
            raise TypeError(
                "monitor must be a SchedulerMonitor"
            )

        if (
            not isinstance(failure_window, timedelta)
            or failure_window.total_seconds() <= 0
        ):
            raise ValueError(
                "failure_window must be a positive timedelta"
            )

        if not (
            0 <= degraded_failure_rate <= 100
            and 0 <= unhealthy_failure_rate <= 100
        ):
            raise ValueError(
                "Failure-rate thresholds must be between 0 and 100"
            )

        if degraded_failure_rate > unhealthy_failure_rate:
            raise ValueError(
                "degraded_failure_rate cannot exceed "
                "unhealthy_failure_rate"
            )

        self._scheduler = scheduler
        self._manager = manager
        self._monitor = monitor
        self._failure_window = failure_window
        self._degraded_failure_rate = degraded_failure_rate
        self._unhealthy_failure_rate = unhealthy_failure_rate

    async def check_health(self) -> SchedulerHealthReport:
        """Run scheduling health checks and build a report."""

        checked_at = datetime.now(timezone.utc)
        checks: list[SchedulerHealthCheck] = []

        definitions = await self._manager.list_jobs()
        enabled_definitions = [
            definition
            for definition in definitions
            if definition.enabled
        ]

        registered_tasks = self._scheduler.registered_tasks
        scheduled_jobs = self._scheduler.get_jobs()

        checks.append(
            SchedulerHealthCheck(
                name="scheduler_running",
                healthy=self._scheduler.is_running,
                message=(
                    "Scheduler is running"
                    if self._scheduler.is_running
                    else "Scheduler is not running"
                ),
            )
        )

        checks.append(
            SchedulerHealthCheck(
                name="job_restoration",
                healthy=self._manager.is_initialised,
                message=(
                    "Stored jobs have been restored"
                    if self._manager.is_initialised
                    else "Stored jobs have not been restored successfully"
                ),
            )
        )

        missing_tasks = sorted(
            {
                definition.task_name
                for definition in enabled_definitions
                if definition.task_name not in registered_tasks
            }
        )

        checks.append(
            SchedulerHealthCheck(
                name="task_registration",
                healthy=not missing_tasks,
                message=(
                    "All enabled jobs reference registered tasks"
                    if not missing_tasks
                    else "Some enabled jobs reference missing tasks"
                ),
                details={"missing_tasks": missing_tasks},
            )
        )

        scheduled_job_ids = {
            job.id for job in scheduled_jobs
        }

        missing_jobs = sorted(
            definition.job_id
            for definition in enabled_definitions
            if definition.job_id not in scheduled_job_ids
        )

        checks.append(
            SchedulerHealthCheck(
                name="job_registration",
                healthy=not missing_jobs,
                message=(
                    "All enabled definitions have active scheduler jobs"
                    if not missing_jobs
                    else "Some enabled jobs are absent from APScheduler"
                ),
                details={"missing_job_ids": missing_jobs},
            )
        )

        failure_count = self._monitor.get_failure_count(
            since=checked_at - self._failure_window,
        )

        failure_rate = self._monitor.get_failure_rate(
            window=self._failure_window,
        )

        if failure_rate >= self._unhealthy_failure_rate:
            failure_healthy = False
            failure_message = (
                "Execution failure rate exceeds the unhealthy threshold"
            )
        elif failure_rate >= self._degraded_failure_rate:
            failure_healthy = False
            failure_message = (
                "Execution failure rate exceeds the degraded threshold"
            )
        else:
            failure_healthy = True
            failure_message = (
                "Execution failure rate is within acceptable limits"
            )

        checks.append(
            SchedulerHealthCheck(
                name="execution_failures",
                healthy=failure_healthy,
                message=failure_message,
                details={
                    "failure_count": failure_count,
                    "failure_rate_percent": failure_rate,
                    "window_seconds": self._failure_window.total_seconds(),
                    "degraded_threshold_percent": (
                        self._degraded_failure_rate
                    ),
                    "unhealthy_threshold_percent": (
                        self._unhealthy_failure_rate
                    ),
                },
            )
        )

        status = self._determine_status(
            checks=checks,
            scheduler_running=self._scheduler.is_running,
            failure_rate=failure_rate,
        )

        return SchedulerHealthReport(
            status=status,
            checked_at=checked_at,
            checks=tuple(checks),
            total_jobs=len(definitions),
            enabled_jobs=len(enabled_definitions),
            registered_tasks=len(registered_tasks),
            recent_failure_count=failure_count,
            recent_failure_rate=failure_rate,
        )

    def _determine_status(
        self,
        *,
        checks: list[SchedulerHealthCheck],
        scheduler_running: bool,
        failure_rate: float,
    ) -> SchedulerHealthStatus:
        """Determine the overall health state."""

        if not scheduler_running:
            return SchedulerHealthStatus.STOPPED

        failed_checks = [
            check for check in checks if not check.healthy
        ]

        if not failed_checks:
            return SchedulerHealthStatus.HEALTHY

        if any(
            check.name in {
                "job_restoration",
                "task_registration",
                "job_registration",
            }
            for check in failed_checks
        ):
            return SchedulerHealthStatus.UNHEALTHY

        if failure_rate >= self._unhealthy_failure_rate:
            return SchedulerHealthStatus.UNHEALTHY

        return SchedulerHealthStatus.DEGRADED
