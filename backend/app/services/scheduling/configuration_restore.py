"""Orchestrated restoration of scheduled-task configuration backups."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.services.scheduling.configuration import (
    ScheduledTaskConfigurationSet,
)
from app.services.scheduling.configuration_applier import (
    ConfigurationApplyResult,
)
from app.services.scheduling.configuration_backup import (
    ConfigurationBackupService,
)
from app.services.scheduling.configuration_manager import (
    ConfigurationManager,
)
from app.services.scheduling.configuration_sync import (
    ConfigurationSynchronizer,
    ConfigurationSyncPlan,
)


@dataclass(frozen=True, slots=True)
class ConfigurationRestoreResult:
    """Outcome of a configuration restoration operation."""

    success: bool
    backup_path: str
    task_count: int
    plan: ConfigurationSyncPlan | None
    apply_result: ConfigurationApplyResult | None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert the restoration result into a serializable mapping."""

        return {
            "success": self.success,
            "backup_path": self.backup_path,
            "task_count": self.task_count,
            "error": self.error,
            "created": (
                list(self.apply_result.created)
                if self.apply_result is not None
                else []
            ),
            "updated": (
                list(self.apply_result.updated)
                if self.apply_result is not None
                else []
            ),
            "deleted": (
                list(self.apply_result.deleted)
                if self.apply_result is not None
                else []
            ),
            "failures": (
                [
                    {
                        "operation": failure.operation,
                        "target": failure.target,
                        "error_type": failure.error_type,
                        "message": failure.message,
                    }
                    for failure in self.apply_result.failures
                ]
                if self.apply_result is not None
                else []
            ),
        }


class ConfigurationRestoreService:
    """Restore configuration backups and reconcile scheduler jobs."""

    def __init__(
        self,
        backup_service: ConfigurationBackupService,
        manager: ConfigurationManager,
        synchronizer: ConfigurationSynchronizer,
        applier: Any,
    ) -> None:
        if not isinstance(
            backup_service,
            ConfigurationBackupService,
        ):
            raise TypeError(
                "backup_service must be a ConfigurationBackupService"
            )

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

        if not callable(getattr(applier, "apply", None)):
            raise TypeError(
                "applier must provide an apply() method"
            )

        self._backup_service = backup_service
        self._manager = manager
        self._synchronizer = synchronizer
        self._applier = applier

    def load_backup(
        self,
        backup_path: str | Path,
    ) -> ScheduledTaskConfigurationSet:
        """Validate and load a backup without activating it."""

        return self._backup_service.restore_backup(backup_path)

    async def preview(
        self,
        backup_path: str | Path,
    ) -> ConfigurationSyncPlan:
        """Preview scheduler changes required by a backup."""

        configuration = self.load_backup(backup_path)

        return await self._synchronizer.create_plan(configuration)

    async def restore(
        self,
        backup_path: str | Path,
    ) -> ConfigurationRestoreResult:
        """Restore a backup and apply its scheduler configuration."""

        path = Path(backup_path).expanduser()

        try:
            configuration = self.load_backup(path)

            plan = await self._synchronizer.create_plan(
                configuration
            )

            apply_result = await self._applier.apply(plan)

            if not apply_result.success:
                return ConfigurationRestoreResult(
                    success=False,
                    backup_path=str(path),
                    task_count=len(configuration),
                    plan=plan,
                    apply_result=apply_result,
                    error=(
                        "Scheduler reconciliation was incomplete; "
                        "the restored configuration was not activated."
                    ),
                )

            self._manager.replace(configuration)

            return ConfigurationRestoreResult(
                success=True,
                backup_path=str(path),
                task_count=len(configuration),
                plan=plan,
                apply_result=apply_result,
            )

        except Exception as exc:
            return ConfigurationRestoreResult(
                success=False,
                backup_path=str(path),
                task_count=0,
                plan=None,
                apply_result=None,
                error=f"{type(exc).__name__}: {exc}",
            )
