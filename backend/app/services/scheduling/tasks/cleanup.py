"""Scheduled cleanup task for TeleForward."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.services.scheduling.base import (
    BaseScheduledTask,
    ScheduledTaskContext,
    ScheduledTaskResult,
    ScheduledTaskStatus,
)
from app.services.scheduling.cleanup import (
    SchedulingCleanupService,
)

logger = logging.getLogger(__name__)


class CleanupScheduledTask(BaseScheduledTask):
    """Execute periodic scheduling-data maintenance."""

    def __init__(
        self,
        cleanup_service: SchedulingCleanupService,
    ) -> None:
        if not isinstance(
            cleanup_service,
            SchedulingCleanupService,
        ):
            raise TypeError(
                "cleanup_service must be a SchedulingCleanupService"
            )

        self._cleanup_service = cleanup_service

    @property
    def name(self) -> str:
        """Return the registered task name."""

        return "scheduling_cleanup"

    async def execute(
        self,
        context: ScheduledTaskContext,
    ) -> ScheduledTaskResult:
        """Run scheduling cleanup and return an execution result."""

        started_at = datetime.now(timezone.utc)

        self.validate_context(context)

        try:
            cleanup_result = await self._cleanup_service.run()

            finished_at = datetime.now(timezone.utc)

            metadata: dict[str, Any] = {
                "deleted_history_records": (
                    cleanup_result.deleted_history_records
                ),
                "recovered_stale_executions": (
                    cleanup_result.recovered_stale_executions
                ),
                "failed_recoveries": (
                    cleanup_result.failed_recoveries
                ),
                "cleanup_duration_seconds": (
                    cleanup_result.duration_seconds
                ),
            }

            if cleanup_result.failed_recoveries:
                return ScheduledTaskResult(
                    execution_id=context.execution_id,
                    task_name=self.name,
                    status=ScheduledTaskStatus.FAILED,
                    started_at=started_at,
                    finished_at=finished_at,
                    duration_seconds=(
                        finished_at - started_at
                    ).total_seconds(),
                    message=(
                        "Cleanup completed with recovery failures"
                    ),
                    metadata=metadata,
                )

            return ScheduledTaskResult(
                execution_id=context.execution_id,
                task_name=self.name,
                status=ScheduledTaskStatus.COMPLETED,
                started_at=started_at,
                finished_at=finished_at,
                duration_seconds=(
                    finished_at - started_at
                ).total_seconds(),
                message="Scheduling cleanup completed successfully",
                metadata=metadata,
            )

        except Exception as exc:
            finished_at = datetime.now(timezone.utc)

            logger.exception(
                "Scheduled cleanup task failed: execution_id=%s",
                context.execution_id,
            )

            return self.failed_result(
                context,
                error=str(exc),
                started_at=started_at,
                finished_at=finished_at,
            )
