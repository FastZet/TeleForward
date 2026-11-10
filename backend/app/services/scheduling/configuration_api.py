"""FastAPI endpoints for scheduled-task configuration management."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field

from app.services.scheduling.configuration import (
    ScheduledTaskConfigurationSet,
)
from app.services.scheduling.configuration_applier import (
    ConfigurationApplier,
)
from app.services.scheduling.configuration_manager import (
    ConfigurationManager,
)
from app.services.scheduling.configuration_permissions import (
    ConfigurationPermission,
    ConfigurationPermissionService,
    ConfigurationPrincipal,
)
from app.services.scheduling.configuration_policy import (
    ConfigurationPolicyError,
    ConfigurationPolicyService,
)
from app.services.scheduling.configuration_sync import (
    ConfigurationSynchronizer,
)


logger = logging.getLogger(__name__)


class ConfigurationTaskResponse(BaseModel):
    """Public representation of a scheduled task configuration."""

    model_config = ConfigDict(extra="forbid")

    task_name: str
    trigger_type: str
    trigger_config: dict[str, Any]
    enabled: bool
    max_instances: int
    coalesce: bool
    misfire_grace_time: int | None
    timeout_seconds: float | None


class ConfigurationStatusResponse(BaseModel):
    """Summary of the active scheduling configuration."""

    loaded: bool
    total_tasks: int
    enabled_tasks: int
    disabled_tasks: int
    tasks: list[ConfigurationTaskResponse]


class ConfigurationSyncPreviewResponse(BaseModel):
    """Preview of scheduler reconciliation operations."""

    creates: list[str]
    updates: list[str]
    deletes: list[str]
    unchanged: list[str]


class ConfigurationSyncResponse(BaseModel):
    """Outcome of scheduler reconciliation."""

    success: bool
    created: list[str]
    updated: list[str]
    deleted: list[str]
    failures: list[dict[str, str]]


class ConfigurationApiDependencies:
    """Dependencies required by the configuration API."""

    def __init__(
        self,
        manager: ConfigurationManager,
        synchronizer: ConfigurationSynchronizer,
        applier: ConfigurationApplier,
        permission_service: ConfigurationPermissionService,
        policy_service: ConfigurationPolicyService,
    ) -> None:
        self.manager = manager
        self.synchronizer = synchronizer
        self.applier = applier
        self.permission_service = permission_service
        self.policy_service = policy_service


def create_configuration_router(
    dependencies: ConfigurationApiDependencies,
    *,
    principal_dependency: Any,
) -> APIRouter:
    """Create the configuration API router."""

    if not isinstance(
        dependencies,
        ConfigurationApiDependencies,
    ):
        raise TypeError(
            "dependencies must be ConfigurationApiDependencies"
        )

    if not callable(principal_dependency):
        raise TypeError("principal_dependency must be callable")

    router = APIRouter(
        prefix="/scheduling/configuration",
        tags=["Scheduling Configuration"],
    )

    async def get_principal(
        principal: ConfigurationPrincipal = Depends(
            principal_dependency
        ),
    ) -> ConfigurationPrincipal:
        if not isinstance(principal, ConfigurationPrincipal):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authenticated principal",
            )

        return principal

    def require_permission(
        principal: ConfigurationPrincipal,
        permission: ConfigurationPermission,
    ) -> None:
        result = dependencies.permission_service.check(
            principal,
            permission,
        )

        if not result.allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=result.reason,
            )

    def get_configuration() -> ScheduledTaskConfigurationSet:
        configuration = dependencies.manager.get_current()

        if configuration is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No scheduling configuration is loaded",
            )

        return configuration

    @router.get(
        "",
        response_model=ConfigurationStatusResponse,
    )
    async def get_configuration_status(
        principal: ConfigurationPrincipal = Depends(get_principal),
    ) -> ConfigurationStatusResponse:
        require_permission(
            principal,
            ConfigurationPermission.VIEW_CONFIGURATION,
        )

        configuration = get_configuration()
        tasks = configuration.to_list()

        return ConfigurationStatusResponse(
            loaded=True,
            total_tasks=len(tasks),
            enabled_tasks=sum(
                1 for task in tasks if task.enabled
            ),
            disabled_tasks=sum(
                1 for task in tasks if not task.enabled
            ),
            tasks=[
                ConfigurationTaskResponse(
                    task_name=task.task_name,
                    trigger_type=task.trigger_type.value,
                    trigger_config=dict(task.trigger_config),
                    enabled=task.enabled,
                    max_instances=task.max_instances,
                    coalesce=task.coalesce,
                    misfire_grace_time=task.misfire_grace_time,
                    timeout_seconds=task.timeout_seconds,
                )
                for task in tasks
            ],
        )

    @router.get(
        "/tasks/{task_name}",
        response_model=ConfigurationTaskResponse,
    )
    async def get_task_configuration(
        task_name: str,
        principal: ConfigurationPrincipal = Depends(get_principal),
    ) -> ConfigurationTaskResponse:
        require_permission(
            principal,
            ConfigurationPermission.VIEW_CONFIGURATION,
        )

        task = dependencies.manager.get_task(task_name)

        if task is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Task configuration '{task_name}' was not found",
            )

        return ConfigurationTaskResponse(
            task_name=task.task_name,
            trigger_type=task.trigger_type.value,
            trigger_config=dict(task.trigger_config),
            enabled=task.enabled,
            max_instances=task.max_instances,
            coalesce=task.coalesce,
            misfire_grace_time=task.misfire_grace_time,
            timeout_seconds=task.timeout_seconds,
        )

    @router.get(
        "/preview",
        response_model=ConfigurationSyncPreviewResponse,
    )
    async def preview_synchronization(
        principal: ConfigurationPrincipal = Depends(get_principal),
    ) -> ConfigurationSyncPreviewResponse:
        require_permission(
            principal,
            ConfigurationPermission.PREVIEW_SYNCHRONIZATION,
        )

        configuration = get_configuration()

        try:
            plan = await dependencies.synchronizer.create_plan(
                configuration
            )
        except Exception as exc:
            logger.exception(
                "Unable to generate scheduling configuration preview"
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Unable to generate synchronization preview",
            ) from exc

        return ConfigurationSyncPreviewResponse(
            creates=list(plan.creates),
            updates=list(plan.updates),
            deletes=list(plan.deletes),
            unchanged=list(plan.unchanged),
        )

    @router.post(
        "/synchronize",
        response_model=ConfigurationSyncResponse,
    )
    async def synchronize_configuration(
        principal: ConfigurationPrincipal = Depends(get_principal),
    ) -> ConfigurationSyncResponse:
        require_permission(
            principal,
            ConfigurationPermission.APPLY_SYNCHRONIZATION,
        )

        configuration = get_configuration()

        try:
            dependencies.policy_service.enforce(configuration)

            plan = await dependencies.synchronizer.create_plan(
                configuration
            )

            result = await dependencies.applier.apply(plan)

        except ConfigurationPolicyError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=exc.result.to_dict(),
            ) from exc

        except Exception as exc:
            logger.exception(
                "Scheduling configuration synchronization failed"
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Scheduling configuration synchronization failed",
            ) from exc

        return ConfigurationSyncResponse(
            success=result.success,
            created=list(result.created),
            updated=list(result.updated),
            deleted=list(result.deleted),
            failures=[
                {
                    "operation": failure.operation,
                    "target": failure.target,
                    "error_type": failure.error_type,
                    "message": failure.message,
                }
                for failure in result.failures
            ],
        )

    return router
