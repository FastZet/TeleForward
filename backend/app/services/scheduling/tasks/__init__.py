"""Scheduled task implementations for TeleForward.

Task classes are loaded lazily to minimise import side effects and
reduce the risk of circular dependencies during application startup.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.services.scheduling.tasks.backup import (
        BackupScheduledTask,
    )
    from app.services.scheduling.tasks.cleanup import (
        CleanupScheduledTask,
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


_EXPORTS: dict[str, tuple[str, str]] = {
    "BackupScheduledTask": (
        ".backup",
        "BackupScheduledTask",
    ),
    "CleanupScheduledTask": (
        ".cleanup",
        "CleanupScheduledTask",
    ),
    "HealthCheckScheduledTask": (
        ".health_check",
        "HealthCheckScheduledTask",
    ),
    "NotificationDispatchScheduledTask": (
        ".notification_dispatch",
        "NotificationDispatchScheduledTask",
    ),
    "SessionMaintenanceScheduledTask": (
        ".session_maintenance",
        "SessionMaintenanceScheduledTask",
    ),
    "TelegramSyncScheduledTask": (
        ".telegram_sync",
        "TelegramSyncScheduledTask",
    ),
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> Any:
    """Resolve an exported task class when it is first accessed."""

    export = _EXPORTS.get(name)

    if export is None:
        raise AttributeError(
            f"module {__name__!r} has no attribute {name!r}"
        )

    module_name, attribute_name = export
    module = import_module(module_name, package=__name__)
    value = getattr(module, attribute_name)

    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """Include lazy exports in module introspection."""

    return sorted(set(globals()) | set(__all__))
