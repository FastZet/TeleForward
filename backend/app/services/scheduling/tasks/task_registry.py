"""Registry for TeleForward scheduled task instances."""

from __future__ import annotations

from collections.abc import Iterable
from threading import RLock

from app.services.scheduling.base import BaseScheduledTask


class ScheduledTaskRegistry:
    """Manage registered scheduled task instances."""

    def __init__(self) -> None:
        self._tasks: dict[str, BaseScheduledTask] = {}
        self._lock = RLock()

    @staticmethod
    def _normalise_name(name: str) -> str:
        """Validate and normalise a task name."""

        if not isinstance(name, str):
            raise TypeError("Task name must be a string")

        normalised = name.strip().lower()

        if not normalised:
            raise ValueError("Task name cannot be empty")

        return normalised

    @staticmethod
    def _validate_task(
        task: BaseScheduledTask,
    ) -> None:
        """Validate a scheduled task instance."""

        if not isinstance(task, BaseScheduledTask):
            raise TypeError(
                "task must be an instance of BaseScheduledTask"
            )

        ScheduledTaskRegistry._normalise_name(task.name)

    def register(
        self,
        task: BaseScheduledTask,
        *,
        replace: bool = False,
    ) -> None:
        """Register a task instance."""

        self._validate_task(task)
        name = self._normalise_name(task.name)

        with self._lock:
            if name in self._tasks and not replace:
                raise ValueError(
                    f"Scheduled task {name!r} is already registered"
                )

            self._tasks[name] = task

    def register_many(
        self,
        tasks: Iterable[BaseScheduledTask],
        *,
        replace: bool = False,
    ) -> None:
        """Register multiple tasks atomically."""

        if isinstance(tasks, (str, bytes)):
            raise TypeError("tasks must be an iterable of task instances")

        validated: dict[str, BaseScheduledTask] = {}

        for task in tasks:
            self._validate_task(task)
            name = self._normalise_name(task.name)

            if name in validated:
                raise ValueError(
                    f"Duplicate task name in registration batch: {name!r}"
                )

            validated[name] = task

        with self._lock:
            if not replace:
                duplicates = set(validated).intersection(self._tasks)

                if duplicates:
                    names = ", ".join(sorted(duplicates))
                    raise ValueError(
                        f"Scheduled tasks already registered: {names}"
                    )

            self._tasks.update(validated)

    def get(self, name: str) -> BaseScheduledTask:
        """Retrieve a registered task."""

        normalised = self._normalise_name(name)

        with self._lock:
            task = self._tasks.get(normalised)

            if task is None:
                raise KeyError(
                    f"Scheduled task {normalised!r} is not registered"
                )

            return task

    def get_optional(
        self,
        name: str,
    ) -> BaseScheduledTask | None:
        """Retrieve a task without raising when it is absent."""

        normalised = self._normalise_name(name)

        with self._lock:
            return self._tasks.get(normalised)

    def unregister(self, name: str) -> BaseScheduledTask:
        """Remove and return a registered task."""

        normalised = self._normalise_name(name)

        with self._lock:
            try:
                return self._tasks.pop(normalised)
            except KeyError:
                raise KeyError(
                    f"Scheduled task {normalised!r} is not registered"
                ) from None

    def contains(self, name: str) -> bool:
        """Check whether a task is registered."""

        normalised = self._normalise_name(name)

        with self._lock:
            return normalised in self._tasks

    def names(self) -> tuple[str, ...]:
        """Return registered task names."""

        with self._lock:
            return tuple(sorted(self._tasks))

    def get_all(self) -> tuple[BaseScheduledTask, ...]:
        """Return a snapshot of registered task instances."""

        with self._lock:
            return tuple(self._tasks.values())

    def clear(self) -> None:
        """Remove all registered tasks."""

        with self._lock:
            self._tasks.clear()

    def __contains__(self, name: object) -> bool:
        if not isinstance(name, str):
            return False

        try:
            return self.contains(name)
        except ValueError:
            return False

    def __len__(self) -> int:
        with self._lock:
            return len(self._tasks)

    def __iter__(self):
        return iter(self.get_all())
