"""Configuration reconciliation for scheduled jobs."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from app.services.scheduling.configuration import (
    ScheduledTaskConfigurationSet,
)
from app.services.scheduling.job_store import (
    BaseJobStore,
    ScheduledJobDefinition,
)
from app.services.scheduling.task_config import ScheduledTaskConfig


@dataclass(frozen=True, slots=True)
class ConfigurationSyncPlan:
    """Describes the changes required to synchronise scheduled jobs."""

    to_create: tuple[ScheduledTaskConfig, ...] = ()
    to_update: tuple[ScheduledTaskConfig, ...] = ()
    to_delete: tuple[str, ...] = ()
    unchanged: tuple[str, ...] = ()

    @property
    def has_changes(self) -> bool:
        return bool(
            self.to_create
            or self.to_update
            or self.to_delete
        )

    @property
    def change_count(self) -> int:
        return (
            len(self.to_create)
            + len(self.to_update)
            + len(self.to_delete)
        )


class ConfigurationSynchronizer:
    """Generate reconciliation plans for scheduled-job definitions."""

    def __init__(self, job_store: BaseJobStore) -> None:
        if not isinstance(job_store, BaseJobStore):
            raise TypeError(
                "job_store must be a BaseJobStore instance"
            )

        self._job_store = job_store

    async def create_plan(
        self,
        configuration: ScheduledTaskConfigurationSet,
    ) -> ConfigurationSyncPlan:
        """Compare active configuration with persisted job definitions."""

        if not isinstance(
            configuration,
            ScheduledTaskConfigurationSet,
        ):
            raise TypeError(
                "configuration must be a ScheduledTaskConfigurationSet"
            )

        definitions = await self._job_store.list_all()

        existing = {
            definition.job_id: definition
            for definition in definitions
        }

        desired = {
            config.task_name: config
            for config in configuration.enabled()
        }

        to_create: list[ScheduledTaskConfig] = []
        to_update: list[ScheduledTaskConfig] = []
        to_delete: list[str] = []
        unchanged: list[str] = []

        for task_name, config in desired.items():
            current = existing.get(task_name)

            if current is None:
                to_create.append(config)
                continue

            if self._config_hash(config) != self._definition_hash(
                current
            ):
                to_update.append(config)
            else:
                unchanged.append(task_name)

        for job_id in existing:
            if job_id not in desired:
                to_delete.append(job_id)

        return ConfigurationSyncPlan(
            to_create=tuple(to_create),
            to_update=tuple(to_update),
            to_delete=tuple(to_delete),
            unchanged=tuple(unchanged),
        )

    @staticmethod
    def _config_hash(config: ScheduledTaskConfig) -> str:
        """Create a stable fingerprint for task configuration."""

        payload = {
            "task_name": config.task_name,
            "trigger_type": config.trigger_type.value,
            "trigger_config": config.trigger_config,
        }

        return ConfigurationSynchronizer._hash(payload)

    @staticmethod
    def _definition_hash(
        definition: ScheduledJobDefinition,
    ) -> str:
        """Create a comparable fingerprint for a persisted definition."""

        payload = {
            "task_name": definition.job_id,
            "trigger_type": definition.trigger_type.value,
            "trigger_config": definition.trigger_config,
        }

        return ConfigurationSynchronizer._hash(payload)

    @staticmethod
    def _hash(payload: dict[str, Any]) -> str:
        """Hash a canonical JSON representation."""

        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
            default=str,
        ).encode("utf-8")

        return hashlib.sha256(encoded).hexdigest()
