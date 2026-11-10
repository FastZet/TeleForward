"""Scheduled notification dispatch task for TeleForward."""

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

NotificationDispatchOperation = Callable[
    [ScheduledTaskContext],
    Awaitable[Mapping[str, Any]],
]


class NotificationDispatchScheduledTask(BaseScheduledTask):
    """Dispatch pending notifications periodically."""

    def __init__(
        self,
        dispatch_operation: NotificationDispatchOperation,
    ) -> None:
        if not callable(dispatch_operation):
            raise TypeError(
                "dispatch_operation must be callable"
            )

        self._dispatch_operation = dispatch_operation

    @property
    def name(self) -> str:
        """Return the registered task name."""

        return "notification_dispatch"

    async def execute(
        self,
        context: ScheduledTaskContext,
    ) -> ScheduledTaskResult:
        """Execute the configured notification dispatch operation."""

        self.validate_context(context)
        started_at = datetime.now(timezone.utc)

        try:
            result = await self._dispatch_operation(context)

            if not isinstance(result, Mapping):
                raise TypeError(
                    "Dispatch operation must return a mapping"
                )

            if result.get("success") is not True:
                raise RuntimeError(
                    str(
                        result.get(
                            "error",
                            "Notification dispatch did not report success",
                        )
                    )
                )

            finished_at = datetime.now(timezone.utc)

            metadata: dict[str, Any] = {
                "notifications_processed": result.get(
                    "notifications_processed", 0
                ),
                "notifications_sent": result.get(
                    "notifications_sent", 0
                ),
                "notifications_failed": result.get(
                    "notifications_failed", 0
                ),
                "notifications_skipped": result.get(
                    "notifications_skipped", 0
                ),
                "warnings": result.get("warnings", []),
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
                message="Notification dispatch completed",
                metadata=metadata,
            )

        except Exception as exc:
            finished_at = datetime.now(timezone.utc)

            logger.exception(
                "Notification dispatch failed: execution_id=%s",
                context.execution_id,
            )

            return self.failed_result(
                context,
                error=str(exc),
                started_at=started_at,
                finished_at=finished_at,
            )
