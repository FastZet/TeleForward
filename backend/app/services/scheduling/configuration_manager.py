"""Lifecycle management for scheduled-task configurations."""

from __future__ import annotations

from pathlib import Path
from threading import RLock
from typing import Any

from app.services.scheduling.configuration import (
    ScheduledTaskConfigurationSet,
)
from app.services.scheduling.configuration_loader import (
    TaskConfigurationLoader,
)
from app.services.scheduling.configuration_validator import (
    ScheduledTaskConfigurationValidator,
)
from app.services.scheduling.task_config import ScheduledTaskConfig


class ConfigurationManager:
    """Manage validated scheduled-task configuration snapshots."""

    def __init__(
        self,
        loader: TaskConfigurationLoader | None = None,
        validator: ScheduledTaskConfigurationValidator | None = None,
    ) -> None:
        self._loader = loader or TaskConfigurationLoader()
        self._validator = (
            validator or ScheduledTaskConfigurationValidator()
        )

        self._configuration: ScheduledTaskConfigurationSet | None = None
        self._source: Path | None = None
        self._lock = RLock()

    def load_file(
        self,
        path: str | Path,
    ) -> ScheduledTaskConfigurationSet:
        """Load, validate, and activate a configuration file."""

        configuration = self._loader.load(path)
        return self.replace(configuration, source=Path(path).expanduser())

    def replace(
        self,
        configuration: ScheduledTaskConfigurationSet,
        *,
        source: Path | None = None,
    ) -> ScheduledTaskConfigurationSet:
        """Validate and atomically replace the active configuration."""

        if not isinstance(
            configuration,
            ScheduledTaskConfigurationSet,
        ):
            raise TypeError(
                "configuration must be a ScheduledTaskConfigurationSet"
            )

        for index, config in enumerate(configuration):
            try:
                self._validator.validate(config)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"Invalid scheduled-task configuration at index "
                    f"{index} ({config.task_name!r}): {exc}"
                ) from exc

        with self._lock:
            self._configuration = configuration
            self._source = source

        return configuration

    def get_current(
        self,
    ) -> ScheduledTaskConfigurationSet | None:
        """Return the currently active configuration snapshot."""

        with self._lock:
            return self._configuration

    def get_task(
        self,
        task_name: str,
    ) -> ScheduledTaskConfig | None:
        """Look up a task configuration by name."""

        configuration = self.get_current()

        if configuration is None:
            return None

        return configuration.get(task_name)

    def get_enabled(
        self,
    ) -> tuple[ScheduledTaskConfig, ...]:
        """Return all enabled task configurations."""

        configuration = self.get_current()

        if configuration is None:
            return ()

        return configuration.enabled()

    def get_disabled(
        self,
    ) -> tuple[ScheduledTaskConfig, ...]:
        """Return all disabled task configurations."""

        configuration = self.get_current()

        if configuration is None:
            return ()

        return configuration.disabled()

    def get_source(self) -> Path | None:
        """Return the source file of the active configuration."""

        with self._lock:
            return self._source

    def clear(self) -> None:
        """Remove the active configuration snapshot."""

        with self._lock:
            self._configuration = None
            self._source = None

    @property
    def is_loaded(self) -> bool:
        """Whether a configuration snapshot is currently available."""

        with self._lock:
            return self._configuration is not None

    @property
    def task_count(self) -> int:
        """Number of configurations currently loaded."""

        configuration = self.get_current()

        if configuration is None:
            return 0

        return len(configuration)

    def to_dict(self) -> dict[str, Any]:
        """Return a serialisable snapshot of the active configuration."""

        configuration = self.get_current()

        return {
            "loaded": configuration is not None,
            "source": (
                str(self.get_source())
                if self.get_source() is not None
                else None
            ),
            "task_count": (
                len(configuration)
                if configuration is not None
                else 0
            ),
            "tasks": (
                configuration.to_list()
                if configuration is not None
                else []
            ),
        }
