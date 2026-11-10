
"""Protected diagnostic routes for scheduling configuration API security."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.services.scheduling.configuration_api_security_integration import (
    validate_configuration_api_request,
)
from app.services.scheduling.configuration_permissions import (
    ConfigurationPermission,
    ConfigurationPermissionService,
    ConfigurationPrincipal,
)


logger = logging.getLogger(__name__)


class ConfigurationSecurityStatusResponse(BaseModel):
    """Public security integration status."""

    model_config = ConfigDict(extra="forbid")

    configured: bool
    principal_authenticated: bool
    principal_active: bool


class ConfigurationPermissionItem(BaseModel):
    """Permission information for a single permission."""

    model_config = ConfigDict(extra="forbid")

    permission: str
    granted: bool


class ConfigurationPrincipalPermissionsResponse(BaseModel):
    """Permission inspection response for the authenticated principal."""

    model_config = ConfigDict(extra="forbid")

    active: bool
    permissions: list[ConfigurationPermissionItem] = Field(
        default_factory=list
    )


def create_configuration_security_router(
    *,
    permission_service: ConfigurationPermissionService,
    prefix: str = "/configuration/security",
    tags: list[str] | None = None,
) -> APIRouter:
    """Create routes for inspecting configuration API security.

    The returned router must be mounted on an application where
    configuration API security has already been installed.

    Args:
        permission_service: Permission evaluation service.
        prefix: Router URL prefix.
        tags: Optional OpenAPI tags.
    """

    if not isinstance(
        permission_service,
        ConfigurationPermissionService,
    ):
        raise TypeError(
            "permission_service must be a ConfigurationPermissionService"
        )

    if not isinstance(prefix, str) or not prefix.startswith("/"):
        raise ValueError("prefix must be an absolute route prefix")

    if prefix == "/":
        raise ValueError("prefix must not be the root path")

    router = APIRouter(
        prefix=prefix.rstrip("/"),
        tags=tags or ["Configuration Security"],
    )

    async def authenticated_principal(
        request: Request,
        _: Any = Depends(validate_configuration_api_request),
    ) -> ConfigurationPrincipal:
        """Resolve the authenticated principal after security validation."""

        from app.services.scheduling.configuration_api_security_integration import (
            resolve_configuration_api_principal,
        )

        return await resolve_configuration_api_principal(request)

    @router.get(
        "/status",
        response_model=ConfigurationSecurityStatusResponse,
        summary="Get configuration API security status",
    )
    async def get_security_status(
        principal: ConfigurationPrincipal = Depends(
            authenticated_principal
        ),
    ) -> ConfigurationSecurityStatusResponse:
        """Return non-sensitive security status for the current principal."""

        return ConfigurationSecurityStatusResponse(
            configured=True,
            principal_authenticated=True,
            principal_active=principal.is_active,
        )

    @router.get(
        "/permissions",
        response_model=ConfigurationPrincipalPermissionsResponse,
        summary="Inspect current principal permissions",
    )
    async def get_principal_permissions(
        principal: ConfigurationPrincipal = Depends(
            authenticated_principal
        ),
    ) -> ConfigurationPrincipalPermissionsResponse:
        """Return effective permissions for the authenticated principal."""

        try:
            permissions = permission_service.get_permissions(
                principal
            )

            items = [
                ConfigurationPermissionItem(
                    permission=permission.value,
                    granted=True,
                )
                for permission in sorted(
                    permissions,
                    key=lambda item: item.value,
                )
            ]

            return ConfigurationPrincipalPermissionsResponse(
                active=principal.is_active,
                permissions=items,
            )

        except Exception as exc:
            logger.exception(
                "Unable to inspect configuration permissions"
            )

            raise HTTPException(
                status_code=500,
                detail="Unable to inspect configuration permissions",
            ) from exc

    return router


__all__ = [
    "ConfigurationSecurityStatusResponse",
    "ConfigurationPermissionItem",
    "ConfigurationPrincipalPermissionsResponse",
    "create_configuration_security_router",
]
