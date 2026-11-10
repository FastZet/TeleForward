"""Scheduled health-check task for TeleForward."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Mapping

from app.services.scheduling.base import (
    BaseScheduledTask,
    ScheduledTaskContext,
    ScheduledTaskResult,
    ScheduledTaskStatus,
)

logger = logging.getLogger(__name__)

HealthCheck = Callable[[], Awaitable[Mapping[str, Any]]]


class HealthCheckScheduledTask(BaseScheduledTask):
    """Run registered asynchronous health checks."""

    def __init__(
        self,
        checks: Mapping[str, HealthCheck],
    ) -> None:
        if not isinstance(checks, Mapping):
            raise TypeError("checks must be a mapping")

        validated_checks: dict[str, HealthCheck] = {}

        for name, check in checks.items():
            if not isinstance(name, str) or not name.strip():
                raise ValueError(
                    "Health-check names cannot be empty"
                )

            if not callable(check):
                raise TypeError(
                    f"Health check {name!r} must be callable"
                )

            validated_checks[name] = check

        if not validated_checks:
            raise ValueError(
                "At least one health check must be registered"
            )

        self._checks = validated_checks

    @property
    def name(self) -> str:
        """Return the registered task name."""

        return "scheduling_health_check"

    async def execute(
        self,
        context: ScheduledTaskContext,
    ) -> ScheduledTaskResult:
        """Execute all configured health checks."""

        self.validate_context(context)

        started_at = datetime.now(timezone.utc)
        results: dict[str, Any] = {}
        failures: list[str] = []

        for name, check in self._checks.items():
            try:
                result = await check()

                if not isinstance(result, Mapping):
                    raise TypeError(
                        "Health check must return a mapping"
                    )

                status = result.get("status")

                if status not in ("healthy", "degraded"):
                    failures.append(name)

                results[name] = dict(result)

            except Exception as exc:
                logger.exception(
                    "Health check %s failed",
                    name,
                )

                failures.append(name)
                results[name] = {
                    "status": "unhealthy",
                    "error": str(exc),
                }

        finished_at = datetime.now(timezone.utc)

        metadata = {
            "checks": results,
            "total_checks": len(self._checks),
            "successful_checks": (
                len(self._checks) - len(failures)
            ),
            "failed_checks": len(failures),
            "failed_check_names": failures,
        }

        if failures:
            return ScheduledTaskResult(
                execution_id=context.execution_id,
                task_name=self.name,
                status=ScheduledTaskStatus.FAILED,
                started_at=started_at,
                finished_at=finished_at,
                duration_seconds=(
                    finished_at - started_at
                ).total_seconds(),
                message="One or more health checks failed",
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
            message="All health checks passed",
            metadata=metadata,
        )
