"""Role-based permissions for scheduling configuration operations."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable


class ConfigurationRole(StrEnum):
    """Roles supported by the scheduling configuration subsystem."""

    ADMIN = "admin"
    OPERATOR = "operator"
    VIEWER = "viewer"
    SYSTEM = "system"


class ConfigurationPermission(StrEnum):
    """Individual permissions for scheduling operations."""

    VIEW_CONFIGURATION = "configuration:view"
    CREATE_CONFIGURATION = "configuration:create"
    UPDATE_CONFIGURATION = "configuration:update"
    DELETE_CONFIGURATION = "configuration:delete"

    PREVIEW_SYNCHRONIZATION = "synchronization:preview"
    APPLY_SYNCHRONIZATION = "synchronization:apply"

    CREATE_BACKUP = "backup:create"
    VIEW_BACKUPS = "backup:view"
    RESTORE_BACKUP = "backup:restore"
    DELETE_BACKUP = "backup:delete"

    VIEW_AUDIT_LOG = "audit:view"

    MANAGE_POLICIES = "policy:manage"
    MANAGE_PERMISSIONS = "permissions:manage"


_ROLE_PERMISSIONS: dict[
    ConfigurationRole,
    frozenset[ConfigurationPermission],
] = {
    ConfigurationRole.ADMIN: frozenset(
        ConfigurationPermission
    ),

    ConfigurationRole.OPERATOR: frozenset(
        {
            ConfigurationPermission.VIEW_CONFIGURATION,
            ConfigurationPermission.CREATE_CONFIGURATION,
            ConfigurationPermission.UPDATE_CONFIGURATION,
            ConfigurationPermission.PREVIEW_SYNCHRONIZATION,
            ConfigurationPermission.APPLY_SYNCHRONIZATION,
            ConfigurationPermission.CREATE_BACKUP,
            ConfigurationPermission.VIEW_BACKUPS,
            ConfigurationPermission.RESTORE_BACKUP,
            ConfigurationPermission.VIEW_AUDIT_LOG,
        }
    ),

    ConfigurationRole.VIEWER: frozenset(
        {
            ConfigurationPermission.VIEW_CONFIGURATION,
            ConfigurationPermission.PREVIEW_SYNCHRONIZATION,
            ConfigurationPermission.VIEW_BACKUPS,
            ConfigurationPermission.VIEW_AUDIT_LOG,
        }
    ),

    ConfigurationRole.SYSTEM: frozenset(
        ConfigurationPermission
    ),
}


@dataclass(frozen=True, slots=True)
class ConfigurationPrincipal:
    """Identity and roles of an actor performing an operation."""

    principal_id: str
    roles: frozenset[ConfigurationRole]
    is_active: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.principal_id, str):
            raise TypeError("principal_id must be a string")

        if not self.principal_id.strip():
            raise ValueError("principal_id cannot be empty")

        if not isinstance(self.roles, frozenset):
            raise TypeError("roles must be a frozenset")

        if any(
            not isinstance(role, ConfigurationRole)
            for role in self.roles
        ):
            raise TypeError("roles contains an invalid role")

        if not isinstance(self.is_active, bool):
            raise TypeError("is_active must be a boolean")


@dataclass(frozen=True, slots=True)
class PermissionCheckResult:
    """Result of a permission evaluation."""

    allowed: bool
    principal_id: str
    permission: ConfigurationPermission
    reason: str

    def to_dict(self) -> dict[str, str | bool]:
        return {
            "allowed": self.allowed,
            "principal_id": self.principal_id,
            "permission": self.permission.value,
            "reason": self.reason,
        }


class ConfigurationPermissionError(PermissionError):
    """Raised when an actor lacks a required permission."""

    def __init__(
        self,
        result: PermissionCheckResult,
    ) -> None:
        super().__init__(
            f"Permission denied for principal "
            f"'{result.principal_id}': {result.permission.value}"
        )
        self.result = result


class ConfigurationPermissionService:
    """Evaluate and enforce scheduling configuration permissions."""

    def __init__(self) -> None:
        self._role_permissions = dict(_ROLE_PERMISSIONS)

    def get_permissions(
        self,
        principal: ConfigurationPrincipal,
    ) -> frozenset[ConfigurationPermission]:
        """Return the effective permissions of a principal."""

        if not isinstance(principal, ConfigurationPrincipal):
            raise TypeError(
                "principal must be a ConfigurationPrincipal"
            )

        if not principal.is_active:
            return frozenset()

        permissions: set[ConfigurationPermission] = set()

        for role in principal.roles:
            permissions.update(
                self._role_permissions.get(role, frozenset())
            )

        return frozenset(permissions)

    def check(
        self,
        principal: ConfigurationPrincipal,
        permission: ConfigurationPermission,
    ) -> PermissionCheckResult:
        """Check whether a principal has a specific permission."""

        if not isinstance(principal, ConfigurationPrincipal):
            raise TypeError(
                "principal must be a ConfigurationPrincipal"
            )

        if not isinstance(permission, ConfigurationPermission):
            raise TypeError(
                "permission must be a ConfigurationPermission"
            )

        if not principal.is_active:
            return PermissionCheckResult(
                allowed=False,
                principal_id=principal.principal_id,
                permission=permission,
                reason="Principal is inactive",
            )

        effective_permissions = self.get_permissions(principal)

        if permission not in effective_permissions:
            return PermissionCheckResult(
                allowed=False,
                principal_id=principal.principal_id,
                permission=permission,
                reason="Required permission is not assigned",
            )

        return PermissionCheckResult(
            allowed=True,
            principal_id=principal.principal_id,
            permission=permission,
            reason="Permission granted",
        )

    def require(
        self,
        principal: ConfigurationPrincipal,
        permission: ConfigurationPermission,
    ) -> None:
        """Raise ConfigurationPermissionError if access is denied."""

        result = self.check(principal, permission)

        if not result.allowed:
            raise ConfigurationPermissionError(result)

    def require_all(
        self,
        principal: ConfigurationPrincipal,
        permissions: Iterable[ConfigurationPermission],
    ) -> None:
        """Require every permission in the supplied collection."""

        for permission in permissions:
            self.require(principal, permission)

    def require_any(
        self,
        principal: ConfigurationPrincipal,
        permissions: Iterable[ConfigurationPermission],
    ) -> None:
        """Require at least one permission in the supplied collection."""

        requested = tuple(permissions)

        if not requested:
            raise ValueError(
                "At least one permission must be supplied"
            )

        for permission in requested:
            result = self.check(principal, permission)

            if result.allowed:
                return

        raise ConfigurationPermissionError(
            PermissionCheckResult(
                allowed=False,
                principal_id=principal.principal_id,
                permission=requested[0],
                reason="None of the required permissions are assigned",
            )
        )

    def roles_for(
        self,
        principal: ConfigurationPrincipal,
    ) -> tuple[str, ...]:
        """Return the principal's role names."""

        if not isinstance(principal, ConfigurationPrincipal):
            raise TypeError(
                "principal must be a ConfigurationPrincipal"
            )

        return tuple(
            sorted(role.value for role in principal.roles)
        )
