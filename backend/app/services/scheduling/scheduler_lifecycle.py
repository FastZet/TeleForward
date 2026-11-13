
"""Lifecycle coordination for the scheduling subsystem."""

from __future__ import annotations

import asyncio
import inspect
import logging
from enum import StrEnum
from typing import Any, Callable

logger = logging.getLogger(__name__)


class SchedulerLifecycleState(StrEnum):
    """Lifecycle states of the scheduling subsystem."""

    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    FAILED = "failed"


class SchedulerLifecycleError(RuntimeError):
    """Raised when scheduler lifecycle operations fail."""


class SchedulerLifecycle:
    """
    Coordinate startup and shutdown of scheduling components.

    Expected manager interface:
        start()
        shutdown()

    Optional monitor interface:
        start(run_immediately=True)
        stop()

    The manager is responsible for restoring persisted jobs and starting
    its underlying scheduler. This coordinator deliberately does not start
    the scheduler independently.
    """

    def __init__(
        self,
        manager: Any,
        *,
        health_monitor: Any | None = None,
        before_start: Callable[[], Any] | None = None,
        after_start: Callable[[], Any] | None = None,
        before_shutdown: Callable[[], Any] | None = None,
        after_shutdown: Callable[[], Any] | None = None,
        monitor_run_immediately: bool = True,
    ) -> None:
        if manager is None:
            raise ValueError("manager is required")

        callbacks = {
            "before_start": before_start,
            "after_start": after_start,
            "before_shutdown": before_shutdown,
            "after_shutdown": after_shutdown,
        }

        for name, callback in callbacks.items():
            if callback is not None and not callable(callback):
                raise TypeError(f"{name} must be callable")

        if not isinstance(monitor_run_immediately, bool):
            raise TypeError("monitor_run_immediately must be a boolean")

        if not callable(getattr(manager, "start", None)):
            raise TypeError("manager must provide a callable start() method")

        if not callable(getattr(manager, "shutdown", None)):
            raise TypeError("manager must provide a callable shutdown() method")

        if health_monitor is not None:
            if not callable(getattr(health_monitor, "start", None)):
                raise TypeError(
                    "health_monitor must provide a callable start() method"
                )

            if not callable(getattr(health_monitor, "stop", None)):
                raise TypeError(
                    "health_monitor must provide a callable stop() method"
                )

        self._manager = manager
        self._health_monitor = health_monitor

        self._before_start = before_start
        self._after_start = after_start
        self._before_shutdown = before_shutdown
        self._after_shutdown = after_shutdown

        self._monitor_run_immediately = monitor_run_immediately

        self._state = SchedulerLifecycleState.STOPPED
        self._lock = asyncio.Lock()

        self._manager_started = False
        self._monitor_started = False

        self._last_error: str | None = None

    @property
    def state(self) -> SchedulerLifecycleState:
        return self._state

    @property
    def is_running(self) -> bool:
        return self._state == SchedulerLifecycleState.RUNNING

    @property
    def last_error(self) -> str | None:
        return self._last_error

    @property
    def manager_started(self) -> bool:
        return self._manager_started

    @property
    def monitor_started(self) -> bool:
        return self._monitor_started

    async def start(self) -> None:
        """Start the scheduling subsystem."""

        async with self._lock:
            if self._state == SchedulerLifecycleState.RUNNING:
                return

            if self._state in {
                SchedulerLifecycleState.STARTING,
                SchedulerLifecycleState.STOPPING,
            }:
                raise SchedulerLifecycleError(
                    f"Cannot start while lifecycle is {self._state.value}"
                )

            self._state = SchedulerLifecycleState.STARTING
            self._last_error = None

            try:
                await self._invoke(self._before_start)

                await self._invoke(self._manager.start)
                self._manager_started = True

                if self._health_monitor is not None:
                    await self._invoke(
                        self._health_monitor.start,
                        run_immediately=self._monitor_run_immediately,
                    )
                    self._monitor_started = True

                await self._invoke(self._after_start)

                self._state = SchedulerLifecycleState.RUNNING

                logger.info("Scheduling subsystem started")

            except BaseException as exc:
                self._last_error = self._describe_error(exc)
                self._state = SchedulerLifecycleState.FAILED

                await self._rollback_startup()

                if isinstance(exc, Exception):
                    raise SchedulerLifecycleError(
                        "Failed to start scheduling subsystem"
                    ) from exc

                raise

    async def shutdown(self) -> None:
        """Stop the scheduling subsystem gracefully."""

        async with self._lock:
            if (
                self._state == SchedulerLifecycleState.STOPPED
                and not self._manager_started
                and not self._monitor_started
            ):
                return

            if self._state == SchedulerLifecycleState.STOPPING:
                return

            self._state = SchedulerLifecycleState.STOPPING

            errors: list[BaseException] = []

            try:
                await self._invoke(self._before_shutdown)
            except Exception as exc:
                errors.append(exc)
                logger.exception("Pre-shutdown callback failed")

            if self._monitor_started and self._health_monitor is not None:
                try:
                    await self._invoke(self._health_monitor.stop)
                    self._monitor_started = False
                except Exception as exc:
                    errors.append(exc)
                    logger.exception("Health monitor shutdown failed")

            if self._manager_started:
                try:
                    await self._invoke(self._manager.shutdown)
                    self._manager_started = False
                except Exception as exc:
                    errors.append(exc)
                    logger.exception("Scheduler manager shutdown failed")

            try:
                await self._invoke(self._after_shutdown)
            except Exception as exc:
                errors.append(exc)
                logger.exception("Post-shutdown callback failed")

            if errors:
                self._state = SchedulerLifecycleState.FAILED
                self._last_error = "; ".join(
                    self._describe_error(error) for error in errors
                )

                raise SchedulerLifecycleError(
                    "One or more scheduling shutdown operations failed"
                ) from errors[0]

            self._state = SchedulerLifecycleState.STOPPED
            self._last_error = None

            logger.info("Scheduling subsystem stopped")

    async def restart(self) -> None:
        """Gracefully stop and start the scheduling subsystem."""

        async with self._lock:
            pass

        await self.shutdown()
        await self.start()

    async def _rollback_startup(self) -> None:
        """Best-effort cleanup after an unsuccessful startup."""

        if self._monitor_started and self._health_monitor is not None:
            try:
                await self._invoke(self._health_monitor.stop)
                self._monitor_started = False
            except Exception:
                logger.exception(
                    "Failed to stop health monitor during startup rollback"
                )

        if self._manager_started:
            try:
                await self._invoke(self._manager.shutdown)
                self._manager_started = False
            except Exception:
                logger.exception(
                    "Failed to stop scheduler manager during startup rollback"
                )

    @staticmethod
    async def _invoke(
        callback: Callable[..., Any] | None,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Invoke a synchronous or asynchronous callback."""

        if callback is None:
            return None

        result = callback(*args, **kwargs)

        if inspect.isawaitable(result):
            return await result

        return result

    @staticmethod
    def _describe_error(error: BaseException) -> str:
        return f"{type(error).__name__}: {error}"
