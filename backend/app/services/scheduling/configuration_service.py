"""Application service for scheduled-task configuration management."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.services.scheduling.configuration import (
    ScheduledTaskConfigurationSet,
)
from app.services.scheduling.configuration_applier import (
    ConfigurationApplier,
    ConfigurationApplyResult,
)
from app.services.scheduling.configuration_manager import (
    ConfigurationManager,
)
from app.services.scheduling.configuration_sync import (
    ConfigurationSynchronizer,
    ConfigurationSyncPlan,
)
from app.services.scheduling.task_config import ScheduledTaskConfig


class ConfigurationService:
    """Coordinate scheduled-task configuration lifecycle operations."""

    def __init__(
        self,
        manager: ConfigurationManager,
        synchronizer: ConfigurationSynchronizer,
        applier: ConfigurationApplier,
    ) -> None:
        if not isinstance(manager, ConfigurationManager):
            raise TypeError(
                "manager must be a ConfigurationManager"
            )

        if not isinstance(
            synchronizer,
            ConfigurationSynchronizer,
        ):
            raise TypeError(
                "synchronizer must be a ConfigurationSynchronizer"
            )

        if not isinstance(applier, ConfigurationApplier):
            raise TypeError(
                "applier must be a ConfigurationApplier"
            )

        self._manager = manager
        self._synchronizer = synchronizer
        self._applier = applier

    def load(
        self,
        path: str | Path,
    ) -> ScheduledTaskConfigurationSet:
        """Load and activate a configuration file."""

        return self._manager.load_file(path)

    def replace(
        self,
        configuration: ScheduledTaskConfigurationSet,
    ) -> ScheduledTaskConfigurationSet:
        """Replace the active configuration snapshot."""

        return self._manager.replace(configuration)

    def get_current(
        self,
    ) -> ScheduledTaskConfigurationSet | None:
        """Return the active configuration snapshot."""

        return self._manager.get_current()

    def get_task(
        self,
        task_name: str,
    ) -> ScheduledTaskConfig | None:
        """Return one configured task."""

        return self._manager.get_task(task_name)

    async def plan_sync(
        self,
    ) -> ConfigurationSyncPlan:
        """Generate a reconciliation plan without modifying jobs."""

        configuration = self._manager.get_current()

        if configuration is None:
            raise RuntimeError(
                "No scheduled-task configuration has been loaded"
            )

        return await self._synchronizer.create_plan(configuration)

    async def apply_sync(
        self,
        plan: ConfigurationSyncPlan,
    ) -> ConfigurationApplyResult:
        """Apply a previously generated reconciliation plan."""

        return await self._applier.apply(plan)

    async def synchronize(self) -> ConfigurationApplyResult:
        """Generate and apply a reconciliation plan."""

        plan = await self.plan_sync()
        return await self.apply_sync(plan)

    def status(self) -> dict[str, Any]:
        """Return a summary of the active configuration."""

        configuration = self._manager.get_current()

        return {
            "loaded": configuration is not None,
            "source": (
                str(self._manager.get_source())
                if self._manager.get_source() is not None
                else None
            ),
            "total_tasks": (
                len(configuration)
                if configuration is not None
                else 0
            ),
            "enabled_tasks": len(
                self._manager.get_enabled()
            ),
            "disabled_tasks": len(
                self._manager.get_disabled()
            ),
        }
