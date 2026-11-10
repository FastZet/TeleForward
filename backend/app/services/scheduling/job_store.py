"""Scheduled job definition storage for TeleForward."""

from __future__ import annotations

from abc import ABC, abstractmethod
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Mapping


class ScheduledJobType(StrEnum):
    """Supported scheduling trigger types."""

    INTERVAL = "interval"
    CRON = "cron"
    DATE = "date"


@dataclass(frozen=True, slots=True)
class ScheduledJobDefinition:
    """Serializable definition of a scheduled job."""

    job_id: str
    task_name: str
    trigger_type: ScheduledJobType
    trigger_config: Mapping[str, Any]
    enabled: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    updated_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    def __post_init__(self) -> None:
        if not isinstance(self.job_id, str) or not self.job_id.strip():
            raise ValueError("job_id cannot be empty")

        if not isinstance(self.task_name, str) or not self.task_name.strip():
            raise ValueError("task_name cannot be empty")

        if not isinstance(self.trigger_type, ScheduledJobType):
            raise TypeError("trigger_type must be a ScheduledJobType")

        if not isinstance(self.trigger_config, Mapping):
            raise TypeError("trigger_config must be a mapping")

        if not isinstance(self.metadata, Mapping):
            raise TypeError("metadata must be a mapping")

        if self.created_at.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")

        if self.updated_at.tzinfo is None:
            raise ValueError("updated_at must be timezone-aware")

        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot precede created_at")

        self._validate_trigger_config()

        # Prevent callers from mutating the original dictionaries after
        # constructing a definition. Nested values are copied as well.
        object.__setattr__(
            self,
            "trigger_config",
            deepcopy(dict(self.trigger_config)),
        )
        object.__setattr__(
            self,
            "metadata",
            deepcopy(dict(self.metadata)),
        )

    def _validate_trigger_config(self) -> None:
        """Validate the minimum configuration required by each trigger."""

        config = self.trigger_config

        if self.trigger_type == ScheduledJobType.INTERVAL:
            interval_fields = (
                "weeks",
                "days",
                "hours",
                "minutes",
                "seconds",
            )

            has_interval = False

            for field_name in interval_fields:
                value = config.get(field_name)

                if value is None:
                    continue

                if isinstance(value, bool) or not isinstance(
                    value, (int, float)
                ):
                    raise ValueError(
                        f"Interval field '{field_name}' must be numeric"
                    )

                if value < 0:
                    raise ValueError(
                        f"Interval field '{field_name}' cannot be negative"
                    )

                if value > 0:
                    has_interval = True

            if not has_interval:
                raise ValueError(
                    "Interval configuration requires a positive interval"
                )

        elif self.trigger_type == ScheduledJobType.CRON:
            expression = config.get("expression")

            if (
                not isinstance(expression, str)
                or not expression.strip()
            ):
                raise ValueError(
                    "Cron configuration requires a non-empty expression"
                )

        elif self.trigger_type == ScheduledJobType.DATE:
            run_date = config.get("run_date")

            if isinstance(run_date, str):
                try:
                    run_date = datetime.fromisoformat(run_date)
                except ValueError as exc:
                    raise ValueError(
                        "run_date must be a valid ISO 8601 datetime"
                    ) from exc

            if not isinstance(run_date, datetime):
                raise ValueError(
                    "Date configuration requires a datetime run_date"
                )

            if run_date.tzinfo is None:
                raise ValueError("run_date must be timezone-aware")


class BaseJobStore(ABC):
    """Abstract storage interface for scheduled job definitions."""

    @abstractmethod
    async def add(
        self,
        definition: ScheduledJobDefinition,
    ) -> None:
        """Persist a new job definition."""

    @abstractmethod
    async def get(
        self,
        job_id: str,
    ) -> ScheduledJobDefinition | None:
        """Retrieve a job definition by its identifier."""

    @abstractmethod
    async def list_all(
        self,
        *,
        enabled_only: bool = False,
    ) -> list[ScheduledJobDefinition]:
        """Return stored job definitions."""

    @abstractmethod
    async def update(
        self,
        definition: ScheduledJobDefinition,
    ) -> None:
        """Replace an existing job definition."""

    @abstractmethod
    async def delete(
        self,
        job_id: str,
    ) -> bool:
        """Delete a job definition.

        Returns True when a definition was deleted.
        """

    @abstractmethod
    async def close(self) -> None:
        """Release storage resources."""


class InMemoryJobStore(BaseJobStore):
    """In-memory job store for development and testing.

    This implementation is not persistent and is not suitable as the
    production source of truth for scheduled jobs.
    """

    def __init__(self) -> None:
        self._definitions: dict[str, ScheduledJobDefinition] = {}

    async def add(
        self,
        definition: ScheduledJobDefinition,
    ) -> None:
        if not isinstance(definition, ScheduledJobDefinition):
            raise TypeError(
                "definition must be a ScheduledJobDefinition"
            )

        if definition.job_id in self._definitions:
            raise ValueError(
                f"Scheduled job already exists: {definition.job_id}"
            )

        self._definitions[definition.job_id] = self._copy_definition(
            definition
        )

    async def get(
        self,
        job_id: str,
    ) -> ScheduledJobDefinition | None:
        self._validate_job_id(job_id)

        definition = self._definitions.get(job_id)

        if definition is None:
            return None

        return self._copy_definition(definition)

    async def list_all(
        self,
        *,
        enabled_only: bool = False,
    ) -> list[ScheduledJobDefinition]:
        definitions = self._definitions.values()

        if enabled_only:
            definitions = (
                definition
                for definition in definitions
                if definition.enabled
            )

        return [
            self._copy_definition(definition)
            for definition in sorted(
                definitions,
                key=lambda item: item.job_id,
            )
        ]

    async def update(
        self,
        definition: ScheduledJobDefinition,
    ) -> None:
        if not isinstance(definition, ScheduledJobDefinition):
            raise TypeError(
                "definition must be a ScheduledJobDefinition"
            )

        if definition.job_id not in self._definitions:
            raise KeyError(
                f"Scheduled job does not exist: {definition.job_id}"
            )

        self._definitions[definition.job_id] = self._copy_definition(
            definition
        )

    async def delete(self, job_id: str) -> bool:
        self._validate_job_id(job_id)

        return self._definitions.pop(job_id, None) is not None

    async def close(self) -> None:
        """No external resources need to be released."""

    @staticmethod
    def _validate_job_id(job_id: str) -> None:
        if not isinstance(job_id, str) or not job_id.strip():
            raise ValueError("job_id cannot be empty")

    @staticmethod
    def _copy_definition(
        definition: ScheduledJobDefinition,
    ) -> ScheduledJobDefinition:
        return ScheduledJobDefinition(
            job_id=definition.job_id,
            task_name=definition.task_name,
            trigger_type=definition.trigger_type,
            trigger_config=deepcopy(dict(definition.trigger_config)),
            enabled=definition.enabled,
            metadata=deepcopy(dict(definition.metadata)),
            created_at=definition.created_at,
            updated_at=definition.updated_at,
        )
