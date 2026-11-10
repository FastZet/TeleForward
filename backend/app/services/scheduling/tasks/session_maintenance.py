"""Scheduled Telegram session maintenance task."""

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

SessionMaintenanceOperation = Callable[
    [ScheduledTaskContext],
    Awaitable[Mapping[str, Any]],
]


class SessionMaintenanceScheduledTask(BaseScheduledTask):
    """Run periodic Telegram session maintenance."""

    def __init__(
        self,
        maintenance_operation: SessionMaintenanceOperation,
    ) -> None:
        if not callable(maintenance_operation):
            raise TypeError(
                "maintenance_operation must be callable"
            )

        self._maintenance_operation = maintenance_operation

    @property
    def name(self) -> str:
        """Return the registered task name."""

        return "telegram_session_maintenance"

    async def execute(
        self,
        context: ScheduledTaskContext,
    ) -> ScheduledTaskResult:
        """Execute the configured session maintenance operation."""

        self.validate_context(context)
        started_at = datetime.now(timezone.utc)

        try:
            result = await self._maintenance_operation(context)

            if not isinstance(result, Mapping):
                raise TypeError(
                    "Maintenance operation must return a mapping"
                )

            if result.get("success") is not True:
                raise RuntimeError(
                    str(
                        result.get(
                            "error",
                            "Session maintenance did not report success",
                        )
                    )
                )

            finished_at = datetime.now(timezone.utc)

            metadata: dict[str, Any] = {
                "accounts_checked": result.get(
                    "accounts_checked", 0
                ),
                "sessions_reconnected": result.get(
                    "sessions_reconnected", 0
                ),
                "sessions_disconnected": result.get(
                    "sessions_disconnected", 0
                ),
                "sessions_requiring_reauthentication": result.get(
                    "sessions_requiring_reauthentication", 0
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
                message="Telegram session maintenance completed",
                metadata=metadata,
            )

        except Exception as exc:
            finished_at = datetime.now(timezone.utc)

            logger.exception(
                "Telegram session maintenance failed: "
                "execution_id=%s",
                context.execution_id,
            )

            return self.failed_result(
                context,
                error=str(exc),
                started_at=started_at,
                finished_at=finished_at,
            )
