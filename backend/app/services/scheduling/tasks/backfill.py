"""Scheduled Telegram message backfill task."""

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

BackfillOperation = Callable[
    [ScheduledTaskContext],
    Awaitable[Mapping[str, Any]],
]


class BackfillScheduledTask(BaseScheduledTask):
    """Process historical Telegram messages periodically."""

    def __init__(
        self,
        backfill_operation: BackfillOperation,
    ) -> None:
        if not callable(backfill_operation):
            raise TypeError(
                "backfill_operation must be callable"
            )

        self._backfill_operation = backfill_operation

    @property
    def name(self) -> str:
        """Return the registered task name."""

        return "telegram_backfill"

    @staticmethod
    def _count(
        result: Mapping[str, Any],
        key: str,
    ) -> int:
        """Validate and return a non-negative counter."""

        value = result.get(key, 0)

        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(
                f"Backfill result field {key!r} must be an integer"
            )

        if value < 0:
            raise ValueError(
                f"Backfill result field {key!r} cannot be negative"
            )

        return value

    async def execute(
        self,
        context: ScheduledTaskContext,
    ) -> ScheduledTaskResult:
        """Execute the configured historical-message backfill."""

        self.validate_context(context)
        started_at = datetime.now(timezone.utc)

        try:
            result = await self._backfill_operation(context)

            if not isinstance(result, Mapping):
                raise TypeError(
                    "Backfill operation must return a mapping"
                )

            if result.get("success") is not True:
                raise RuntimeError(
                    str(
                        result.get(
                            "error",
                            "Backfill operation did not report success",
                        )
                    )
                )

            processed = self._count(result, "messages_processed")
            forwarded = self._count(result, "messages_forwarded")
            skipped = self._count(result, "messages_skipped")
            failed = self._count(result, "messages_failed")

            if forwarded + skipped + failed > processed:
                raise ValueError(
                    "Backfill outcome counts exceed messages_processed"
                )

            finished_at = datetime.now(timezone.utc)

            metadata: dict[str, Any] = {
                "messages_processed": processed,
                "messages_forwarded": forwarded,
                "messages_skipped": skipped,
                "messages_failed": failed,
                "batches_processed": self._count(
                    result,
                    "batches_processed",
                ),
                "has_more": result.get("has_more", False),
                "warnings": result.get("warnings", []),
            }

            if not isinstance(metadata["has_more"], bool):
                raise TypeError(
                    "Backfill result field 'has_more' must be a boolean"
                )

            status = (
                ScheduledTaskStatus.FAILED
                if failed > 0
                else ScheduledTaskStatus.COMPLETED
            )

            message = (
                "Backfill completed with message failures"
                if failed > 0
                else "Historical message backfill completed"
            )

            return ScheduledTaskResult(
                execution_id=context.execution_id,
                task_name=self.name,
                status=status,
                started_at=started_at,
                finished_at=finished_at,
                duration_seconds=(
                    finished_at - started_at
                ).total_seconds(),
                message=message,
                metadata=metadata,
            )

        except Exception as exc:
            finished_at = datetime.now(timezone.utc)

            logger.exception(
                "Telegram backfill failed: execution_id=%s",
                context.execution_id,
            )

            return self.failed_result(
                context,
                error=str(exc),
                started_at=started_at,
                finished_at=finished_at,
            )
