"""File-based loader for scheduled task configurations."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any

from app.services.scheduling.configuration import (
    ScheduledTaskConfigurationSet,
)


class TaskConfigurationLoadError(Exception):
    """Raised when scheduled-task configuration cannot be loaded."""


class TaskConfigurationLoader:
    """Load and validate task configurations from JSON or TOML files."""

    DEFAULT_MAX_FILE_SIZE = 1_048_576  # 1 MiB

    def __init__(
        self,
        *,
        max_file_size: int = DEFAULT_MAX_FILE_SIZE,
    ) -> None:
        if (
            isinstance(max_file_size, bool)
            or not isinstance(max_file_size, int)
            or max_file_size < 1
        ):
            raise ValueError(
                "max_file_size must be a positive integer"
            )

        self._max_file_size = max_file_size

    def load(self, path: str | Path) -> ScheduledTaskConfigurationSet:
        """Load a JSON or TOML configuration file."""

        try:
            config_path = Path(path).expanduser()
        except (TypeError, ValueError) as exc:
            raise TaskConfigurationLoadError(
                "Invalid configuration file path"
            ) from exc

        if not config_path.exists():
            raise TaskConfigurationLoadError(
                f"Configuration file does not exist: {config_path}"
            )

        if not config_path.is_file():
            raise TaskConfigurationLoadError(
                f"Configuration path is not a file: {config_path}"
            )

        try:
            file_size = config_path.stat().st_size
        except OSError as exc:
            raise TaskConfigurationLoadError(
                f"Unable to inspect configuration file: {exc}"
            ) from exc

        if file_size > self._max_file_size:
            raise TaskConfigurationLoadError(
                f"Configuration file exceeds the maximum size "
                f"of {self._max_file_size} bytes"
            )

        suffix = config_path.suffix.lower()

        if suffix not in {".json", ".toml"}:
            raise TaskConfigurationLoadError(
                f"Unsupported configuration format: {suffix!r}. "
                "Supported formats are .json and .toml"
            )

        try:
            content = config_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise TaskConfigurationLoadError(
                f"Unable to read configuration file: {exc}"
            ) from exc

        try:
            data = self._parse(content, suffix)
        except (ValueError, tomllib.TOMLDecodeError) as exc:
            raise TaskConfigurationLoadError(
                f"Invalid {suffix[1:].upper()} configuration: {exc}"
            ) from exc

        return self._build_configuration_set(data)

    @staticmethod
    def _parse(content: str, suffix: str) -> Any:
        """Parse configuration text according to its file extension."""

        if suffix == ".json":
            return json.loads(content)

        if suffix == ".toml":
            return tomllib.loads(content)

        raise ValueError(f"Unsupported configuration format: {suffix}")

    @staticmethod
    def _build_configuration_set(
        data: Any,
    ) -> ScheduledTaskConfigurationSet:
        """Validate the document structure and build its configuration set."""

        if not isinstance(data, dict):
            raise TaskConfigurationLoadError(
                "Configuration document must contain an object"
            )

        unknown_fields = set(data) - {"tasks"}

        if unknown_fields:
            raise TaskConfigurationLoadError(
                "Unknown top-level configuration fields: "
                + ", ".join(sorted(str(field) for field in unknown_fields))
            )

        tasks = data.get("tasks")

        if not isinstance(tasks, list):
            raise TaskConfigurationLoadError(
                "Configuration must contain a 'tasks' array"
            )

        try:
            return ScheduledTaskConfigurationSet.from_iterable(tasks)
        except (TypeError, ValueError) as exc:
            raise TaskConfigurationLoadError(
                f"Task configuration validation failed: {exc}"
            ) from exc
