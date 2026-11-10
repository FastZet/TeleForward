"""Factory for constructing TeleForward scheduled tasks."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from app.services.scheduling.cleanup import (
    SchedulingCleanupService,
)
from app.services.scheduling.tasks.backfill import (
    BackfillScheduledTask,
)
from app.services.scheduling.tasks.backup import (
    BackupScheduledTask,
)
from app.services.scheduling.tasks.cleanup import (
    CleanupScheduledTask,
)
from app.services.scheduling.tasks.forwarding import (
    ForwardingScheduledTask,
)
from app.services.scheduling.tasks.health_check import (
    HealthCheckScheduledTask,
)
from app.services.scheduling.tasks.notification_dispatch import (
    NotificationDispatchScheduledTask,
)
from app.services.scheduling.tasks.session_maintenance import (
    SessionMaintenanceScheduledTask,
)
from app.services.scheduling.tasks.telegram_sync import (
    TelegramSyncScheduledTask,
)
from app.services.scheduling.tasks.task_registry import (
    ScheduledTaskRegistry,
)

from app.services.scheduling.base import BaseScheduledTask


class ScheduledTaskFactory:
    """Construct and register scheduled task instances."""

    def __init__(
        self,
        cleanup_service: SchedulingCleanupService,
        *,
        backup_operation: Callable[..., Awaitable[Mapping[str, Any]]],
        session_maintenance_operation: Callable[
            ..., Awaitable[Mapping[str, Any]]
        ],
        telegram_sync_operation: Callable[
            ..., Awaitable[Mapping[str, Any]]
        ],
        notification_dispatch_operation: Callable[
            ..., Awaitable[Mapping[str, Any]]
        ],
        forwarding_operation: Callable[
            ..., Awaitable[Mapping[str, Any]]
        ],
        backfill_operation: Callable[
            ..., Awaitable[Mapping[str, Any]]
        ],
        health_checks: Mapping[
            str,
            Callable[[], Awaitable[Mapping[str, Any]]],
        ],
    ) -> None:
        self._cleanup_service = cleanup_service
        self._backup_operation = backup_operation
        self._session_maintenance_operation = (
            session_maintenance_operation
        )
        self._telegram_sync_operation = telegram_sync_operation
        self._notification_dispatch_operation = (
            notification_dispatch_operation
        )
        self._forwarding_operation = forwarding_operation
        self._backfill_operation = backfill_operation
        self._health_checks = dict(health_checks)

        self._validate_dependencies()

    def _validate_dependencies(self) -> None:
        """Validate all injected task dependencies."""

        if not isinstance(
            self._cleanup_service,
            SchedulingCleanupService,
        ):
            raise TypeError(
                "cleanup_service must be a SchedulingCleanupService"
            )

        operations = {
            "backup_operation": self._backup_operation,
            "session_maintenance_operation": (
                self._session_maintenance_operation
            ),
            "telegram_sync_operation": self._telegram_sync_operation,
            "notification_dispatch_operation": (
                self._notification_dispatch_operation
            ),
            "forwarding_operation": self._forwarding_operation,
            "backfill_operation": self._backfill_operation,
        }

        for name, operation in operations.items():
            if not callable(operation):
                raise TypeError(f"{name} must be callable")

        if not self._health_checks:
            raise ValueError(
                "At least one health check must be configured"
            )

    def build(self) -> tuple[BaseScheduledTask, ...]:
        """Construct all configured scheduled task instances."""

        return (
            CleanupScheduledTask(self._cleanup_service),
            HealthCheckScheduledTask(self._health_checks),
            BackupScheduledTask(self._backup_operation),
            SessionMaintenanceScheduledTask(
                self._session_maintenance_operation
            ),
            TelegramSyncScheduledTask(
                self._telegram_sync_operation
            ),
            NotificationDispatchScheduledTask(
                self._notification_dispatch_operation
            ),
            ForwardingScheduledTask(self._forwarding_operation),
            BackfillScheduledTask(self._backfill_operation),
        )

    def register(
        self,
        registry: ScheduledTaskRegistry,
        *,
        replace: bool = False,
    ) -> tuple[BaseScheduledTask, ...]:
        """Build and register all scheduled tasks."""

        if not isinstance(registry, ScheduledTaskRegistry):
            raise TypeError(
                "registry must be a ScheduledTaskRegistry"
            )

        tasks = self.build()
        registry.register_many(tasks, replace=replace)

        return tasks
