
"""Periodic monitoring for consolidated security-audit health status."""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections import deque
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4


logger = logging.getLogger(__name__)


class HealthMonitorError(RuntimeError):
    """Base exception for health-monitor failures."""


class HealthMonitorAlreadyRunningError(HealthMonitorError):
    """Raised when the monitor is already running."""


class HealthMonitorNotRunningError(HealthMonitorError):
    """Raised when an operation requires a running monitor."""


class HealthMonitorStatus(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class HealthStatusSnapshot:
    """Immutable record of one health-monitor execution."""

    snapshot_id: str
    checked_at: datetime
    status: HealthMonitorStatus
    health_data: Any = field(repr=False)
    duration_seconds: float = 0.0
    error: str | None = None

    def __post_init__(self) -> None:
        if not self.snapshot_id:
            raise ValueError("snapshot_id cannot be empty")

        if (
            self.checked_at.tzinfo is None
            or self.checked_at.utcoffset() is None
        ):
            raise ValueError("checked_at must be timezone-aware")

        if self.duration_seconds < 0:
            raise ValueError("duration_seconds cannot be negative")

        if self.error is not None and not isinstance(self.error, str):
            raise TypeError("error must be a string or None")


@dataclass(frozen=True, slots=True)
class HealthMonitorStatistics:
    """Aggregate statistics for monitor executions."""

    total_checks: int
    successful_checks: int
    failed_checks: int
    listener_failures: int
    last_checked_at: datetime | None
    last_successful_at: datetime | None
    last_failed_at: datetime | None
    current_status: HealthMonitorStatus
    average_duration_seconds: float


HealthCheckCallback = Callable[
    [],
    Any | Awaitable[Any],
]

HealthStatusResolver = Callable[
    [Any],
    HealthMonitorStatus,
]

HealthSnapshotListener = Callable[
    [HealthStatusSnapshot],
    Any | Awaitable[Any],
]


class SecurityAuditHealthStatusMonitor:
    """Periodically evaluates and records security-audit health."""

    def __init__(
        self,
        *,
        check: HealthCheckCallback,
        interval_seconds: float = 60.0,
        history_limit: int = 100,
        status_resolver: HealthStatusResolver | None = None,
        listeners: tuple[HealthSnapshotListener, ...] = (),
        notify_on_unchanged: bool = False,
    ) -> None:
        if not callable(check):
            raise TypeError("check must be callable")

        if (
            isinstance(interval_seconds, bool)
            or not isinstance(interval_seconds, (int, float))
            or interval_seconds <= 0
        ):
            raise ValueError(
                "interval_seconds must be a positive number"
            )

        if (
            isinstance(history_limit, bool)
            or not isinstance(history_limit, int)
            or history_limit < 1
        ):
            raise ValueError("history_limit must be a positive integer")

        if status_resolver is not None and not callable(status_resolver):
            raise TypeError("status_resolver must be callable")

        if not isinstance(listeners, tuple):
            raise TypeError("listeners must be a tuple")

        if any(not callable(listener) for listener in listeners):
            raise TypeError("every listener must be callable")

        if not isinstance(notify_on_unchanged, bool):
            raise TypeError("notify_on_unchanged must be a boolean")

        self._check = check
        self._interval_seconds = float(interval_seconds)
        self._history: deque[HealthStatusSnapshot] = deque(
            maxlen=history_limit
        )
        self._status_resolver = (
            status_resolver or self._default_status_resolver
        )
        self._listeners = list(listeners)
        self._notify_on_unchanged = notify_on_unchanged

        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._check_lock = asyncio.Lock()
        self._lifecycle_lock = asyncio.Lock()

        self._total_checks = 0
        self._successful_checks = 0
        self._failed_checks = 0
        self._listener_failures = 0
        self._duration_total = 0.0

        self._last_checked_at: datetime | None = None
        self._last_successful_at: datetime | None = None
        self._last_failed_at: datetime | None = None
        self._current_status = HealthMonitorStatus.UNKNOWN

    @staticmethod
    def _default_status_resolver(
        health_data: Any,
    ) -> HealthMonitorStatus:
        """Resolve status from a subsystem-health object or mapping."""

        raw_status: Any = None

        if isinstance(health_data, Mapping):
            raw_status = health_data.get("status")
        else:
            raw_status = getattr(health_data, "status", None)

        if isinstance(raw_status, HealthMonitorStatus):
            return raw_status

        if isinstance(raw_status, StrEnum):
            raw_status = raw_status.value

        if isinstance(raw_status, str):
            normalized = raw_status.strip().lower()

            aliases = {
                "healthy": HealthMonitorStatus.HEALTHY,
                "ok": HealthMonitorStatus.HEALTHY,
                "degraded": HealthMonitorStatus.DEGRADED,
                "unhealthy": HealthMonitorStatus.UNHEALTHY,
                "failed": HealthMonitorStatus.UNHEALTHY,
                "unknown": HealthMonitorStatus.UNKNOWN,
                "not_installed": HealthMonitorStatus.DEGRADED,
            }

            if normalized in aliases:
                return aliases[normalized]

        raise ValueError(
            "Health data must expose a recognised status value"
        )

    @property
    def is_running(self) -> bool:
        """Whether the background monitoring task is active."""

        return self._task is not None and not self._task.done()

    @property
    def current_status(self) -> HealthMonitorStatus:
        return self._current_status

    @property
    def latest_snapshot(self) -> HealthStatusSnapshot | None:
        if not self._history:
            return None

        return self._history[-1]

    def get_history(self) -> tuple[HealthStatusSnapshot, ...]:
        """Return retained snapshots in chronological order."""

        return tuple(self._history)

    def get_statistics(self) -> HealthMonitorStatistics:
        """Return cumulative monitor statistics."""

        average_duration = (
            self._duration_total / self._total_checks
            if self._total_checks
            else 0.0
        )

        return HealthMonitorStatistics(
            total_checks=self._total_checks,
            successful_checks=self._successful_checks,
            failed_checks=self._failed_checks,
            listener_failures=self._listener_failures,
            last_checked_at=self._last_checked_at,
            last_successful_at=self._last_successful_at,
            last_failed_at=self._last_failed_at,
            current_status=self._current_status,
            average_duration_seconds=average_duration,
        )

    def add_listener(
        self,
        listener: HealthSnapshotListener,
    ) -> None:
        if not callable(listener):
            raise TypeError("listener must be callable")

        if listener not in self._listeners:
            self._listeners.append(listener)

    def remove_listener(
        self,
        listener: HealthSnapshotListener,
    ) -> bool:
        try:
            self._listeners.remove(listener)
            return True
        except ValueError:
            return False

    async def check_once(self) -> HealthStatusSnapshot:
        """Run one health check and publish its snapshot."""

        async with self._check_lock:
            started_at = asyncio.get_running_loop().time()
            checked_at = datetime.now(timezone.utc)

            health_data: Any = None
            error_message: str | None = None

            try:
                result = self._check()

                if inspect.isawaitable(result):
                    result = await result

                health_data = result
                resolved_status = self._status_resolver(health_data)

                if not isinstance(resolved_status, HealthMonitorStatus):
                    raise TypeError(
                        "status_resolver must return HealthMonitorStatus"
                    )

                successful = resolved_status in {
                    HealthMonitorStatus.HEALTHY,
                    HealthMonitorStatus.DEGRADED,
                }

            except asyncio.CancelledError:
                raise

            except Exception as exc:
                logger.exception("Security-audit health check failed")

                resolved_status = HealthMonitorStatus.UNKNOWN
                successful = False
                error_message = (
                    f"{type(exc).__name__}: {exc}"
                )

            duration = (
                asyncio.get_running_loop().time() - started_at
            )

            previous_status = self._current_status

            snapshot = HealthStatusSnapshot(
                snapshot_id=str(uuid4()),
                checked_at=checked_at,
                status=resolved_status,
                health_data=health_data,
                duration_seconds=duration,
                error=error_message,
            )

            self._history.append(snapshot)
            self._total_checks += 1
            self._duration_total += duration
            self._last_checked_at = checked_at
            self._current_status = resolved_status

            if successful:
                self._successful_checks += 1
                self._last_successful_at = checked_at
            else:
                self._failed_checks += 1
                self._last_failed_at = checked_at

            should_notify = (
                self._notify_on_unchanged
                or resolved_status != previous_status
            )

            if should_notify:
                await self._notify_listeners(snapshot)

            return snapshot

    async def _notify_listeners(
        self,
        snapshot: HealthStatusSnapshot,
    ) -> None:
        """Notify listeners independently; one failure must not block others."""

        for listener in tuple(self._listeners):
            try:
                result = listener(snapshot)

                if inspect.isawaitable(result):
                    await result

            except asyncio.CancelledError:
                raise

            except Exception:
                self._listener_failures += 1
                logger.exception(
                    "Security-audit health listener failed"
                )

    async def start(
        self,
        *,
        run_immediately: bool = True,
    ) -> None:
        """Start periodic monitoring."""

        if not isinstance(run_immediately, bool):
            raise TypeError("run_immediately must be a boolean")

        async with self._lifecycle_lock:
            if self.is_running:
                raise HealthMonitorAlreadyRunningError(
                    "Health monitor is already running"
                )

            if self._task is not None:
                await self._task
                self._task = None

            self._stop_event = asyncio.Event()

            if run_immediately:
                await self.check_once()

            self._task = asyncio.create_task(
                self._monitor_loop(),
                name="security-audit-health-monitor",
            )

    async def _monitor_loop(self) -> None:
        """Run periodic checks until explicitly stopped."""

        try:
            while not self._stop_event.is_set():
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=self._interval_seconds,
                    )
                    break

                except TimeoutError:
                    pass

                if self._stop_event.is_set():
                    break

                try:
                    await self.check_once()

                except asyncio.CancelledError:
                    raise

                except Exception:
                    # check_once normally converts check failures into
                    # snapshots. This guard protects the monitor loop
                    # from unexpected internal failures.
                    logger.exception(
                        "Unexpected health-monitor execution failure"
                    )

        except asyncio.CancelledError:
            raise

        finally:
            logger.debug("Security-audit health monitor stopped")

    async def stop(
        self,
        *,
        cancel_running_check: bool = False,
    ) -> None:
        """Stop background monitoring and wait for its task to finish."""

        if not isinstance(cancel_running_check, bool):
            raise TypeError("cancel_running_check must be a boolean")

        async with self._lifecycle_lock:
            task = self._task

            if task is None:
                return

            self._stop_event.set()

            if cancel_running_check and not task.done():
                task.cancel()

            try:
                await task

            except asyncio.CancelledError:
                if not cancel_running_check:
                    raise

            finally:
                if self._task is task:
                    self._task = None

    async def wait_until_stopped(self) -> None:
        """Wait for the background task to finish."""

        task = self._task

        if task is None:
            return

        await task

    async def __aenter__(
        self,
    ) -> SecurityAuditHealthStatusMonitor:
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: Any,
        exc_value: Any,
        traceback: Any,
    ) -> None:
        await self.stop(cancel_running_check=False)
