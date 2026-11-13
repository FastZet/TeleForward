
"""Tests for the security audit health monitor FastAPI lifespan integration."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI

from app.services.scheduling.configuration_api_security_audit_health_status_monitor import (
    install_configuration_api_security_audit_health_status_monitor,
)
from app.services.scheduling.configuration_api_security_audit_health_status_monitor_lifespan import (
    SecurityAuditHealthStatusMonitorLifespanError,
    create_security_audit_health_status_monitor_lifespan,
)
from app.services.scheduling.configuration_api_security_audit_health_status_monitor import (
    SecurityAuditHealthStatusMonitor,
)


@pytest.fixture
def app() -> FastAPI:
    return FastAPI()


@pytest.fixture
def monitor(monkeypatch: pytest.MonkeyPatch) -> SecurityAuditHealthStatusMonitor:
    """Create a monitor instance without starting background tasks."""

    instance = object.__new__(SecurityAuditHealthStatusMonitor)

    state = {"running": False}

    async def start(*, run_immediately: bool = True) -> None:
        state["running"] = True

    async def stop(*, cancel: bool = True) -> None:
        state["running"] = False

    monkeypatch.setattr(
        SecurityAuditHealthStatusMonitor,
        "start",
        start,
    )
    monkeypatch.setattr(
        SecurityAuditHealthStatusMonitor,
        "stop",
        stop,
    )
    monkeypatch.setattr(
        SecurityAuditHealthStatusMonitor,
        "is_running",
        property(lambda self: state["running"]),
    )

    instance._test_state = state
    return instance


def install_monitor(
    app: FastAPI,
    monitor: SecurityAuditHealthStatusMonitor,
) -> None:
    install_configuration_api_security_audit_health_status_monitor(
        app,
        monitor,
    )


@pytest.mark.asyncio
async def test_lifespan_starts_and_stops_monitor(
    app: FastAPI,
    monitor: SecurityAuditHealthStatusMonitor,
) -> None:
    install_monitor(app, monitor)

    lifespan = create_security_audit_health_status_monitor_lifespan()

    async with lifespan(app):
        assert monitor.is_running is True

    assert monitor.is_running is False


@pytest.mark.asyncio
async def test_lifespan_runs_callbacks_in_expected_order(
    app: FastAPI,
    monitor: SecurityAuditHealthStatusMonitor,
) -> None:
    install_monitor(app, monitor)

    events: list[str] = []

    def before_start(application: FastAPI) -> None:
        assert application is app
        events.append("before_start")

    async def after_start(application: FastAPI) -> None:
        assert application is app
        events.append("after_start")

    def before_shutdown(application: FastAPI) -> None:
        assert application is app
        events.append("before_shutdown")

    async def after_shutdown(application: FastAPI) -> None:
        assert application is app
        events.append("after_shutdown")

    lifespan = create_security_audit_health_status_monitor_lifespan(
        before_start=before_start,
        after_start=after_start,
        before_shutdown=before_shutdown,
        after_shutdown=after_shutdown,
    )

    async with lifespan(app):
        events.append("application_running")

    assert events == [
        "before_start",
        "after_start",
        "application_running",
        "before_shutdown",
        "after_shutdown",
    ]


@pytest.mark.asyncio
async def test_lifespan_supports_async_callbacks(
    app: FastAPI,
    monitor: SecurityAuditHealthStatusMonitor,
) -> None:
    install_monitor(app, monitor)

    events: list[str] = []

    async def callback(application: FastAPI) -> None:
        assert application is app
        events.append("called")

    lifespan = create_security_audit_health_status_monitor_lifespan(
        before_start=callback,
    )

    async with lifespan(app):
        pass

    assert events == ["called"]


@pytest.mark.asyncio
async def test_lifespan_runs_without_optional_callbacks(
    app: FastAPI,
    monitor: SecurityAuditHealthStatusMonitor,
) -> None:
    install_monitor(app, monitor)

    lifespan = create_security_audit_health_status_monitor_lifespan()

    async with lifespan(app):
        assert monitor.is_running is True

    assert monitor.is_running is False


@pytest.mark.asyncio
async def test_lifespan_rejects_missing_monitor(
    app: FastAPI,
) -> None:
    lifespan = create_security_audit_health_status_monitor_lifespan()

    with pytest.raises(SecurityAuditHealthStatusMonitorLifespanError):
        async with lifespan(app):
            pass


@pytest.mark.asyncio
async def test_before_start_failure_does_not_start_monitor(
    app: FastAPI,
    monitor: SecurityAuditHealthStatusMonitor,
) -> None:
    install_monitor(app, monitor)

    async def fail(application: FastAPI) -> None:
        raise RuntimeError("Startup callback failed")

    lifespan = create_security_audit_health_status_monitor_lifespan(
        before_start=fail,
    )

    with pytest.raises(RuntimeError, match="Startup callback failed"):
        async with lifespan(app):
            pass

    assert monitor.is_running is False


@pytest.mark.asyncio
async def test_after_start_failure_stops_monitor(
    app: FastAPI,
    monitor: SecurityAuditHealthStatusMonitor,
) -> None:
    install_monitor(app, monitor)

    async def fail(application: FastAPI) -> None:
        raise RuntimeError("Post-start callback failed")

    lifespan = create_security_audit_health_status_monitor_lifespan(
        after_start=fail,
    )

    with pytest.raises(RuntimeError, match="Post-start callback failed"):
        async with lifespan(app):
            pass

    assert monitor.is_running is False


@pytest.mark.asyncio
async def test_before_shutdown_failure_does_not_prevent_monitor_stop(
    app: FastAPI,
    monitor: SecurityAuditHealthStatusMonitor,
) -> None:
    install_monitor(app, monitor)

    async def fail(application: FastAPI) -> None:
        raise RuntimeError("Shutdown callback failed")

    lifespan = create_security_audit_health_status_monitor_lifespan(
        before_shutdown=fail,
    )

    async with lifespan(app):
        assert monitor.is_running is True

    assert monitor.is_running is False


@pytest.mark.asyncio
async def test_after_shutdown_failure_does_not_leave_monitor_running(
    app: FastAPI,
    monitor: SecurityAuditHealthStatusMonitor,
) -> None:
    install_monitor(app, monitor)

    async def fail(application: FastAPI) -> None:
        raise RuntimeError("Post-shutdown callback failed")

    lifespan = create_security_audit_health_status_monitor_lifespan(
        after_shutdown=fail,
    )

    async with lifespan(app):
        assert monitor.is_running is True

    assert monitor.is_running is False


@pytest.mark.asyncio
async def test_application_exception_still_stops_monitor(
    app: FastAPI,
    monitor: SecurityAuditHealthStatusMonitor,
) -> None:
    install_monitor(app, monitor)

    lifespan = create_security_audit_health_status_monitor_lifespan()

    with pytest.raises(RuntimeError, match="Application failure"):
        async with lifespan(app):
            assert monitor.is_running is True
            raise RuntimeError("Application failure")

    assert monitor.is_running is False


@pytest.mark.asyncio
async def test_lifespan_does_not_swallow_application_exception(
    app: FastAPI,
    monitor: SecurityAuditHealthStatusMonitor,
) -> None:
    install_monitor(app, monitor)

    lifespan = create_security_audit_health_status_monitor_lifespan()

    with pytest.raises(ValueError, match="Application error"):
        async with lifespan(app):
            raise ValueError("Application error")


@pytest.mark.asyncio
async def test_monitor_is_stopped_after_normal_lifespan_exit(
    app: FastAPI,
    monitor: SecurityAuditHealthStatusMonitor,
) -> None:
    install_monitor(app, monitor)

    lifespan = create_security_audit_health_status_monitor_lifespan()

    async with lifespan(app):
        assert monitor.is_running is True

    assert monitor.is_running is False


@pytest.mark.asyncio
async def test_startup_callback_receives_application_instance(
    app: FastAPI,
    monitor: SecurityAuditHealthStatusMonitor,
) -> None:
    install_monitor(app, monitor)

    received: list[Any] = []

    def callback(application: FastAPI) -> None:
        received.append(application)

    lifespan = create_security_audit_health_status_monitor_lifespan(
        before_start=callback,
    )

    async with lifespan(app):
        pass

    assert received == [app]


def test_lifespan_factory_rejects_invalid_callback() -> None:
    with pytest.raises((TypeError, ValueError)):
        create_security_audit_health_status_monitor_lifespan(
            before_start="not a callback",  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_shutdown_callbacks_are_called_after_normal_exit(
    app: FastAPI,
    monitor: SecurityAuditHealthStatusMonitor,
) -> None:
    install_monitor(app, monitor)

    events: list[str] = []

    async def before_shutdown(application: FastAPI) -> None:
        events.append("before_shutdown")

    async def after_shutdown(application: FastAPI) -> None:
        events.append("after_shutdown")

    lifespan = create_security_audit_health_status_monitor_lifespan(
        before_shutdown=before_shutdown,
        after_shutdown=after_shutdown,
    )

    async with lifespan(app):
        pass

    assert events == ["before_shutdown", "after_shutdown"]


@pytest.mark.asyncio
async def test_startup_and_shutdown_callbacks_are_not_repeated(
    app: FastAPI,
    monitor: SecurityAuditHealthStatusMonitor,
) -> None:
    install_monitor(app, monitor)

    events: list[str] = []

    def callback(application: FastAPI) -> None:
        events.append("called")

    lifespan = create_security_audit_health_status_monitor_lifespan(
        before_start=callback,
        before_shutdown=callback,
    )

    async with lifespan(app):
        assert events == ["called"]

    assert events == ["called", "called"]
