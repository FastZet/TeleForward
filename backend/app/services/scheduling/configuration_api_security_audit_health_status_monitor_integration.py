
"""FastAPI integration for the security-audit health-status monitor."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI

from app.services.scheduling.configuration_api_security_audit_health_status_monitor import (
    HealthCheckCallback,
    HealthSnapshotListener,
    HealthStatusResolver,
    SecurityAuditHealthStatusMonitor,
)


logger = logging.getLogger(__name__)


MONITOR_STATE_KEY = (
    "configuration_api_security_audit_health_status_monitor"
)

MONITOR_INSTALLED_STATE_KEY = (
    "configuration_api_security_audit_health_status_monitor_installed"
)


class SecurityAuditHealthStatusMonitorIntegrationError(RuntimeError):
    """Raised when monitor integration operations fail."""


def _validate_app(app: FastAPI) -> None:
    if not isinstance(app, FastAPI):
        raise TypeError("app must be a FastAPI instance")


def install_configuration_api_security_audit_health_status_monitor(
    app: FastAPI,
    *,
    check: HealthCheckCallback,
    interval_seconds: float = 60.0,
    history_limit: int = 100,
    status_resolver: HealthStatusResolver | None = None,
    listeners: tuple[HealthSnapshotListener, ...] = (),
    notify_on_unchanged: bool = False,
) -> SecurityAuditHealthStatusMonitor:
    """Create and register the monitor in application state."""

    _validate_app(app)

    if getattr(app.state, MONITOR_INSTALLED_STATE_KEY, False):
        raise SecurityAuditHealthStatusMonitorIntegrationError(
            "Security-audit health monitor is already installed"
        )

    if getattr(app.state, MONITOR_STATE_KEY, None) is not None:
        raise SecurityAuditHealthStatusMonitorIntegrationError(
            "Monitor state already contains an unregistered instance"
        )

    try:
        monitor = SecurityAuditHealthStatusMonitor(
            check=check,
            interval_seconds=interval_seconds,
            history_limit=history_limit,
            status_resolver=status_resolver,
            listeners=listeners,
            notify_on_unchanged=notify_on_unchanged,
        )

        setattr(app.state, MONITOR_STATE_KEY, monitor)
        setattr(app.state, MONITOR_INSTALLED_STATE_KEY, True)

        logger.info(
            "Installed security-audit health status monitor"
        )

        return monitor

    except Exception as exc:
        raise SecurityAuditHealthStatusMonitorIntegrationError(
            "Failed to install security-audit health monitor"
        ) from exc


def get_configuration_api_security_audit_health_status_monitor(
    app: FastAPI,
) -> SecurityAuditHealthStatusMonitor:
    """Retrieve the installed monitor."""

    _validate_app(app)

    if not getattr(app.state, MONITOR_INSTALLED_STATE_KEY, False):
        raise SecurityAuditHealthStatusMonitorIntegrationError(
            "Security-audit health monitor is not installed"
        )

    monitor = getattr(app.state, MONITOR_STATE_KEY, None)

    if not isinstance(monitor, SecurityAuditHealthStatusMonitor):
        raise SecurityAuditHealthStatusMonitorIntegrationError(
            "Installed health monitor state is invalid"
        )

    return monitor


def is_configuration_api_security_audit_health_status_monitor_installed(
    app: FastAPI,
) -> bool:
    """Return whether a valid monitor is registered."""

    _validate_app(app)

    if not getattr(app.state, MONITOR_INSTALLED_STATE_KEY, False):
        return False

    monitor = getattr(app.state, MONITOR_STATE_KEY, None)

    return isinstance(
        monitor,
        SecurityAuditHealthStatusMonitor,
    )


async def start_configuration_api_security_audit_health_status_monitor(
    app: FastAPI,
    *,
    run_immediately: bool = True,
) -> None:
    """Start the installed monitor."""

    monitor = (
        get_configuration_api_security_audit_health_status_monitor(
            app
        )
    )

    try:
        await monitor.start(
            run_immediately=run_immediately,
        )

    except Exception as exc:
        raise SecurityAuditHealthStatusMonitorIntegrationError(
            "Failed to start security-audit health monitor"
        ) from exc


async def stop_configuration_api_security_audit_health_status_monitor(
    app: FastAPI,
    *,
    cancel_running_check: bool = False,
) -> None:
    """Stop the installed monitor without removing it."""

    monitor = (
        get_configuration_api_security_audit_health_status_monitor(
            app
        )
    )

    try:
        await monitor.stop(
            cancel_running_check=cancel_running_check,
        )

    except Exception as exc:
        raise SecurityAuditHealthStatusMonitorIntegrationError(
            "Failed to stop security-audit health monitor"
        ) from exc


def remove_configuration_api_security_audit_health_status_monitor(
    app: FastAPI,
) -> SecurityAuditHealthStatusMonitor:
    """Remove monitor registration from application state.

    This operation is synchronous and therefore requires the monitor
    to have already been stopped.
    """

    monitor = (
        get_configuration_api_security_audit_health_status_monitor(
            app
        )
    )

    if monitor.is_running:
        raise SecurityAuditHealthStatusMonitorIntegrationError(
            "Stop the health monitor before removing it"
        )

    setattr(app.state, MONITOR_STATE_KEY, None)
    setattr(app.state, MONITOR_INSTALLED_STATE_KEY, False)

    logger.info(
        "Removed security-audit health status monitor registration"
    )

    return monitor


def get_configuration_api_security_audit_health_status_monitor_status(
    app: FastAPI,
) -> dict[str, Any]:
    """Return a JSON-compatible monitor status summary."""

    monitor = (
        get_configuration_api_security_audit_health_status_monitor(
            app
        )
    )

    statistics = monitor.get_statistics()
    snapshot = monitor.latest_snapshot

    return {
        "installed": True,
        "running": monitor.is_running,
        "current_status": monitor.current_status.value,
        "latest_snapshot": (
            {
                "snapshot_id": snapshot.snapshot_id,
                "checked_at": snapshot.checked_at.isoformat(),
                "status": snapshot.status.value,
                "duration_seconds": snapshot.duration_seconds,
                "error": snapshot.error,
            }
            if snapshot is not None
            else None
        ),
        "statistics": {
            "total_checks": statistics.total_checks,
            "successful_checks": statistics.successful_checks,
            "failed_checks": statistics.failed_checks,
            "listener_failures": statistics.listener_failures,
            "last_checked_at": (
                statistics.last_checked_at.isoformat()
                if statistics.last_checked_at is not None
                else None
            ),
            "last_successful_at": (
                statistics.last_successful_at.isoformat()
                if statistics.last_successful_at is not None
                else None
            ),
            "last_failed_at": (
                statistics.last_failed_at.isoformat()
                if statistics.last_failed_at is not None
                else None
            ),
            "average_duration_seconds": (
                statistics.average_duration_seconds
            ),
        },
    }


def get_configuration_api_security_audit_health_status_monitor_history(
    app: FastAPI,
    *,
    limit: int | None = None,
) -> tuple[Any, ...]:
    """Return retained snapshots, optionally limited to the newest N."""

    monitor = (
        get_configuration_api_security_audit_health_status_monitor(
            app
        )
    )

    history = monitor.get_history()

    if limit is None:
        return history

    if (
        isinstance(limit, bool)
        or not isinstance(limit, int)
        or limit < 1
    ):
        raise ValueError("limit must be a positive integer or None")

    return history[-limit:]


async def check_configuration_api_security_audit_health_status_monitor(
    app: FastAPI,
) -> Any:
    """Execute and return one immediate health-check snapshot."""

    monitor = (
        get_configuration_api_security_audit_health_status_monitor(
            app
        )
    )

    try:
        return await monitor.check_once()

    except Exception as exc:
        raise SecurityAuditHealthStatusMonitorIntegrationError(
            "Failed to execute security-audit health check"
        ) from exc


__all__ = [
    "MONITOR_STATE_KEY",
    "MONITOR_INSTALLED_STATE_KEY",
    "SecurityAuditHealthStatusMonitorIntegrationError",
    "install_configuration_api_security_audit_health_status_monitor",
    "get_configuration_api_security_audit_health_status_monitor",
    "is_configuration_api_security_audit_health_status_monitor_installed",
    "start_configuration_api_security_audit_health_status_monitor",
    "stop_configuration_api_security_audit_health_status_monitor",
    "remove_configuration_api_security_audit_health_status_monitor",
    "get_configuration_api_security_audit_health_status_monitor_status",
    "get_configuration_api_security_audit_health_status_monitor_history",
    "check_configuration_api_security_audit_health_status_monitor",
]
