
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
    Coordinate startup, restart and shutdown of scheduling components.

    Required manager interface:
        start()
        shutdown()

    Optional health monitor interface:
        start(run_immediately=True)
        stop()

    The manager owns the underlying scheduler lifecycle, including
    restoration of persisted jobs and scheduler startup.

    All lifecycle operations are serialised using an asyncio lock.
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
            raise TypeError(
                "monitor_run_immediately must be a boolean"
            )

        if not callable(getattr(manager, "start", None)):
            raise TypeError(
                "manager must provide a callable start() method"
            )

        if not callable(getattr(manager, "shutdown", None)):
            raise TypeError(
                "manager must provide a callable shutdown() method"
            )

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
        """Return the current lifecycle state."""

        return self._state

    @property
    def is_running(self) -> bool:
        """Return whether the subsystem is fully running."""

        return self._state == SchedulerLifecycleState.RUNNING

    @property
    def last_error(self) -> str | None:
        """Return the most recent lifecycle error."""

        return self._last_error

    @property
    def manager_started(self) -> bool:
        """
        Return whether the manager may require cleanup.

        This flag remains true after an unsuccessful cleanup attempt.
        """

        return self._manager_started

    @property
    def monitor_started(self) -> bool:
        """
        Return whether the monitor may require cleanup.

        This flag remains true after an unsuccessful cleanup attempt.
        """

        return self._monitor_started

    async def start(self) -> None:
        """Start the scheduling subsystem."""

        async with self._lock:
            await self._start_locked()

    async def shutdown(self) -> None:
        """Stop the scheduling subsystem gracefully."""

        async with self._lock:
            await self._shutdown_locked()

    async def restart(self) -> None:
        """
        Perform a serialised shutdown followed by startup.

        The lifecycle lock remains held throughout the operation so that
        concurrent start or shutdown calls cannot interleave with restart.
        """

        async with self._lock:
            if (
                self._manager_started
                or self._monitor_started
                or self._state
                in {
                    SchedulerLifecycleState.RUNNING,
                    SchedulerLifecycleState.FAILED,
                }
            ):
                await self._shutdown_locked()

            await self._start_locked()

    async def _start_locked(self) -> None:
        """Start components while the lifecycle lock is held."""

        if self._state == SchedulerLifecycleState.RUNNING:
            return

        if self._state in {
            SchedulerLifecycleState.STARTING,
            SchedulerLifecycleState.STOPPING,
        }:
            raise SchedulerLifecycleError(
                f"Cannot start while lifecycle is {self._state.value}"
            )

        if self._manager_started or self._monitor_started:
            raise SchedulerLifecycleError(
                "Cannot start while previous components still require cleanup"
            )

        self._state = SchedulerLifecycleState.STARTING
        self._last_error = None

        try:
            await self._invoke(self._before_start)

            # Mark startup as attempted before invoking the component.
            # A component may partially initialise and then raise.
            self._manager_started = True
            await self._invoke(self._manager.start)

            if self._health_monitor is not None:
                self._monitor_started = True

                await self._invoke(
                    self._health_monitor.start,
                    run_immediately=self._monitor_run_immediately,
                )

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

    async def _shutdown_locked(self) -> None:
        """Stop components while the lifecycle lock is held."""

        if (
            self._state == SchedulerLifecycleState.STOPPED
            and not self._manager_started
            and not self._monitor_started
        ):
            return

        self._state = SchedulerLifecycleState.STOPPING

        errors: list[Exception] = []
        cancellation: asyncio.CancelledError | None = None

        async def invoke_cleanup(
            callback: Callable[..., Any] | None,
            *,
            description: str,
        ) -> bool:
            """
            Execute one shutdown operation.

            Returns True only when the operation completed successfully.
            Cancellation is recorded and deferred until remaining cleanup
            operations have been attempted.
            """

            nonlocal cancellation

            if callback is None:
                return True

            try:
                await self._invoke(callback)
                return True

            except asyncio.CancelledError as exc:
                if cancellation is None:
                    cancellation = exc

                logger.warning(
                    "Cancellation received during %s; "
                    "continuing scheduler cleanup",
                    description,
                )
                return False

            except Exception as exc:
                errors.append(exc)

                logger.exception(
                    "Scheduling shutdown operation failed: %s",
                    description,
                )
                return False

        await invoke_cleanup(
            self._before_shutdown,
            description="pre-shutdown callback",
        )

        if self._monitor_started and self._health_monitor is not None:
            stopped = await invoke_cleanup(
                self._health_monitor.stop,
                description="health monitor shutdown",
            )

            if stopped:
                self._monitor_started = False

        if self._manager_started:
            stopped = await invoke_cleanup(
                self._manager.shutdown,
                description="scheduler manager shutdown",
            )

            if stopped:
                self._manager_started = False

        await invoke_cleanup(
            self._after_shutdown,
            description="post-shutdown callback",
        )

        if cancellation is not None:
            self._state = SchedulerLifecycleState.FAILED
            self._last_error = "Shutdown interrupted by cancellation"

            if errors:
                self._last_error += ": " + "; ".join(
                    self._describe_error(error) for error in errors
                )

            raise cancellation

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

    async def _rollback_startup(self) -> None:
        """
        Attempt cleanup after an unsuccessful startup.

        Cleanup is best-effort. Component flags remain set when cleanup
        fails, allowing a subsequent shutdown call to retry.
        """

        if self._monitor_started and self._health_monitor is not None:
            try:
                await self._invoke(self._health_monitor.stop)
                self._monitor_started = False

            except BaseException:
                logger.exception(
                    "Failed to stop health monitor during startup rollback"
                )

        if self._manager_started:
            try:
                await self._invoke(self._manager.shutdown)
                self._manager_started = False

            except BaseException:
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
        """Return a concise description of an exception."""

        return f"{type(error).__name__}: {error}"
