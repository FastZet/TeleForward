"""Scheduled backup task for TeleForward."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime, timezone
from typing import Any

from app.services.scheduling.base import (
    BaseScheduledTask,
    ScheduledTaskContext,
    ScheduledTaskResult,
    ScheduledTaskStatus,
)

logger = logging.getLogger(__name__)

BackupOperation = Callable[
    [ScheduledTaskContext],
    Awaitable[Mapping[str, Any]],
]


class BackupScheduledTask(BaseScheduledTask):
    """Execute a configured asynchronous backup operation."""

    def __init__(
        self,
        backup_operation: BackupOperation,
    ) -> None:
        if not callable(backup_operation):
            raise TypeError(
                "backup_operation must be callable"
            )

        self._backup_operation = backup_operation

    @property
    def name(self) -> str:
        """Return the registered task name."""

        return "scheduled_backup"

    async def execute(
        self,
        context: ScheduledTaskContext,
    ) -> ScheduledTaskResult:
        """Create a backup and report its outcome."""

        self.validate_context(context)
        started_at = datetime.now(timezone.utc)

        try:
            backup_result = await self._backup_operation(context)

            if not isinstance(backup_result, Mapping):
                raise TypeError(
                    "Backup operation must return a mapping"
                )

            if backup_result.get("success") is not True:
                raise RuntimeError(
                    str(
                        backup_result.get(
                            "error",
                            "Backup operation did not report success",
                        )
                    )
                )

            finished_at = datetime.now(timezone.utc)

            metadata: dict[str, Any] = {
                "backup_id": backup_result.get("backup_id"),
                "backup_size_bytes": backup_result.get(
                    "size_bytes"
                ),
                "backup_format": backup_result.get("format"),
                "backup_location": backup_result.get("location"),
            }

            return ScheduledTaskResult(
                execution_id=context.execution_id,
                task_name=self.name,
                status=ScheduledTaskStatus.COMPLETED,
                started_at=started_at,
                finished_at=finished_at,
                duration_seconds=(
                    finished_at - started_at
                ).total_seconds(),
                message="Scheduled backup completed successfully",
                metadata=metadata,
            )

        except Exception as exc:
            finished_at = datetime.now(timezone.utc)

            logger.exception(
                "Scheduled backup failed: execution_id=%s",
                context.execution_id,
            )

            return self.failed_result(
                context,
                error=str(exc),
                started_at=started_at,
                finished_at=finished_at,
            )
