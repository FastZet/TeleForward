"""Persist scheduled task results through the execution-history repository."""

from __future__ import annotations

from app.services.scheduling.base import (
    BaseScheduledTask,
    ScheduledTaskContext,
    ScheduledTaskResult,
    ScheduledTaskStatus,
)
from app.services.scheduling.history import (
    ExecutionHistoryEntry,
    ExecutionHistoryRepository,
    ExecutionHistoryStatus,
)


class HistoryTrackingScheduledTask(BaseScheduledTask):
    """Wrap a scheduled task with durable started and finished records."""

    def __init__(
        self,
        task: BaseScheduledTask,
        history_repository: ExecutionHistoryRepository,
    ) -> None:
        if not isinstance(task, BaseScheduledTask):
            raise TypeError("task must be a BaseScheduledTask")
        if not isinstance(
            history_repository,
            ExecutionHistoryRepository,
        ):
            raise TypeError(
                "history_repository must be an ExecutionHistoryRepository"
            )

        self._task = task
        self._history_repository = history_repository
        self.name = task.name
        super().__init__(enabled=task.enabled)

    async def execute(
        self,
        context: ScheduledTaskContext,
    ) -> ScheduledTaskResult:
        """Record RUNNING before work, then persist its final outcome."""
        self.validate_context(context)

        await self._history_repository.record(
            ExecutionHistoryEntry(
                execution_id=context.execution_id,
                job_id=context.job_id,
                task_name=self.name,
                status=ExecutionHistoryStatus.RUNNING,
                started_at=context.started_at,
            )
        )

        try:
            result = await self._task.execute(context)
            if not isinstance(result, ScheduledTaskResult):
                raise TypeError(
                    "Scheduled task must return ScheduledTaskResult"
                )
            if (
                result.job_id != context.job_id
                or result.execution_id != context.execution_id
                or result.task_name != self.name
            ):
                raise ValueError(
                    "Task result identifiers do not match execution context"
                )
        except Exception as exc:
            result = self.failed_result(
                context,
                error=f"{type(exc).__name__}: {exc}",
            )

        status = {
            ScheduledTaskStatus.COMPLETED: (
                ExecutionHistoryStatus.COMPLETED
            ),
            ScheduledTaskStatus.FAILED: ExecutionHistoryStatus.FAILED,
            ScheduledTaskStatus.SKIPPED: ExecutionHistoryStatus.SKIPPED,
        }[result.status]

        details = dict(result.metadata)
        if result.message is not None:
            details["message"] = result.message

        updated = await self._history_repository.update(
            ExecutionHistoryEntry(
                execution_id=result.execution_id,
                job_id=result.job_id,
                task_name=result.task_name,
                status=status,
                started_at=result.started_at,
                finished_at=result.finished_at,
                duration_seconds=result.duration_seconds,
                error=result.error,
                details=details,
            )
        )
        if not updated:
            raise RuntimeError(
                "Scheduled execution history record disappeared "
                f"during execution: {context.execution_id}"
            )

        return result
