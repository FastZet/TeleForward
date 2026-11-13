
"""Tests for the security-audit health-status monitor."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone

import pytest

from app.services.scheduling.configuration_api_security_audit_health_status_monitor import (
    HealthMonitorAlreadyRunningError,
    HealthMonitorNotRunningError,
    HealthMonitorStatus,
    HealthSnapshotListener,
    HealthStatusSnapshot,
    SecurityAuditHealthStatusMonitor,
)


@dataclass(frozen=True)
class FakeHealthData:
    status: str
    details: dict[str, str] | None = None


def make_monitor(
    check,
    **kwargs,
) -> SecurityAuditHealthStatusMonitor:
    return SecurityAuditHealthStatusMonitor(
        check=check,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Construction and validation
# ---------------------------------------------------------------------------


def test_monitor_requires_callable_check() -> None:
    with pytest.raises(TypeError):
        make_monitor(None)


@pytest.mark.parametrize(
    "interval",
    [0, -1, True, False, "60", None],
)
def test_monitor_rejects_invalid_interval(interval) -> None:
    with pytest.raises(ValueError):
        make_monitor(
            lambda: {"status": "healthy"},
            interval_seconds=interval,
        )


@pytest.mark.parametrize(
    "limit",
    [0, -1, True, 1.5, "10", None],
)
def test_monitor_rejects_invalid_history_limit(limit) -> None:
    with pytest.raises(ValueError):
        make_monitor(
            lambda: {"status": "healthy"},
            history_limit=limit,
        )


def test_monitor_rejects_invalid_status_resolver() -> None:
    with pytest.raises(TypeError):
        make_monitor(
            lambda: {"status": "healthy"},
            status_resolver=object(),
        )


def test_monitor_requires_tuple_of_listeners() -> None:
    with pytest.raises(TypeError):
        make_monitor(
            lambda: {"status": "healthy"},
            listeners=[],
        )


def test_monitor_rejects_non_callable_listener() -> None:
    with pytest.raises(TypeError):
        make_monitor(
            lambda: {"status": "healthy"},
            listeners=(object(),),
        )


def test_monitor_rejects_invalid_notify_flag() -> None:
    with pytest.raises(TypeError):
        make_monitor(
            lambda: {"status": "healthy"},
            notify_on_unchanged=1,
        )


def test_monitor_initial_state() -> None:
    monitor = make_monitor(
        lambda: {"status": "healthy"},
    )

    assert monitor.is_running is False
    assert monitor.current_status is HealthMonitorStatus.UNKNOWN
    assert monitor.latest_snapshot is None
    assert monitor.get_history() == ()


# ---------------------------------------------------------------------------
# Status resolution
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw_status", "expected"),
    [
        ("healthy", HealthMonitorStatus.HEALTHY),
        ("ok", HealthMonitorStatus.HEALTHY),
        ("degraded", HealthMonitorStatus.DEGRADED),
        ("unhealthy", HealthMonitorStatus.UNHEALTHY),
        ("failed", HealthMonitorStatus.UNHEALTHY),
        ("unknown", HealthMonitorStatus.UNKNOWN),
        ("not_installed", HealthMonitorStatus.DEGRADED),
        ("HEALTHY", HealthMonitorStatus.HEALTHY),
    ],
)
def test_default_status_resolver(raw_status, expected) -> None:
    monitor = make_monitor(
        lambda: {"status": raw_status},
    )

    resolved = monitor._default_status_resolver(
        {"status": raw_status}
    )

    assert resolved is expected


def test_default_status_resolver_accepts_enum() -> None:
    monitor = make_monitor(
        lambda: {"status": "healthy"},
    )

    assert (
        monitor._default_status_resolver(
            {"status": HealthMonitorStatus.HEALTHY}
        )
        is HealthMonitorStatus.HEALTHY
    )


def test_default_status_resolver_accepts_object_attribute() -> None:
    monitor = make_monitor(
        lambda: FakeHealthData(status="healthy"),
    )

    assert (
        monitor._default_status_resolver(
            FakeHealthData(status="healthy")
        )
        is HealthMonitorStatus.HEALTHY
    )


def test_default_status_resolver_rejects_missing_status() -> None:
    monitor = make_monitor(lambda: {})

    with pytest.raises(ValueError):
        monitor._default_status_resolver({})


def test_default_status_resolver_rejects_unknown_status() -> None:
    monitor = make_monitor(lambda: {})

    with pytest.raises(ValueError):
        monitor._default_status_resolver(
            {"status": "maintenance"}
        )


# ---------------------------------------------------------------------------
# Health checks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_once_with_sync_callback() -> None:
    monitor = make_monitor(
        lambda: {"status": "healthy"},
    )

    snapshot = await monitor.check_once()

    assert snapshot.status is HealthMonitorStatus.HEALTHY
    assert snapshot.error is None
    assert monitor.current_status is HealthMonitorStatus.HEALTHY


@pytest.mark.asyncio
async def test_check_once_with_async_callback() -> None:
    async def check():
        return {"status": "degraded"}

    monitor = make_monitor(check)

    snapshot = await monitor.check_once()

    assert snapshot.status is HealthMonitorStatus.DEGRADED


@pytest.mark.asyncio
async def test_check_once_preserves_health_data() -> None:
    health_data = {
        "status": "healthy",
        "components": {
            "audit_logger": "healthy",
        },
    }

    monitor = make_monitor(lambda: health_data)

    snapshot = await monitor.check_once()

    assert snapshot.health_data is health_data


@pytest.mark.asyncio
async def test_check_once_records_failure() -> None:
    def check():
        raise RuntimeError("health service unavailable")

    monitor = make_monitor(check)

    snapshot = await monitor.check_once()

    assert snapshot.status is HealthMonitorStatus.UNKNOWN
    assert "health service unavailable" in snapshot.error
    assert monitor.current_status is HealthMonitorStatus.UNKNOWN


@pytest.mark.asyncio
async def test_check_once_handles_invalid_health_data() -> None:
    monitor = make_monitor(lambda: {"unexpected": True})

    snapshot = await monitor.check_once()

    assert snapshot.status is HealthMonitorStatus.UNKNOWN
    assert snapshot.error is not None


@pytest.mark.asyncio
async def test_check_once_handles_invalid_resolver_result() -> None:
    monitor = make_monitor(
        lambda: {"status": "healthy"},
        status_resolver=lambda _: "healthy",
    )

    snapshot = await monitor.check_once()

    assert snapshot.status is HealthMonitorStatus.UNKNOWN
    assert snapshot.error is not None


@pytest.mark.asyncio
async def test_check_once_does_not_swallow_cancellation() -> None:
    started = asyncio.Event()

    async def check():
        started.set()
        await asyncio.Event().wait()

    monitor = make_monitor(check)

    task = asyncio.create_task(monitor.check_once())

    await started.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_concurrent_checks_are_serialized() -> None:
    active = 0
    maximum_active = 0

    async def check():
        nonlocal active, maximum_active

        active += 1
        maximum_active = max(maximum_active, active)

        await asyncio.sleep(0.02)

        active -= 1
        return {"status": "healthy"}

    monitor = make_monitor(check)

    await asyncio.gather(
        monitor.check_once(),
        monitor.check_once(),
        monitor.check_once(),
    )

    assert maximum_active == 1
    assert monitor.get_statistics().total_checks == 3


# ---------------------------------------------------------------------------
# Snapshots and statistics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_snapshot_contains_timezone_aware_timestamp() -> None:
    monitor = make_monitor(lambda: {"status": "healthy"})

    snapshot = await monitor.check_once()

    assert snapshot.checked_at.tzinfo is not None
    assert snapshot.checked_at.utcoffset() is not None


@pytest.mark.asyncio
async def test_snapshot_has_unique_identifier() -> None:
    monitor = make_monitor(lambda: {"status": "healthy"})

    first = await monitor.check_once()
    second = await monitor.check_once()

    assert first.snapshot_id != second.snapshot_id


@pytest.mark.asyncio
async def test_history_is_bounded() -> None:
    monitor = make_monitor(
        lambda: {"status": "healthy"},
        history_limit=2,
    )

    await monitor.check_once()
    await monitor.check_once()
    await monitor.check_once()

    history = monitor.get_history()

    assert len(history) == 2
    assert history[0].checked_at <= history[1].checked_at


@pytest.mark.asyncio
async def test_history_returns_immutable_tuple() -> None:
    monitor = make_monitor(lambda: {"status": "healthy"})

    await monitor.check_once()

    history = monitor.get_history()

    assert isinstance(history, tuple)


@pytest.mark.asyncio
async def test_latest_snapshot_returns_latest_entry() -> None:
    monitor = make_monitor(lambda: {"status": "healthy"})

    first = await monitor.check_once()
    second = await monitor.check_once()

    assert monitor.latest_snapshot is second
    assert monitor.latest_snapshot is not first


@pytest.mark.asyncio
async def test_statistics_count_successful_checks() -> None:
    monitor = make_monitor(lambda: {"status": "healthy"})

    await monitor.check_once()
    await monitor.check_once()

    statistics = monitor.get_statistics()

    assert statistics.total_checks == 2
    assert statistics.successful_checks == 2
    assert statistics.failed_checks == 0


@pytest.mark.asyncio
async def test_degraded_checks_count_as_successful() -> None:
    monitor = make_monitor(lambda: {"status": "degraded"})

    await monitor.check_once()

    statistics = monitor.get_statistics()

    assert statistics.successful_checks == 1
    assert statistics.failed_checks == 0


@pytest.mark.asyncio
async def test_unhealthy_checks_count_as_failures() -> None:
    monitor = make_monitor(lambda: {"status": "unhealthy"})

    await monitor.check_once()

    statistics = monitor.get_statistics()

    assert statistics.successful_checks == 0
    assert statistics.failed_checks == 1


@pytest.mark.asyncio
async def test_statistics_track_last_execution_timestamps() -> None:
    monitor = make_monitor(lambda: {"status": "healthy"})

    await monitor.check_once()

    statistics = monitor.get_statistics()

    assert statistics.last_checked_at is not None
    assert statistics.last_successful_at is not None
    assert statistics.last_failed_at is None


@pytest.mark.asyncio
async def test_statistics_track_last_failure() -> None:
    monitor = make_monitor(
        lambda: {"status": "unhealthy"},
    )

    await monitor.check_once()

    statistics = monitor.get_statistics()

    assert statistics.last_failed_at is not None
    assert statistics.last_successful_at is None


@pytest.mark.asyncio
async def test_average_duration_is_non_negative() -> None:
    monitor = make_monitor(lambda: {"status": "healthy"})

    await monitor.check_once()

    assert (
        monitor.get_statistics().average_duration_seconds
        >= 0
    )


# ---------------------------------------------------------------------------
# Listeners
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_listener_receives_first_snapshot() -> None:
    received: list[HealthStatusSnapshot] = []

    def listener(snapshot):
        received.append(snapshot)

    monitor = make_monitor(
        lambda: {"status": "healthy"},
        listeners=(listener,),
    )

    snapshot = await monitor.check_once()

    assert received == [snapshot]


@pytest.mark.asyncio
async def test_listener_is_not_notified_when_status_unchanged() -> None:
    received = []

    monitor = make_monitor(
        lambda: {"status": "healthy"},
        listeners=(received.append,),
    )

    await monitor.check_once()
    await monitor.check_once()

    assert len(received) == 1


@pytest.mark.asyncio
async def test_listener_is_notified_on_status_change() -> None:
    received = []
    statuses = iter(["healthy", "degraded"])

    monitor = make_monitor(
        lambda: {"status": next(statuses)},
        listeners=(received.append,),
    )

    await monitor.check_once()
    await monitor.check_once()

    assert len(received) == 2
    assert received[0].status is HealthMonitorStatus.HEALTHY
    assert received[1].status is HealthMonitorStatus.DEGRADED


@pytest.mark.asyncio
async def test_notify_on_unchanged_notifies_every_time() -> None:
    received = []

    monitor = make_monitor(
        lambda: {"status": "healthy"},
        listeners=(received.append,),
        notify_on_unchanged=True,
    )

    await monitor.check_once()
    await monitor.check_once()

    assert len(received) == 2


@pytest.mark.asyncio
async def test_async_listener_is_supported() -> None:
    received = []

    async def listener(snapshot):
        received.append(snapshot)

    monitor = make_monitor(
        lambda: {"status": "healthy"},
        listeners=(listener,),
    )

    snapshot = await monitor.check_once()

    assert received == [snapshot]


@pytest.mark.asyncio
async def test_listener_failure_does_not_block_other_listeners() -> None:
    received = []

    def failing_listener(snapshot):
        raise RuntimeError("listener failed")

    def successful_listener(snapshot):
        received.append(snapshot)

    monitor = make_monitor(
        lambda: {"status": "healthy"},
        listeners=(
            failing_listener,
            successful_listener,
        ),
    )

    snapshot = await monitor.check_once()

    assert received == [snapshot]
    assert monitor.get_statistics().listener_failures == 1


def test_add_listener_rejects_non_callable() -> None:
    monitor = make_monitor(lambda: {"status": "healthy"})

    with pytest.raises(TypeError):
        monitor.add_listener(object())


def test_add_listener_avoids_duplicates() -> None:
    monitor = make_monitor(lambda: {"status": "healthy"})

    def listener(snapshot):
        pass

    monitor.add_listener(listener)
    monitor.add_listener(listener)

    assert monitor._listeners.count(listener) == 1


def test_remove_listener_returns_true_when_present() -> None:
    monitor = make_monitor(lambda: {"status": "healthy"})

    def listener(snapshot):
        pass

    monitor.add_listener(listener)

    assert monitor.remove_listener(listener) is True


def test_remove_listener_returns_false_when_missing() -> None:
    monitor = make_monitor(lambda: {"status": "healthy"})

    def listener(snapshot):
        pass

    assert monitor.remove_listener(listener) is False


# ---------------------------------------------------------------------------
# Background lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_runs_immediate_check_by_default() -> None:
    calls = 0

    def check():
        nonlocal calls
        calls += 1
        return {"status": "healthy"}

    monitor = make_monitor(
        check,
        interval_seconds=3600,
    )

    await monitor.start()

    try:
        assert calls == 1
        assert monitor.is_running is True
    finally:
        await monitor.stop()


@pytest.mark.asyncio
async def test_start_can_skip_immediate_check() -> None:
    calls = 0

    def check():
        nonlocal calls
        calls += 1
        return {"status": "healthy"}

    monitor = make_monitor(
        check,
        interval_seconds=3600,
    )

    await monitor.start(run_immediately=False)

    try:
        assert calls == 0
    finally:
        await monitor.stop()


@pytest.mark.asyncio
async def test_start_rejects_duplicate_start() -> None:
    monitor = make_monitor(
        lambda: {"status": "healthy"},
        interval_seconds=3600,
    )

    await monitor.start()

    try:
        with pytest.raises(HealthMonitorAlreadyRunningError):
            await monitor.start()
    finally:
        await monitor.stop()


@pytest.mark.asyncio
async def test_stop_clears_running_state() -> None:
    monitor = make_monitor(
        lambda: {"status": "healthy"},
        interval_seconds=3600,
    )

    await monitor.start()
    await monitor.stop()

    assert monitor.is_running is False


@pytest.mark.asyncio
async def test_stop_is_safe_when_not_running() -> None:
    monitor = make_monitor(lambda: {"status": "healthy"})

    await monitor.stop()

    assert monitor.is_running is False


@pytest.mark.asyncio
async def test_stop_waits_for_running_check() -> None:
    started = asyncio.Event()
    finished = asyncio.Event()

    async def check():
        started.set()
        await asyncio.sleep(0.05)
        finished.set()
        return {"status": "healthy"}

    monitor = make_monitor(
        check,
        interval_seconds=0.01,
    )

    await monitor.start(run_immediately=False)
    await asyncio.sleep(0.03)

    assert started.is_set()

    await monitor.stop()

    assert finished.is_set()
    assert monitor.is_running is False


@pytest.mark.asyncio
async def test_stop_can_cancel_running_check() -> None:
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def check():
        started.set()

        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    monitor = make_monitor(
        check,
        interval_seconds=0.01,
    )

    await monitor.start(run_immediately=False)
    await asyncio.sleep(0.03)

    assert started.is_set()

    await monitor.stop(cancel_running_check=True)

    assert cancelled.is_set()
    assert monitor.is_running is False


@pytest.mark.asyncio
async def test_stop_rejects_invalid_cancel_flag() -> None:
    monitor = make_monitor(lambda: {"status": "healthy"})

    with pytest.raises(TypeError):
        await monitor.stop(cancel_running_check=1)


@pytest.mark.asyncio
async def test_start_rejects_invalid_immediate_flag() -> None:
    monitor = make_monitor(lambda: {"status": "healthy"})

    with pytest.raises(TypeError):
        await monitor.start(run_immediately=1)


@pytest.mark.asyncio
async def test_context_manager_starts_and_stops_monitor() -> None:
    monitor = make_monitor(
        lambda: {"status": "healthy"},
        interval_seconds=3600,
    )

    async with monitor as active_monitor:
        assert active_monitor is monitor
        assert monitor.is_running is True

    assert monitor.is_running is False


@pytest.mark.asyncio
async def test_wait_until_stopped_returns_when_not_started() -> None:
    monitor = make_monitor(lambda: {"status": "healthy"})

    await monitor.wait_until_stopped()


# ---------------------------------------------------------------------------
# Snapshot validation
# ---------------------------------------------------------------------------


def test_snapshot_rejects_empty_identifier() -> None:
    with pytest.raises(ValueError):
        HealthStatusSnapshot(
            snapshot_id="",
            checked_at=datetime.now(timezone.utc),
            status=HealthMonitorStatus.HEALTHY,
            health_data={},
        )


def test_snapshot_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError):
        HealthStatusSnapshot(
            snapshot_id="snapshot-1",
            checked_at=datetime.now(),
            status=HealthMonitorStatus.HEALTHY,
            health_data={},
        )


def test_snapshot_rejects_negative_duration() -> None:
    with pytest.raises(ValueError):
        HealthStatusSnapshot(
            snapshot_id="snapshot-1",
            checked_at=datetime.now(timezone.utc),
            status=HealthMonitorStatus.HEALTHY,
            health_data={},
            duration_seconds=-1,
        )


def test_snapshot_rejects_invalid_error_type() -> None:
    with pytest.raises(TypeError):
        HealthStatusSnapshot(
            snapshot_id="snapshot-1",
            checked_at=datetime.now(timezone.utc),
            status=HealthMonitorStatus.HEALTHY,
            health_data={},
            error=123,  # type: ignore[arg-type]
        )
