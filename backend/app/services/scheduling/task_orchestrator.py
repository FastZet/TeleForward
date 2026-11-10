"""Orchestration layer for scheduled task registration."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from app.services.scheduling.task_config import ScheduledTaskConfig
from app.services.scheduling.task_loader import (
    LoadedScheduledTask,
    TaskLoader,
)


RegistrationCallback = Callable[
    [LoadedScheduledTask],
    Awaitable[None] | None,
]


@dataclass(frozen=True, slots=True)
class TaskRegistrationResult:
    """Summary of a task registration operation."""

    registered: tuple[str, ...]
    failed_task: str | None = None
    error: str | None = None

    @property
    def success(self) -> bool:
        return self.failed_task is None


class TaskOrchestrator:
    """Load and register scheduled tasks through an injected callback."""

    def __init__(
        self,
        loader: TaskLoader,
        register_callback: RegistrationCallback,
    ) -> None:
        if not isinstance(loader, TaskLoader):
            raise TypeError("loader must be a TaskLoader instance")

        if not callable(register_callback):
            raise TypeError("register_callback must be callable")

        self._loader = loader
        self._register_callback = register_callback

    async def register_one(
        self,
        configuration: ScheduledTaskConfig | Mapping[str, Any],
    ) -> TaskRegistrationResult:
        """Load and register one scheduled task."""

        loaded = self._loader.load_one(configuration)

        try:
            await self._register(loaded)
        except Exception as exc:
            return TaskRegistrationResult(
                registered=(),
                failed_task=loaded.config.task_name,
                error=f"{type(exc).__name__}: {exc}",
            )

        return TaskRegistrationResult(
            registered=(loaded.config.task_name,),
        )

    async def register_many(
        self,
        configurations: Iterable[
            ScheduledTaskConfig | Mapping[str, Any]
        ],
    ) -> TaskRegistrationResult:
        """Validate all configurations, then register tasks sequentially.

        Configuration loading is completed before registration begins.
        Registration itself is not transactional: if a callback fails,
        previously registered tasks remain registered.
        """

        loaded_tasks = self._loader.load(configurations)

        registered: list[str] = []

        for loaded in loaded_tasks:
            try:
                await self._register(loaded)
            except Exception as exc:
                return TaskRegistrationResult(
                    registered=tuple(registered),
                    failed_task=loaded.config.task_name,
                    error=f"{type(exc).__name__}: {exc}",
                )

            registered.append(loaded.config.task_name)

        return TaskRegistrationResult(
            registered=tuple(registered),
        )

    async def _register(
        self,
        loaded: LoadedScheduledTask,
    ) -> None:
        """Invoke the configured registration callback."""

        result = self._register_callback(loaded)

        if inspect.isawaitable(result):
            await result
