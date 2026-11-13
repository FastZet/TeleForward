
"""Integration tests for the security-audit health-status monitor."""

from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI

from app.services.scheduling.configuration_api_security_audit_health_status_monitor import (
    HealthMonitorStatus,
)
from app.services.scheduling.configuration_api_security_audit_health_status_monitor_integration import (
    MONITOR_INSTALLED_STATE_KEY,
    MONITOR_STATE_KEY,
    SecurityAuditHealthStatusMonitorIntegrationError,
    check_configuration_api_security_audit_health_status_monitor,
    get_configuration_api_security_audit_health_status_monitor,
    get_configuration_api_security_audit_health_status_monitor_history,
    get_configuration_api_security_audit_health_status_monitor_status,
    install_configuration_api_security_audit_health_status_monitor,
    is_configuration_api_security_audit_health_status_monitor_installed,
    remove_configuration_api_security_audit_health_status_monitor,
    start_configuration_api_security_audit_health_status_monitor,
    stop_configuration_api_security_audit_health_status_monitor,
)


@pytest.fixture
def app() -> FastAPI:
    return FastAPI()


def healthy_check():
    return {"status": "healthy"}


# ---------------------------------------------------------------------------
# Installation
# ---------------------------------------------------------------------------


def test_install_registers_monitor(app: FastAPI) -> None:
    monitor = install_configuration_api_security_audit_health_status_monitor(
        app,
        check=healthy_check,
    )

    assert (
        getattr(app.state, MONITOR_STATE_KEY)
        is monitor
    )


def test_install_marks_monitor_as_installed(app: FastAPI) -> None:
    install_configuration_api_security_audit_health_status_monitor(
        app,
        check=healthy_check,
    )

    assert getattr(app.state, MONITOR_INSTALLED_STATE_KEY) is True


def test_install_does_not_start_monitor_automatically(
    app: FastAPI,
) -> None:
    monitor = install_configuration_api_security_audit_health_status_monitor(
        app,
        check=healthy_check,
    )

    assert monitor.is_running is False


def test_install_rejects_non_fastapi_application() -> None:
    with pytest.raises(TypeError):
        install_configuration_api_security_audit_health_status_monitor(
            object(),  # type: ignore[arg-type]
            check=healthy_check,
        )


def test_install_rejects_duplicate_registration(
    app: FastAPI,
) -> None:
    first = install_configuration_api_security_audit_health_status_monitor(
        app,
        check=healthy_check,
    )

    with pytest.raises(SecurityAuditHealthStatusMonitorIntegrationError):
        install_configuration_api_security_audit_health_status_monitor(
            app,
            check=healthy_check,
        )

    assert (
        get_configuration_api_security_audit_health_status_monitor(
            app
        )
        is first
    )


def test_install_rejects_existing_unregistered_monitor_state(
    app: FastAPI,
) -> None:
    setattr(app.state, MONITOR_STATE_KEY, object())

    with pytest.raises(SecurityAuditHealthStatusMonitorIntegrationError):
        install_configuration_api_security_audit_health_status_monitor(
            app,
            check=healthy_check,
        )


@pytest.mark.parametrize(
    "interval",
    [0, -1, True, "60"],
)
def test_install_rejects_invalid_interval(
    app: FastAPI,
    interval,
) -> None:
    with pytest.raises(SecurityAuditHealthStatusMonitorIntegrationError):
        install_configuration_api_security_audit_health_status_monitor(
            app,
            check=healthy_check,
            interval_seconds=interval,
        )

    assert (
        is_configuration_api_security_audit_health_status_monitor_installed(
            app
        )
        is False
    )


def test_install_rejects_invalid_history_limit(
    app: FastAPI,
) -> None:
    with pytest.raises(SecurityAuditHealthStatusMonitorIntegrationError):
        install_configuration_api_security_audit_health_status_monitor(
            app,
            check=healthy_check,
            history_limit=0,
        )


