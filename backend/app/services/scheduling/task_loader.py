"""Configuration loader for scheduled task implementations."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from app.services.scheduling.base import BaseScheduledTask
from app.services.scheduling.task_config import ScheduledTaskConfig
from app.services.scheduling.tasks.task_registry import (
    ScheduledTaskRegistry,
)


@dataclass(frozen=True, slots=True)
class LoadedScheduledTask:
    """A resolved task and its validated configuration."""

    task: BaseScheduledTask
    config: ScheduledTaskConfig


class TaskLoader:
    """Validate task configurations and resolve registered task instances."""

    def __init__(
        self,
        registry: ScheduledTaskRegistry,
    ) -> None:
        if not isinstance(registry, ScheduledTaskRegistry):
            raise TypeError(
                "registry must be a ScheduledTaskRegistry instance"
            )

        self._registry = registry

    def load_one(
        self,
        configuration: ScheduledTaskConfig | Mapping[str, Any],
    ) -> LoadedScheduledTask:
        """Load one configuration and resolve its registered task."""

        if isinstance(configuration, ScheduledTaskConfig):
            config = configuration
        elif isinstance(configuration, Mapping):
            config = ScheduledTaskConfig.from_dict(configuration)
        else:
            raise TypeError(
                "configuration must be ScheduledTaskConfig or a mapping"
            )

        task = self._registry.get_optional(config.task_name)

        if task is None:
            raise LookupError(
                f"No scheduled task is registered with name "
                f"{config.task_name!r}"
            )

        return LoadedScheduledTask(
            task=task,
            config=config,
        )

    def load(
        self,
        configurations: Iterable[
            ScheduledTaskConfig | Mapping[str, Any]
        ],
    ) -> list[LoadedScheduledTask]:
        """Load multiple configurations.

        Loading is fail-fast. If any configuration is invalid or refers
        to an unregistered task, no partial result is returned.
        """

        if isinstance(configurations, (str, bytes, Mapping)):
            raise TypeError(
                "configurations must be an iterable of configurations"
            )

        loaded: list[LoadedScheduledTask] = []

        for index, configuration in enumerate(configurations):
            try:
                loaded.append(self.load_one(configuration))
            except (TypeError, ValueError, LookupError) as exc:
                raise ValueError(
                    f"Failed to load scheduled task at index {index}: {exc}"
                ) from exc

        return loaded
