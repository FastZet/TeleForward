"""Controlled execution of scheduled tasks for TeleForward."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from app.services.scheduling.base import (
    BaseScheduledTask,
    ScheduledTaskContext,
    ScheduledTaskResult,
    ScheduledTaskStatus,
)

logger = logging.getLogger(__name__)


class ScheduledTaskExecutor:
    """Execute scheduled tasks with concurrency and timeout controls."""

    def __init__(
        self,
        *,
        max_concurrent_tasks: int = 10,
        default_timeout_seconds: float = 300.0,
    ) -> None:
        if (
            isinstance(max_concurrent_tasks, bool)
            or not isinstance(max_concurrent_tasks, int)
            or max_concurrent_tasks < 1
        ):
            raise ValueError(
                "max_concurrent_tasks must be a positive integer"
            )

        if (
            isinstance(default_timeout_seconds, bool)
            or not isinstance(default_timeout_seconds, (int, float))
            or default_timeout_seconds <= 0
        ):
            raise ValueError(
                "default_timeout_seconds must be positive"
            )

        self._semaphore = asyncio.Semaphore(max_concurrent_tasks)
        self._default_timeout = float(default_timeout_seconds)

    async def execute(
        self,
        task: BaseScheduledTask,
        context: ScheduledTaskContext,
        *,
        timeout_seconds: float | None = None,
    ) -> ScheduledTaskResult:
        """Execute one scheduled task.

        The concurrency limit applies to active task executions. Waiting
        executions remain pending until a semaphore slot becomes available.
        """

        if not isinstance(task, BaseScheduledTask):
            raise TypeError("task must inherit from BaseScheduledTask")

        if not isinstance(context, ScheduledTaskContext):
            raise TypeError(
                "context must be a ScheduledTaskContext"
            )

        timeout = self._resolve_timeout(timeout_seconds)

        async with self._semaphore:
            started_at = datetime.now(timezone.utc)

            execution_context = ScheduledTaskContext(
                job_id=context.job_id,
                execution_id=context.execution_id,
                scheduled_at=context.scheduled_at,
                started_at=started_at,
                metadata=context.metadata,
            )

            if not task.enabled:
                return task.skipped_result(
                    execution_context,
                    reason="Task is disabled",
                )

            try:
                result = await asyncio.wait_for(
                    task.execute(execution_context),
                    timeout=timeout,
                )

                self._validate_result(
                    result,
                    task=task,
                    context=execution_context,
                )

                logger.info(
                    "Scheduled task executed: task=%s job=%s "
                    "execution=%s status=%s duration=%.3fs",
                    task.name,
                    context.job_id,
                    context.execution_id,
                    result.status.value,
                    result.duration_seconds,
                )

                return result

            except asyncio.TimeoutError:
                message = (
                    f"Task exceeded its execution timeout "
                    f"of {timeout:.2f} seconds"
                )

                logger.error(
                    "Scheduled task timed out: task=%s job=%s "
                    "execution=%s timeout=%.2fs",
                    task.name,
                    context.job_id,
                    context.execution_id,
                    timeout,
                )

                return task.failed_result(
                    execution_context,
                    error=message,
                )

            except asyncio.CancelledError:
                logger.warning(
                    "Scheduled task execution cancelled: "
                    "task=%s job=%s execution=%s",
                    task.name,
                    context.job_id,
                    context.execution_id,
                )
                raise

            except Exception as exc:
                logger.exception(
                    "Scheduled task execution failed: "
                    "task=%s job=%s execution=%s",
                    task.name,
                    context.job_id,
                    context.execution_id,
                )

                return task.failed_result(
                    execution_context,
                    error=f"{type(exc).__name__}: {exc}",
                )

    async def execute_many(
        self,
        tasks: list[
            tuple[BaseScheduledTask, ScheduledTaskContext]
        ],
        *,
        timeout_seconds: float | None = None,
    ) -> list[ScheduledTaskResult]:
        """Execute multiple task/context pairs.

        Results retain the same order as the supplied task list.
        Individual task failures are represented in their results.
        """

        if not isinstance(tasks, list):
            raise TypeError("tasks must be a list")

        executions = [
            self.execute(
                task,
                context,
                timeout_seconds=timeout_seconds,
            )
            for task, context in tasks
        ]

        return await asyncio.gather(*executions)

    @staticmethod
    def _validate_result(
        result: ScheduledTaskResult,
        *,
        task: BaseScheduledTask,
        context: ScheduledTaskContext,
    ) -> None:
        """Ensure a task returned a result for the current execution."""

        if not isinstance(result, ScheduledTaskResult):
            raise TypeError(
                "Scheduled task must return ScheduledTaskResult"
            )

        if result.job_id != context.job_id:
            raise ValueError(
                "Task result job_id does not match execution context"
            )

        if result.execution_id != context.execution_id:
            raise ValueError(
                "Task result execution_id does not match execution context"
            )

        if result.task_name != task.name:
            raise ValueError(
                "Task result task_name does not match registered task"
            )

        if result.status == ScheduledTaskStatus.FAILED and not result.error:
            raise ValueError(
                "Failed task result must include an error"
            )

    def _resolve_timeout(
        self,
        timeout_seconds: float | None,
    ) -> float:
        """Resolve and validate an execution timeout."""

        if timeout_seconds is None:
            return self._default_timeout

        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or timeout_seconds <= 0
        ):
            raise ValueError(
                "timeout_seconds must be a positive number"
            )

        return float(timeout_seconds)