def test_install_rejects_non_callable_check(
    app: FastAPI,
) -> None:
    with pytest.raises(SecurityAuditHealthStatusMonitorIntegrationError):
        install_configuration_api_security_audit_health_status_monitor(
            app,
            check=object(),  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------


def test_get_monitor_returns_registered_instance(
    app: FastAPI,
) -> None:
    monitor = install_configuration_api_security_audit_health_status_monitor(
        app,
        check=healthy_check,
    )

    retrieved = (
        get_configuration_api_security_audit_health_status_monitor(
            app
        )
    )

    assert retrieved is monitor


def test_get_monitor_rejects_uninstalled_monitor(
    app: FastAPI,
) -> None:
    with pytest.raises(SecurityAuditHealthStatusMonitorIntegrationError):
        get_configuration_api_security_audit_health_status_monitor(
            app
        )


def test_get_monitor_detects_invalid_state(
    app: FastAPI,
) -> None:
    setattr(app.state, MONITOR_INSTALLED_STATE_KEY, True)
    setattr(app.state, MONITOR_STATE_KEY, object())

    with pytest.raises(SecurityAuditHealthStatusMonitorIntegrationError):
        get_configuration_api_security_audit_health_status_monitor(
            app
        )


def test_get_monitor_rejects_non_fastapi_application() -> None:
    with pytest.raises(TypeError):
        get_configuration_api_security_audit_health_status_monitor(
            object()  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------------------
# Installation status
# ---------------------------------------------------------------------------


def test_installed_status_is_false_initially(
    app: FastAPI,
) -> None:
    assert (
        is_configuration_api_security_audit_health_status_monitor_installed(
            app
        )
        is False
    )


def test_installed_status_is_true_after_installation(
    app: FastAPI,
) -> None:
    install_configuration_api_security_audit_health_status_monitor(
        app,
        check=healthy_check,
    )

    assert (
        is_configuration_api_security_audit_health_status_monitor_installed(
            app
        )
        is True
    )


def test_installed_status_detects_invalid_monitor_state(
    app: FastAPI,
) -> None:
    setattr(app.state, MONITOR_INSTALLED_STATE_KEY, True)
    setattr(app.state, MONITOR_STATE_KEY, object())

    assert (
        is_configuration_api_security_audit_health_status_monitor_installed(
            app
        )
        is False
    )


def test_installed_status_rejects_non_fastapi_application() -> None:
    with pytest.raises(TypeError):
        is_configuration_api_security_audit_health_status_monitor_installed(
            object()  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------------------
# Start and stop
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_starts_registered_monitor(
    app: FastAPI,
) -> None:
    monitor = install_configuration_api_security_audit_health_status_monitor(
        app,
        check=healthy_check,
        interval_seconds=3600,
    )

    await start_configuration_api_security_audit_health_status_monitor(
        app
    )

    try:
        assert monitor.is_running is True
        assert monitor.current_status is HealthMonitorStatus.HEALTHY
    finally:
        await stop_configuration_api_security_audit_health_status_monitor(
            app
        )


@pytest.mark.asyncio
async def test_start_can_skip_immediate_check(
    app: FastAPI,
) -> None:
    calls = 0

    def check():
        nonlocal calls
        calls += 1
        return {"status": "healthy"}

    monitor = install_configuration_api_security_audit_health_status_monitor(
        app,
        check=check,
        interval_seconds=3600,
    )

    await start_configuration_api_security_audit_health_status_monitor(
        app,
        run_immediately=False,
    )

    try:
        assert monitor.is_running is True
        assert calls == 0
    finally:
        await stop_configuration_api_security_audit_health_status_monitor(
            app
        )


@pytest.mark.asyncio
async def test_stop_stops_registered_monitor(
    app: FastAPI,
) -> None:
    monitor = install_configuration_api_security_audit_health_status_monitor(
        app,
        check=healthy_check,
        interval_seconds=3600,
    )

    await start_configuration_api_security_audit_health_status_monitor(
        app
    )

    await stop_configuration_api_security_audit_health_status_monitor(
        app
    )

    assert monitor.is_running is False


@pytest.mark.asyncio
async def test_start_rejects_uninstalled_monitor(
    app: FastAPI,
) -> None:
    with pytest.raises(SecurityAuditHealthStatusMonitorIntegrationError):
        await start_configuration_api_security_audit_health_status_monitor(
            app
        )


@pytest.mark.asyncio
async def test_stop_rejects_uninstalled_monitor(
    app: FastAPI,
) -> None:
    with pytest.raises(SecurityAuditHealthStatusMonitorIntegrationError):
        await stop_configuration_api_security_audit_health_status_monitor(
            app
        )


@pytest.mark.asyncio
async def test_start_wraps_monitor_errors(
    app: FastAPI,
) -> None:
    monitor = install_configuration_api_security_audit_health_status_monitor(
        app,
        check=healthy_check,
        interval_seconds=3600,
    )

    await monitor.start()

    try:
        with pytest.raises(SecurityAuditHealthStatusMonitorIntegrationError):
            await start_configuration_api_security_audit_health_status_monitor(
                app
            )
    finally:
        await monitor.stop()


@pytest.mark.asyncio
async def test_stop_can_cancel_running_check(
    app: FastAPI,
) -> None:
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def check():
        started.set()

        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    monitor = install_configuration_api_security_audit_health_status_monitor(
        app,
        check=check,
        interval_seconds=0.01,
    )

    await start_configuration_api_security_audit_health_status_monitor(
        app,
        run_immediately=False,
    )

    await asyncio.wait_for(started.wait(), timeout=1)

    await stop_configuration_api_security_audit_health_status_monitor(
        app,
        cancel_running_check=True,
    )

    assert cancelled.is_set()
    assert monitor.is_running is False


# ---------------------------------------------------------------------------
# Immediate health check
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_executes_one_health_check(
    app: FastAPI,
) -> None:
    calls = 0

    def check():
        nonlocal calls
        calls += 1
        return {"status": "healthy"}

    install_configuration_api_security_audit_health_status_monitor(
        app,
        check=check,
    )

    snapshot = (
        await check_configuration_api_security_audit_health_status_monitor(
            app
        )
    )

    assert calls == 1
    assert snapshot.status is HealthMonitorStatus.HEALTHY


@pytest.mark.asyncio
async def test_check_does_not_require_background_monitor_to_run(
    app: FastAPI,
) -> None:
    monitor = install_configuration_api_security_audit_health_status_monitor(
        app,
        check=healthy_check,
    )

    snapshot = (
        await check_configuration_api_security_audit_health_status_monitor(
            app
        )
    )

    assert monitor.is_running is False
    assert snapshot.status is HealthMonitorStatus.HEALTHY


@pytest.mark.asyncio
async def test_check_rejects_uninstalled_monitor(
    app: FastAPI,
) -> None:
    with pytest.raises(SecurityAuditHealthStatusMonitorIntegrationError):
        await check_configuration_api_security_audit_health_status_monitor(
            app
        )


# ---------------------------------------------------------------------------
# Status summary
# ---------------------------------------------------------------------------


def test_status_summary_before_first_check(
    app: FastAPI,
) -> None:
    install_configuration_api_security_audit_health_status_monitor(
        app,
        check=healthy_check,
    )

    result = (
        get_configuration_api_security_audit_health_status_monitor_status(
            app
        )
    )

    assert result["installed"] is True
    assert result["running"] is False
    assert result["current_status"] == "unknown"
    assert result["latest_snapshot"] is None
    assert result["statistics"]["total_checks"] == 0


@pytest.mark.asyncio
async def test_status_summary_after_check(
    app: FastAPI,
) -> None:
    install_configuration_api_security_audit_health_status_monitor(
        app,
        check=healthy_check,
    )

    await check_configuration_api_security_audit_health_status_monitor(
        app
    )

    result = (
        get_configuration_api_security_audit_health_status_monitor_status(
            app
        )
    )

    assert result["current_status"] == "healthy"
    assert result["latest_snapshot"]["status"] == "healthy"
    assert result["statistics"]["total_checks"] == 1
    assert result["statistics"]["successful_checks"] == 1


def test_status_summary_excludes_raw_health_data(
    app: FastAPI,
) -> None:
    install_configuration_api_security_audit_health_status_monitor(
        app,
        check=lambda: {
            "status": "healthy",
            "internal": "sensitive payload",
        },
    )

    result = (
        get_configuration_api_security_audit_health_status_monitor_status(
            app
        )
    )

    assert "health_data" not in result["latest_snapshot"] if (
        result["latest_snapshot"] is not None
    ) else True


def test_status_summary_rejects_uninstalled_monitor(
    app: FastAPI,
) -> None:
    with pytest.raises(SecurityAuditHealthStatusMonitorIntegrationError):
        get_configuration_api_security_audit_health_status_monitor_status(
            app
        )


# ---------------------------------------------------------------------------
# History retrieval
# ---------------------------------------------------------------------------


def test_history_is_empty_before_checks(
    app: FastAPI,
) -> None:
    install_configuration_api_security_audit_health_status_monitor(
        app,
        check=healthy_check,
    )

    assert (
        get_configuration_api_security_audit_health_status_monitor_history(
            app
        )
        == ()
    )


@pytest.mark.asyncio
async def test_history_returns_all_retained_snapshots(
    app: FastAPI,
) -> None:
    install_configuration_api_security_audit_health_status_monitor(
        app,
        check=healthy_check,
    )

    for _ in range(3):
        await check_configuration_api_security_audit_health_status_monitor(
            app
        )

    history = (
        get_configuration_api_security_audit_health_status_monitor_history(
            app
        )
    )

    assert len(history) == 3


@pytest.mark.asyncio
async def test_history_supports_limit(
    app: FastAPI,
) -> None:
    install_configuration_api_security_audit_health_status_monitor(
        app,
        check=healthy_check,
    )

    for _ in range(3):
        await check_configuration_api_security_audit_health_status_monitor(
            app
        )

    history = (
        get_configuration_api_security_audit_health_status_monitor_history(
            app,
            limit=2,
        )
    )

    assert len(history) == 2


@pytest.mark.asyncio
async def test_history_limit_returns_newest_snapshots(
    app: FastAPI,
) -> None:
    install_configuration_api_security_audit_health_status_monitor(
        app,
        check=healthy_check,
    )

    for _ in range(3):
        await check_configuration_api_security_audit_health_status_monitor(
            app
        )

    full_history = (
        get_configuration_api_security_audit_health_status_monitor_history(
            app
        )
    )

    limited_history = (
        get_configuration_api_security_audit_health_status_monitor_history(
            app,
            limit=2,
        )
    )

    assert limited_history == full_history[-2:]


@pytest.mark.parametrize("limit", [0, -1, True, 1.5, "2"])
def test_history_rejects_invalid_limit(
    app: FastAPI,
    limit,
) -> None:
    install_configuration_api_security_audit_health_status_monitor(
        app,
        check=healthy_check,
    )

    with pytest.raises(ValueError):
        get_configuration_api_security_audit_health_status_monitor_history(
            app,
            limit=limit,
        )


def test_history_rejects_uninstalled_monitor(
    app: FastAPI,
) -> None:
    with pytest.raises(SecurityAuditHealthStatusMonitorIntegrationError):
        get_configuration_api_security_audit_health_status_monitor_history(
            app
        )


# ---------------------------------------------------------------------------
# Removal
# ---------------------------------------------------------------------------


def test_remove_returns_monitor(
    app: FastAPI,
):
    monitor = install_configuration_api_security_audit_health_status_monitor(
        app,
        check=healthy_check,
    )

    removed = (
        remove_configuration_api_security_audit_health_status_monitor(
            app
        )
    )

    assert removed is monitor


def test_remove_clears_application_state(
    app: FastAPI,
) -> None:
    install_configuration_api_security_audit_health_status_monitor(
        app,
        check=healthy_check,
    )

    remove_configuration_api_security_audit_health_status_monitor(
        app
    )

    assert getattr(app.state, MONITOR_STATE_KEY) is None
    assert getattr(app.state, MONITOR_INSTALLED_STATE_KEY) is False


def test_remove_marks_monitor_as_uninstalled(
    app: FastAPI,
) -> None:
    install_configuration_api_security_audit_health_status_monitor(
        app,
        check=healthy_check,
    )

    remove_configuration_api_security_audit_health_status_monitor(
        app
    )

    assert (
        is_configuration_api_security_audit_health_status_monitor_installed(
            app
        )
        is False
    )


def test_remove_rejects_running_monitor(
    app: FastAPI,
) -> None:
    monitor = install_configuration_api_security_audit_health_status_monitor(
        app,
        check=healthy_check,
    )

    async def start_and_test():
        await monitor.start()

        try:
            with pytest.raises(
                SecurityAuditHealthStatusMonitorIntegrationError
            ):
                remove_configuration_api_security_audit_health_status_monitor(
                    app
                )
        finally:
            await monitor.stop()

    asyncio.run(start_and_test())


def test_remove_rejects_uninstalled_monitor(
    app: FastAPI,
) -> None:
    with pytest.raises(SecurityAuditHealthStatusMonitorIntegrationError):
        remove_configuration_api_security_audit_health_status_monitor(
            app
        )


def test_removed_monitor_can_be_reinstalled(
    app: FastAPI,
) -> None:
    first = install_configuration_api_security_audit_health_status_monitor(
        app,
        check=healthy_check,
    )

    remove_configuration_api_security_audit_health_status_monitor(
        app
    )

    second = install_configuration_api_security_audit_health_status_monitor(
        app,
        check=healthy_check,
    )

    assert second is not first


# ---------------------------------------------------------------------------
# Application isolation
# ---------------------------------------------------------------------------


def test_applications_have_independent_monitors() -> None:
    first_app = FastAPI()
    second_app = FastAPI()

    first = install_configuration_api_security_audit_health_status_monitor(
        first_app,
        check=healthy_check,
    )

    second = install_configuration_api_security_audit_health_status_monitor(
        second_app,
        check=healthy_check,
    )

    assert first is not second


def test_removal_from_one_application_does_not_affect_another() -> None:
    first_app = FastAPI()
    second_app = FastAPI()

    install_configuration_api_security_audit_health_status_monitor(
        first_app,
        check=healthy_check,
    )

    second = install_configuration_api_security_audit_health_status_monitor(
        second_app,
        check=healthy_check,
    )

    remove_configuration_api_security_audit_health_status_monitor(
        first_app
    )

    assert (
        is_configuration_api_security_audit_health_status_monitor_installed(
            first_app
        )
        is False
    )

    assert (
        get_configuration_api_security_audit_health_status_monitor(
            second_app
        )
        is second
    )
