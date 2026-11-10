"""APScheduler integration for TeleForward."""

from __future__ import annotations

import logging
from collections import deque
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from apscheduler.job import Job
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

from app.services.scheduling.base import (
    BaseScheduledTask,
    ScheduledTaskContext,
    ScheduledTaskResult,
    ScheduledTaskStatus,
)

logger = logging.getLogger(__name__)

_DEFAULT_RESULT_HISTORY_SIZE = 1000


class SchedulerService:
    """Manage scheduled tasks using APScheduler.

    This service owns the in-process scheduler and task registry.
    It does not provide persistent job storage or database-backed
    execution history.
    """

    def __init__(
        self,
        *,
        timezone_name: str = "UTC",
        result_history_size: int = _DEFAULT_RESULT_HISTORY_SIZE,
    ) -> None:
        if result_history_size < 1:
            raise ValueError("result_history_size must be at least 1")

        self._scheduler = AsyncIOScheduler(timezone=timezone_name)
        self._tasks: dict[str, BaseScheduledTask] = {}
        self._results: deque[ScheduledTaskResult] = deque(
            maxlen=result_history_size
        )

    @property
    def is_running(self) -> bool:
        """Return whether the scheduler is currently running."""

        return self._scheduler.running

    @property
    def registered_tasks(self) -> tuple[str, ...]:
        """Return the names of registered task implementations."""

        return tuple(sorted(self._tasks))

    @property
    def recent_results(self) -> tuple[ScheduledTaskResult, ...]:
        """Return the in-memory execution result history."""

        return tuple(self._results)

    def register_task(self, task: BaseScheduledTask) -> None:
        """Register a task implementation."""

        if not isinstance(task, BaseScheduledTask):
            raise TypeError("task must inherit from BaseScheduledTask")

        if task.name in self._tasks:
            raise ValueError(
                f"A task named '{task.name}' is already registered"
            )

        self._tasks[task.name] = task
        logger.debug("Registered scheduled task: %s", task.name)

    def unregister_task(self, task_name: str) -> None:
        """Remove a task implementation from the registry.

        Existing scheduled jobs referencing this task are removed first.
        """

        self._validate_task_name(task_name)

        if task_name not in self._tasks:
            raise KeyError(f"Unknown scheduled task: {task_name}")

        for job in self._scheduler.get_jobs():
            if (
                job.func == self._execute_task
                and job.args
                and job.args[0] == task_name
            ):
                self._scheduler.remove_job(job.id)

        del self._tasks[task_name]
        logger.debug("Unregistered scheduled task: %s", task_name)

    def add_interval_job(
        self,
        *,
        task_name: str,
        job_id: str,
        seconds: float | None = None,
        minutes: float | None = None,
        hours: float | None = None,
        days: float | None = None,
        weeks: float | None = None,
        start_date: datetime | str | None = None,
        end_date: datetime | str | None = None,
        jitter: int | None = None,
        replace_existing: bool = False,
        max_instances: int = 1,
        coalesce: bool = True,
        misfire_grace_time: int | None = 60,
    ) -> Job:
        """Schedule a task at a fixed interval."""

        self._validate_job_configuration(
            task_name=task_name,
            job_id=job_id,
            max_instances=max_instances,
            misfire_grace_time=misfire_grace_time,
        )

        interval_values = {
            "seconds": seconds,
            "minutes": minutes,
            "hours": hours,
            "days": days,
            "weeks": weeks,
        }

        if not any(
            value is not None and value > 0
            for value in interval_values.values()
        ):
            raise ValueError(
                "At least one positive interval value is required"
            )

        return self._add_job(
            task_name=task_name,
            job_id=job_id,
            trigger="interval",
            replace_existing=replace_existing,
            max_instances=max_instances,
            coalesce=coalesce,
            misfire_grace_time=misfire_grace_time,
            seconds=seconds,
            minutes=minutes,
            hours=hours,
            days=days,
            weeks=weeks,
            start_date=start_date,
            end_date=end_date,
            jitter=jitter,
        )

    def add_cron_job(
        self,
        *,
        task_name: str,
        job_id: str,
        expression: str,
        replace_existing: bool = False,
        max_instances: int = 1,
        coalesce: bool = True,
        misfire_grace_time: int | None = 60,
        jitter: int | None = None,
    ) -> Job:
        """Schedule a task using a five-field cron expression.

        The expression uses APScheduler's crontab syntax:
        minute hour day month day_of_week.
        """

        self._validate_job_configuration(
            task_name=task_name,
            job_id=job_id,
            max_instances=max_instances,
            misfire_grace_time=misfire_grace_time,
        )

        if not expression.strip():
            raise ValueError("Cron expression cannot be empty")

        trigger = CronTrigger.from_crontab(
            expression,
            timezone=self._scheduler.timezone,
        )

        return self._add_job(
            task_name=task_name,
            job_id=job_id,
            trigger=trigger,
            replace_existing=replace_existing,
            max_instances=max_instances,
            coalesce=coalesce,
            misfire_grace_time=misfire_grace_time,
            jitter=jitter,
        )

    def add_date_job(
        self,
        *,
        task_name: str,
        job_id: str,
        run_date: datetime,
        replace_existing: bool = False,
        misfire_grace_time: int | None = 60,
    ) -> Job:
        """Schedule a task to execute once at a specific time."""

        self._validate_job_configuration(
            task_name=task_name,
            job_id=job_id,
            max_instances=1,
            misfire_grace_time=misfire_grace_time,
        )

        if run_date.tzinfo is None:
            raise ValueError("run_date must be timezone-aware")

        trigger = DateTrigger(
            run_date=run_date,
            timezone=self._scheduler.timezone,
        )

        return self._add_job(
            task_name=task_name,
            job_id=job_id,
            trigger=trigger,
            replace_existing=replace_existing,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=misfire_grace_time,
        )

    def _add_job(
        self,
        *,
        task_name: str,
        job_id: str,
        trigger: Any,
        replace_existing: bool,
        max_instances: int,
        coalesce: bool,
        misfire_grace_time: int | None,
        **trigger_options: Any,
    ) -> Job:
        """Register a task execution with APScheduler."""

        return self._scheduler.add_job(
            self._execute_task,
            trigger=trigger,
            id=job_id,
            args=[task_name, job_id],
            replace_existing=replace_existing,
            max_instances=max_instances,
            coalesce=coalesce,
            misfire_grace_time=misfire_grace_time,
            **trigger_options,
        )

    async def _execute_task(
        self,
        task_name: str,
        job_id: str,
    ) -> ScheduledTaskResult:
        """Execute a registered task and record its result."""

        task = self._tasks.get(task_name)

        if task is None:
            raise RuntimeError(
                f"Scheduled task '{task_name}' is no longer registered"
            )

        execution_time = datetime.now(timezone.utc)
        context = ScheduledTaskContext(
            job_id=job_id,
            execution_id=str(uuid4()),
            scheduled_at=execution_time,
            started_at=execution_time,
        )

        if not task.enabled:
            result = task.skipped_result(
                context,
                reason="Task is disabled",
            )
            self._record_result(result)
            return result

        try:
            result = await task.execute(context)

            if not isinstance(result, ScheduledTaskResult):
                raise TypeError(
                    "Scheduled task must return ScheduledTaskResult"
                )

            if (
                result.job_id != job_id
                or result.execution_id != context.execution_id
                or result.task_name != task.name
            ):
                raise ValueError(
                    "Task result identifiers do not match execution context"
                )

            self._record_result(result)

            if result.status == ScheduledTaskStatus.FAILED:
                logger.error(
                    "Scheduled task failed: task=%s job=%s error=%s",
                    task_name,
                    job_id,
                    result.error,
                )
            else:
                logger.info(
                    "Scheduled task finished: task=%s job=%s status=%s",
                    task_name,
                    job_id,
                    result.status.value,
                )

            return result

        except Exception as exc:
            logger.exception(
                "Unhandled exception in scheduled task: task=%s job=%s",
                task_name,
                job_id,
            )

            result = task.failed_result(
                context,
                error=f"{type(exc).__name__}: {exc}",
            )
            self._record_result(result)
            return result

    def _record_result(self, result: ScheduledTaskResult) -> None:
        """Append an execution result to the bounded in-memory history."""

        self._results.append(result)

    def get_job(self, job_id: str) -> Job | None:
        """Return a scheduled job by its identifier."""

        if not job_id.strip():
            raise ValueError("job_id cannot be empty")

        return self._scheduler.get_job(job_id)

    def get_jobs(self) -> list[Job]:
        """Return all currently scheduled jobs."""

        return self._scheduler.get_jobs()

    def remove_job(self, job_id: str) -> None:
        """Remove a scheduled job."""

        if not job_id.strip():
            raise ValueError("job_id cannot be empty")

        self._scheduler.remove_job(job_id)

    def pause_job(self, job_id: str) -> Job | None:
        """Pause a scheduled job."""

        if not job_id.strip():
            raise ValueError("job_id cannot be empty")

        return self._scheduler.pause_job(job_id)

    def resume_job(self, job_id: str) -> Job | None:
        """Resume a paused scheduled job."""

        if not job_id.strip():
            raise ValueError("job_id cannot be empty")

        return self._scheduler.resume_job(job_id)

    def start(self, *, paused: bool = False) -> None:
        """Start the scheduler."""

        if self._scheduler.running:
            logger.debug("Scheduler is already running")
            return

        self._scheduler.start(paused=paused)
        logger.info("TeleForward scheduler started")

    def pause(self) -> None:
        """Pause the scheduler globally."""

        if self._scheduler.running:
            self._scheduler.pause()
            logger.info("TeleForward scheduler paused")

    def resume(self) -> None:
        """Resume the scheduler globally."""

        if self._scheduler.running:
            self._scheduler.resume()
            logger.info("TeleForward scheduler resumed")

    def shutdown(self, *, wait: bool = True) -> None:
        """Shut down the scheduler."""

        if not self._scheduler.running:
            return

        self._scheduler.shutdown(wait=wait)
        logger.info("TeleForward scheduler shut down")

    @staticmethod
    def _validate_task_name(task_name: str) -> None:
        if not isinstance(task_name, str) or not task_name.strip():
            raise ValueError("task_name cannot be empty")

    def _validate_job_configuration(
        self,
        *,
        task_name: str,
        job_id: str,
        max_instances: int,
        misfire_grace_time: int | None,
    ) -> None:
        self._validate_task_name(task_name)

        if task_name not in self._tasks:
            raise KeyError(f"Task is not registered: {task_name}")

        if not isinstance(job_id, str) or not job_id.strip():
            raise ValueError("job_id cannot be empty")

        if max_instances < 1:
            raise ValueError("max_instances must be at least 1")

        if (
            misfire_grace_time is not None
            and misfire_grace_time < 1
        ):
            raise ValueError(
                "misfire_grace_time must be positive or None"
            )
