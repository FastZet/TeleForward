
"""Runtime facade for the scheduling subsystem."""

from __future__ import annotations

import inspect
import logging
from typing import Any, Iterable

from app.services.scheduling.scheduler_lifecycle import (
    SchedulerLifecycle,
    SchedulerLifecycleState,
)

from app.services.scheduling.tasks.task_registry import (
    ScheduledTaskRegistry,
)

logger = logging.getLogger(__name__)


class SchedulerRuntimeError(RuntimeError):
    """Raised when scheduler runtime operations fail."""


class SchedulerRuntime:
    """
    Coordinate the scheduling subsystem through a single runtime facade.

    Responsibilities:
        - Manage scheduler lifecycle.
        - Register and retrieve scheduled tasks.
        - Delegate job operations to SchedulingManager.
        - Expose runtime health and lifecycle state.
        - Provide a consistent application-facing interface.

    The runtime does not implement job persistence or task execution itself.
    Those responsibilities remain with the scheduler manager and its
    associated services.
    """

    def __init__(
        self,
        manager: Any,
        task_registry: ScheduledTaskRegistry,
        *,
        health_monitor: Any | None = None,
        lifecycle: SchedulerLifecycle | None = None,
        before_start: Any | None = None,
        after_start: Any | None = None,
        before_shutdown: Any | None = None,
        after_shutdown: Any | None = None,
        monitor_run_immediately: bool = True,
    ) -> None:
        if manager is None:
            raise ValueError("manager is required")

        if not isinstance(task_registry, ScheduledTaskRegistry):
            raise TypeError(
                "task_registry must be a ScheduledTaskRegistry instance"
            )

        self._manager = manager
        self._task_registry = task_registry

        if lifecycle is not None and not isinstance(
            lifecycle,
            SchedulerLifecycle,
        ):
            raise TypeError(
                "lifecycle must be a SchedulerLifecycle instance"
            )

        if lifecycle is not None and any(
            callback is not None
            for callback in (
                before_start,
                after_start,
                before_shutdown,
                after_shutdown,
            )
        ):
            raise ValueError(
                "Lifecycle callbacks cannot be supplied when "
                "an existing lifecycle instance is provided"
            )

        if lifecycle is not None and health_monitor is not None:
            raise ValueError(
                "health_monitor cannot be supplied alongside an "
                "existing lifecycle instance"
            )

        self._lifecycle = lifecycle or SchedulerLifecycle(
            manager,
            health_monitor=health_monitor,
            before_start=before_start,
            after_start=after_start,
            before_shutdown=before_shutdown,
            after_shutdown=after_shutdown,
            monitor_run_immediately=monitor_run_immediately,
        )

    @property
    def manager(self) -> Any:
        """Return the underlying scheduler manager."""

        return self._manager

    @property
    def task_registry(self) -> ScheduledTaskRegistry:
        """Return the scheduled-task registry."""

        return self._task_registry

    @property
    def lifecycle(self) -> SchedulerLifecycle:
        """Return the lifecycle coordinator."""

        return self._lifecycle

    @property
    def state(self) -> SchedulerLifecycleState:
        """Return the current runtime lifecycle state."""

        return self._lifecycle.state

    @property
    def is_running(self) -> bool:
        """Return whether the runtime is fully running."""

        return self._lifecycle.is_running

    @property
    def last_error(self) -> str | None:
        """Return the most recent lifecycle error."""

        return self._lifecycle.last_error

    async def start(self) -> None:
        """Start the complete scheduling runtime."""

        try:
            await self._lifecycle.start()
        except Exception:
            logger.exception("Failed to start scheduler runtime")
            raise

    async def shutdown(self) -> None:
        """Gracefully stop the scheduling runtime."""

        try:
            await self._lifecycle.shutdown()
        except Exception:
            logger.exception("Failed to shut down scheduler runtime")
            raise

    async def restart(self) -> None:
        """Restart the scheduling runtime."""

        try:
            await self._lifecycle.restart()
        except Exception:
            logger.exception("Failed to restart scheduler runtime")
            raise

    def register_task(self, task: Any) -> None:
        """
        Register one scheduled task.

        Registration is delegated to ScheduledTaskRegistry, which performs
        task validation and duplicate-name checks.
        """

        self._task_registry.register(task)

    def register_tasks(self, tasks: Iterable[Any]) -> None:
        """
        Register multiple scheduled tasks.

        The registry is responsible for validating the batch and applying
        its duplicate-registration policy.
        """

        self._task_registry.register_many(tasks)

    def get_task(self, task_name: str) -> Any:
        """Retrieve a registered task by name."""

        task = self._task_registry.get_optional(task_name)

        if task is None:
            raise SchedulerRuntimeError(
                f"Scheduled task is not registered: {task_name}"
            )

        return task

    def get_task_optional(self, task_name: str) -> Any | None:
        """Retrieve a registered task, returning None when absent."""

        return self._task_registry.get_optional(task_name)

    def unregister_task(self, task_name: str) -> Any:
        """Remove a task from the registry."""

        task = self._task_registry.get_optional(task_name)

        if task is None:
            raise SchedulerRuntimeError(
                f"Scheduled task is not registered: {task_name}"
            )

        self._task_registry.unregister(task_name)

        return task

    def has_task(self, task_name: str) -> bool:
        """Check whether a task is registered."""

        return self._task_registry.contains(task_name)

    def get_registered_task_names(self) -> tuple[str, ...]:
        """Return the names of all registered tasks."""

        return self._task_registry.names()

    def get_registered_tasks(self) -> tuple[Any, ...]:
        """Return all registered task instances."""

        return tuple(self._task_registry.get_all())

    async def create_job(self, *args: Any, **kwargs: Any) -> Any:
        """Create a scheduled job through the scheduler manager."""

        return await self._call_manager("create_job", *args, **kwargs)

    async def update_job(self, *args: Any, **kwargs: Any) -> Any:
        """Update a scheduled job through the scheduler manager."""

        return await self._call_manager("update_job", *args, **kwargs)

    async def delete_job(self, *args: Any, **kwargs: Any) -> Any:
        """Delete a scheduled job through the scheduler manager."""

        return await self._call_manager("delete_job", *args, **kwargs)

    async def enable_job(self, *args: Any, **kwargs: Any) -> Any:
        """Enable a scheduled job through the scheduler manager."""

        return await self._call_manager("enable_job", *args, **kwargs)

    async def disable_job(self, *args: Any, **kwargs: Any) -> Any:
        """Disable a scheduled job through the scheduler manager."""

        return await self._call_manager("disable_job", *args, **kwargs)

    async def list_jobs(self, *args: Any, **kwargs: Any) -> Any:
        """List scheduled jobs through the scheduler manager."""

        return await self._call_manager("list_jobs", *args, **kwargs)

    async def restore_jobs(self, *args: Any, **kwargs: Any) -> Any:
        """Restore persisted scheduled jobs through the manager."""

        return await self._call_manager("restore_jobs", *args, **kwargs)

    async def _call_manager(
        self,
        method_name: str,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """
        Delegate an operation to the scheduler manager.

        Both synchronous and asynchronous manager methods are supported.
        Missing methods produce an explicit runtime error.
        """

        method = getattr(self._manager, method_name, None)

        if not callable(method):
            raise SchedulerRuntimeError(
                f"Scheduler manager does not implement {method_name}()"
            )

        try:
            result = method(*args, **kwargs)

            if inspect.isawaitable(result):
                return await result

            return result

        except SchedulerRuntimeError:
            raise

        except Exception as exc:
            logger.exception(
                "Scheduler manager operation failed: %s",
                method_name,
            )

            raise SchedulerRuntimeError(
                f"Scheduler operation failed: {method_name}"
            ) from exc

    def get_status(self) -> dict[str, Any]:
        """
        Return a lightweight runtime status snapshot.

        This is an in-process snapshot, not a complete scheduler health
        report. Detailed health checks belong to SchedulerHealthService.
        """

        return {
            "state": self.state.value,
            "is_running": self.is_running,
            "last_error": self.last_error,
            "manager_started": self._lifecycle.manager_started,
            "monitor_started": self._lifecycle.monitor_started,
            "registered_task_count": len(
                self._task_registry.get_all()
            ),
            "registered_task_names": list(
                self._task_registry.names()
            ),
        }
