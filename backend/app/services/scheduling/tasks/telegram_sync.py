"""Scheduled Telegram synchronisation task."""

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

TelegramSyncOperation = Callable[
    [ScheduledTaskContext],
    Awaitable[Mapping[str, Any]],
]


class TelegramSyncScheduledTask(BaseScheduledTask):
    """Run periodic Telegram account and chat synchronisation."""

    def __init__(
        self,
        sync_operation: TelegramSyncOperation,
    ) -> None:
        if not callable(sync_operation):
            raise TypeError("sync_operation must be callable")

        self._sync_operation = sync_operation

    @property
    def name(self) -> str:
        """Return the registered task name."""

        return "telegram_sync"

    async def execute(
        self,
        context: ScheduledTaskContext,
    ) -> ScheduledTaskResult:
        """Execute the configured Telegram synchronisation."""

        self.validate_context(context)
        started_at = datetime.now(timezone.utc)

        try:
            result = await self._sync_operation(context)

            if not isinstance(result, Mapping):
                raise TypeError(
                    "Sync operation must return a mapping"
                )

            if result.get("success") is not True:
                raise RuntimeError(
                    str(
                        result.get(
                            "error",
                            "Telegram synchronisation did not report success",
                        )
                    )
                )

            finished_at = datetime.now(timezone.utc)

            metadata: dict[str, Any] = {
                "accounts_processed": result.get(
                    "accounts_processed", 0
                ),
                "chats_synchronised": result.get(
                    "chats_synchronised", 0
                ),
                "messages_processed": result.get(
                    "messages_processed", 0
                ),
                "messages_created": result.get(
                    "messages_created", 0
                ),
                "messages_updated": result.get(
                    "messages_updated", 0
                ),
                "messages_deleted": result.get(
                    "messages_deleted", 0
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
                message="Telegram synchronisation completed",
                metadata=metadata,
            )

        except Exception as exc:
            finished_at = datetime.now(timezone.utc)

            logger.exception(
                "Telegram synchronisation failed: execution_id=%s",
                context.execution_id,
            )

            return self.failed_result(
                context,
                error=str(exc),
                started_at=started_at,
                finished_at=finished_at,
            )
