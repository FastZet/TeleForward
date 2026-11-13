
"""Health diagnostics for the scheduler runtime lifespan."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from fastapi import FastAPI

from app.services.scheduling.scheduler_lifecycle import (
    SchedulerLifecycleState,
)
from app.services.scheduling.scheduler_runtime_integration import (
    SchedulerRuntimeIntegrationError,
    get_scheduler_runtime,
)

logger = logging.getLogger(__name__)


class SchedulerLifespanHealthStatus(StrEnum):
    """Health states exposed by the scheduler lifespan."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class SchedulerLifespanHealthReport:
    """Immutable scheduler lifespan health report."""

    status: SchedulerLifespanHealthStatus
    runtime_installed: bool
    lifecycle_state: str
    is_running: bool
    registered_task_count: int | None
    scheduled_job_count: int | None
    checked_at: datetime
    details: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.checked_at.tzinfo is None:
            raise ValueError("checked_at must be timezone-aware")

        if self.registered_task_count is not None:
            if self.registered_task_count < 0:
                raise ValueError(
                    "registered_task_count cannot be negative"
                )

        if self.scheduled_job_count is not None:
            if self.scheduled_job_count < 0:
                raise ValueError(
                    "scheduled_job_count cannot be negative"
                )

        object.__setattr__(
            self,
            "checked_at",
            self.checked_at.astimezone(timezone.utc),
        )

        object.__setattr__(
            self,
            "details",
            tuple(self.details),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible report."""

        result = asdict(self)
        result["status"] = self.status.value
        result["checked_at"] = self.checked_at.isoformat()
        result["details"] = list(self.details)

        return result


class SchedulerRuntimeLifespanHealthService:
    """Inspect scheduler runtime lifecycle health."""

    def __init__(
        self,
        *,
        app: FastAPI | None = None,
    ) -> None:
        if app is not None and not isinstance(app, FastAPI):
            raise TypeError("app must be a FastAPI instance or None")

        self._app = app

    @staticmethod
    def _read_lifecycle_state(runtime: Any) -> str:
        """Read the lifecycle state without assuming a string enum."""

        state = getattr(runtime, "state", None)

        if isinstance(state, SchedulerLifecycleState):
            return state.value

        if state is None:
            return "unknown"

        return str(getattr(state, "value", state))

    @staticmethod
    def _read_running_state(runtime: Any) -> bool:
        """Read the runtime running indicator."""

        running = getattr(runtime, "is_running", None)

        if isinstance(running, bool):
            return running

        return False

    @staticmethod
    def _read_task_count(runtime: Any) -> int | None:
        """Read the registered task count when available."""

        registry = getattr(runtime, "task_registry", None)

        if registry is None:
            return None

        names_method = getattr(registry, "names", None)

        if callable(names_method):
            names = names_method()

            if isinstance(names, (list, tuple, set, frozenset)):
                return len(names)

        get_all_method = getattr(registry, "get_all", None)

        if callable(get_all_method):
            tasks = get_all_method()

            if isinstance(tasks, (list, tuple, set, frozenset)):
                return len(tasks)

        return None

    @staticmethod
    def _read_job_count(runtime: Any) -> int | None:
        """Read the scheduler job count when available."""

        manager = getattr(runtime, "manager", None)

        if manager is None:
            return None

        scheduler = getattr(manager, "scheduler", None)

        if scheduler is None:
            return None

        get_jobs = getattr(scheduler, "get_jobs", None)

        if not callable(get_jobs):
            return None

        jobs = get_jobs()

        if isinstance(jobs, (list, tuple, set, frozenset)):
            return len(jobs)

        return None

    @staticmethod
    def _determine_status(
        *,
        lifecycle_state: str,
        is_running: bool,
        details: list[str],
    ) -> SchedulerLifespanHealthStatus:
        """Determine the overall scheduler health status."""

        if lifecycle_state == SchedulerLifecycleState.FAILED.value:
            return SchedulerLifespanHealthStatus.FAILED

        if lifecycle_state == SchedulerLifecycleState.RUNNING.value:
            if is_running:
                return SchedulerLifespanHealthStatus.HEALTHY

            details.append(
                "Lifecycle reports RUNNING but runtime is not running"
            )

            return SchedulerLifespanHealthStatus.DEGRADED

        if lifecycle_state in {
            SchedulerLifecycleState.STARTING.value,
            SchedulerLifecycleState.STOPPING.value,
        }:
            return SchedulerLifespanHealthStatus.DEGRADED

        if lifecycle_state == SchedulerLifecycleState.STOPPED.value:
            details.append("Scheduler runtime is stopped")

            return SchedulerLifespanHealthStatus.UNAVAILABLE

        details.append("Scheduler lifecycle state is unknown")

        return SchedulerLifespanHealthStatus.DEGRADED

    def inspect(
        self,
        app: FastAPI | None = None,
    ) -> SchedulerLifespanHealthReport:
        """Inspect the scheduler runtime and return a health report."""

        target_app = app or self._app

        if not isinstance(target_app, FastAPI):
            raise TypeError(
                "A FastAPI application must be supplied"
            )

        checked_at = datetime.now(timezone.utc)

        try:
            runtime = get_scheduler_runtime(target_app)

        except SchedulerRuntimeIntegrationError:
            return SchedulerLifespanHealthReport(
                status=SchedulerLifespanHealthStatus.UNAVAILABLE,
                runtime_installed=False,
                lifecycle_state="not_installed",
                is_running=False,
                registered_task_count=None,
                scheduled_job_count=None,
                checked_at=checked_at,
                details=("Scheduler runtime is not installed",),
            )

        details: list[str] = []

        try:
            lifecycle_state = self._read_lifecycle_state(runtime)
            is_running = self._read_running_state(runtime)
            task_count = self._read_task_count(runtime)
            job_count = self._read_job_count(runtime)

        except Exception:
            logger.exception(
                "Failed to inspect scheduler runtime health"
            )

            return SchedulerLifespanHealthReport(
                status=SchedulerLifespanHealthStatus.DEGRADED,
                runtime_installed=True,
                lifecycle_state="inspection_error",
                is_running=False,
                registered_task_count=None,
                scheduled_job_count=None,
                checked_at=checked_at,
                details=("Scheduler runtime inspection failed",),
            )

        status = self._determine_status(
            lifecycle_state=lifecycle_state,
            is_running=is_running,
            details=details,
        )

        return SchedulerLifespanHealthReport(
            status=status,
            runtime_installed=True,
            lifecycle_state=lifecycle_state,
            is_running=is_running,
            registered_task_count=task_count,
            scheduled_job_count=job_count,
            checked_at=checked_at,
            details=tuple(details),
        )

    def is_healthy(
        self,
        app: FastAPI | None = None,
    ) -> bool:
        """Return True only when the scheduler is fully healthy."""

        return (
            self.inspect(app).status
            == SchedulerLifespanHealthStatus.HEALTHY
        )

    def get_status(
        self,
        app: FastAPI | None = None,
    ) -> dict[str, Any]:
        """Return a dictionary representation of scheduler health."""

        return self.inspect(app).to_dict()
