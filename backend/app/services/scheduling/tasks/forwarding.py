"""Scheduled message forwarding task for TeleForward."""

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

ForwardingOperation = Callable[
    [ScheduledTaskContext],
    Awaitable[Mapping[str, Any]],
]


class ForwardingScheduledTask(BaseScheduledTask):
    """Execute pending forwarding work on a schedule."""

    def __init__(
        self,
        forwarding_operation: ForwardingOperation,
    ) -> None:
        if not callable(forwarding_operation):
            raise TypeError(
                "forwarding_operation must be callable"
            )

        self._forwarding_operation = forwarding_operation

    @property
    def name(self) -> str:
        """Return the registered task name."""

        return "scheduled_forwarding"

    @staticmethod
    def _count(
        result: Mapping[str, Any],
        key: str,
    ) -> int:
        """Read and validate a non-negative result counter."""

        value = result.get(key, 0)

        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(
                f"Forwarding result field {key!r} must be an integer"
            )

        if value < 0:
            raise ValueError(
                f"Forwarding result field {key!r} cannot be negative"
            )

        return value

    async def execute(
        self,
        context: ScheduledTaskContext,
    ) -> ScheduledTaskResult:
        """Process pending forwarding work."""

        self.validate_context(context)
        started_at = datetime.now(timezone.utc)

        try:
            result = await self._forwarding_operation(context)

            if not isinstance(result, Mapping):
                raise TypeError(
                    "Forwarding operation must return a mapping"
                )

            if result.get("success") is not True:
                raise RuntimeError(
                    str(
                        result.get(
                            "error",
                            "Forwarding operation did not report success",
                        )
                    )
                )

            processed = self._count(result, "messages_processed")
            forwarded = self._count(result, "messages_forwarded")
            skipped = self._count(result, "messages_skipped")
            failed = self._count(result, "messages_failed")

            if forwarded + skipped + failed > processed:
                raise ValueError(
                    "Forwarding result counts exceed messages_processed"
                )

            finished_at = datetime.now(timezone.utc)

            metadata: dict[str, Any] = {
                "messages_processed": processed,
                "messages_forwarded": forwarded,
                "messages_skipped": skipped,
                "messages_failed": failed,
                "rules_processed": self._count(
                    result,
                    "rules_processed",
                ),
                "warnings": result.get("warnings", []),
            }

            status = (
                ScheduledTaskStatus.FAILED
                if failed > 0
                else ScheduledTaskStatus.COMPLETED
            )

            message = (
                "Forwarding completed with message failures"
                if failed > 0
                else "Scheduled forwarding completed successfully"
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
                "Scheduled forwarding failed: execution_id=%s",
                context.execution_id,
            )

            return ScheduledTaskResult(
                execution_id=context.execution_id,
                task_name=self.name,
                status=ScheduledTaskStatus.FAILED,
                started_at=started_at,
                finished_at=finished_at,
                duration_seconds=(
                    finished_at - started_at
                ).total_seconds(),
                message="Scheduled forwarding failed",
                error=str(exc),
            )
