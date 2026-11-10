"""Configuration collection for TeleForward scheduled tasks."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from app.services.scheduling.task_config import ScheduledTaskConfig


@dataclass(frozen=True, slots=True)
class ScheduledTaskConfigurationSet:
    """Validated collection of scheduled task configurations."""

    configurations: tuple[ScheduledTaskConfig, ...]

    def __post_init__(self) -> None:
        """Validate configuration types and unique task names."""

        if not isinstance(self.configurations, tuple):
            raise TypeError(
                "configurations must be a tuple of ScheduledTaskConfig objects"
            )

        names: set[str] = set()

        for config in self.configurations:
            if not isinstance(config, ScheduledTaskConfig):
                raise TypeError(
                    "Every configuration must be a ScheduledTaskConfig"
                )

            if config.task_name in names:
                raise ValueError(
                    f"Duplicate scheduled task configuration: "
                    f"{config.task_name!r}"
                )

            names.add(config.task_name)

    @classmethod
    def from_iterable(
        cls,
        configurations: Iterable[
            ScheduledTaskConfig | Mapping[str, Any]
        ],
    ) -> ScheduledTaskConfigurationSet:
        """Build a validated configuration set from mappings or models."""

        if isinstance(configurations, (str, bytes, Mapping)):
            raise TypeError(
                "configurations must be an iterable of task configurations"
            )

        normalised: list[ScheduledTaskConfig] = []

        for index, configuration in enumerate(configurations):
            try:
                if isinstance(configuration, ScheduledTaskConfig):
                    config = configuration
                elif isinstance(configuration, Mapping):
                    config = ScheduledTaskConfig.from_dict(configuration)
                else:
                    raise TypeError(
                        "Expected ScheduledTaskConfig or mapping"
                    )
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"Invalid scheduled task configuration at index "
                    f"{index}: {exc}"
                ) from exc

            normalised.append(config)

        return cls(configurations=tuple(normalised))

    def get(self, task_name: str) -> ScheduledTaskConfig | None:
        """Return a configuration by normalised task name."""

        if not isinstance(task_name, str):
            raise TypeError("task_name must be a string")

        normalised_name = task_name.strip().lower()

        for config in self.configurations:
            if config.task_name == normalised_name:
                return config

        return None

    def enabled(self) -> tuple[ScheduledTaskConfig, ...]:
        """Return only enabled task configurations."""

        return tuple(
            config
            for config in self.configurations
            if config.enabled
        )

    def disabled(self) -> tuple[ScheduledTaskConfig, ...]:
        """Return only disabled task configurations."""

        return tuple(
            config
            for config in self.configurations
            if not config.enabled
        )

    def to_list(self) -> list[dict[str, Any]]:
        """Return configurations as serialisable dictionaries."""

        return [
            config.to_dict()
            for config in self.configurations
        ]

    def __len__(self) -> int:
        return len(self.configurations)

    def __iter__(self):
        return iter(self.configurations)
