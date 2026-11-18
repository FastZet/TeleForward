"""Factory for constructing TeleForward scheduled tasks."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from app.services.scheduling.cleanup import (
    SchedulingCleanupService,
)
from app.services.scheduling.history import ExecutionHistoryRepository
from app.services.scheduling.history_tracking import (
    HistoryTrackingScheduledTask,
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
        backup_operation: Callable[..., Awaitable[Mapping[str, Any]]] | None,
        session_maintenance_operation: Callable[
            ..., Awaitable[Mapping[str, Any]]
        ] | None,
        telegram_sync_operation: Callable[
            ..., Awaitable[Mapping[str, Any]]
        ] | None,
        notification_dispatch_operation: Callable[
            ..., Awaitable[Mapping[str, Any]]
        ] | None,
        forwarding_operation: Callable[
            ..., Awaitable[Mapping[str, Any]]
        ] | None,
        backfill_operation: Callable[
            ..., Awaitable[Mapping[str, Any]]
        ] | None,
        health_checks: Mapping[
            str,
            Callable[[], Awaitable[Mapping[str, Any]]],
        ],
        history_repository: ExecutionHistoryRepository | None = None,
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
        self._history_repository = history_repository

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
            if operation is not None and not callable(operation):
                raise TypeError(f"{name} must be callable or None")

        if not self._health_checks:
            raise ValueError(
                "At least one health check must be configured"
            )

        if (
            self._history_repository is not None
            and not isinstance(
                self._history_repository,
                ExecutionHistoryRepository,
            )
        ):
            raise TypeError(
                "history_repository must be an "
                "ExecutionHistoryRepository or None"
            )

    def build(self) -> tuple[BaseScheduledTask, ...]:
        """Construct all configured scheduled task instances."""

        configured_tasks: list[BaseScheduledTask] = [
            CleanupScheduledTask(self._cleanup_service),
            HealthCheckScheduledTask(self._health_checks),
        ]

        if self._backup_operation is not None:
            configured_tasks.append(
                BackupScheduledTask(self._backup_operation)
            )
        if self._session_maintenance_operation is not None:
            configured_tasks.append(
                SessionMaintenanceScheduledTask(
                    self._session_maintenance_operation
                )
            )
        if self._telegram_sync_operation is not None:
            configured_tasks.append(
                TelegramSyncScheduledTask(
                    self._telegram_sync_operation
                )
            )
        if self._notification_dispatch_operation is not None:
            configured_tasks.append(
                NotificationDispatchScheduledTask(
                    self._notification_dispatch_operation
                )
            )
        if self._forwarding_operation is not None:
            configured_tasks.append(
                ForwardingScheduledTask(self._forwarding_operation)
            )
        if self._backfill_operation is not None:
            configured_tasks.append(
                BackfillScheduledTask(self._backfill_operation)
            )

        tasks = tuple(configured_tasks)

        if self._history_repository is None:
            return tasks

        return tuple(
            HistoryTrackingScheduledTask(task, self._history_repository)
            for task in tasks
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
