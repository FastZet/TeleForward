"""Access-control service for scheduling configuration resources."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable

from app.services.scheduling.configuration_permissions import (
    ConfigurationPermission,
    ConfigurationPermissionService,
    ConfigurationPrincipal,
    ConfigurationRole,
    ConfigurationPermissionError,
)


class ConfigurationResourceType(StrEnum):
    """Supported scheduling configuration resource types."""

    CONFIGURATION = "configuration"
    TASK = "task"
    BACKUP = "backup"
    AUDIT_LOG = "audit_log"
    POLICY = "policy"


@dataclass(frozen=True, slots=True)
class ConfigurationAccessRule:
    """Resource-specific access rule."""

    resource_type: ConfigurationResourceType
    resource_id: str
    required_permissions: frozenset[ConfigurationPermission]
    denied_principals: frozenset[str] = frozenset()
    allowed_principals: frozenset[str] | None = None

    def __post_init__(self) -> None:
        if not isinstance(
            self.resource_type,
            ConfigurationResourceType,
        ):
            raise TypeError("Invalid resource_type")

        if not isinstance(self.resource_id, str) or not self.resource_id.strip():
            raise ValueError("resource_id must be non-empty")

        if not isinstance(self.required_permissions, frozenset):
            raise TypeError(
                "required_permissions must be a frozenset"
            )

        if any(
            not isinstance(permission, ConfigurationPermission)
            for permission in self.required_permissions
        ):
            raise TypeError(
                "required_permissions contains an invalid permission"
            )

        if not isinstance(self.denied_principals, frozenset):
            raise TypeError("denied_principals must be a frozenset")

        if self.allowed_principals is not None and not isinstance(
            self.allowed_principals,
            frozenset,
        ):
            raise TypeError(
                "allowed_principals must be a frozenset or None"
            )


@dataclass(frozen=True, slots=True)
class ConfigurationAccessResult:
    """Result of a resource access evaluation."""

    allowed: bool
    principal_id: str
    resource_type: ConfigurationResourceType
    resource_id: str
    reason: str

    def to_dict(self) -> dict[str, str | bool]:
        return {
            "allowed": self.allowed,
            "principal_id": self.principal_id,
            "resource_type": self.resource_type.value,
            "resource_id": self.resource_id,
            "reason": self.reason,
        }


class ConfigurationAccessDenied(PermissionError):
    """Raised when access to a configuration resource is denied."""

    def __init__(
        self,
        result: ConfigurationAccessResult,
    ) -> None:
        super().__init__(
            f"Access denied for principal '{result.principal_id}' "
            f"to {result.resource_type.value} '{result.resource_id}': "
            f"{result.reason}"
        )
        self.result = result


class ConfigurationAccessService:
    """Manage resource-specific scheduling access decisions."""

    def __init__(
        self,
        permission_service: ConfigurationPermissionService,
    ) -> None:
        if not isinstance(
            permission_service,
            ConfigurationPermissionService,
        ):
            raise TypeError(
                "permission_service must be a "
                "ConfigurationPermissionService"
            )

        self._permission_service = permission_service
        self._rules: dict[
            tuple[ConfigurationResourceType, str],
            ConfigurationAccessRule,
        ] = {}

    def add_rule(self, rule: ConfigurationAccessRule) -> None:
        """Add or replace a resource access rule."""

        if not isinstance(rule, ConfigurationAccessRule):
            raise TypeError("rule must be a ConfigurationAccessRule")

        key = (rule.resource_type, rule.resource_id)
        self._rules[key] = rule

    def remove_rule(
        self,
        resource_type: ConfigurationResourceType,
        resource_id: str,
    ) -> bool:
        """Remove a resource-specific rule."""

        key = (resource_type, resource_id)
        return self._rules.pop(key, None) is not None

    def get_rule(
        self,
        resource_type: ConfigurationResourceType,
        resource_id: str,
    ) -> ConfigurationAccessRule | None:
        """Retrieve a resource-specific rule."""

        return self._rules.get((resource_type, resource_id))

    def check(
        self,
        principal: ConfigurationPrincipal,
        resource_type: ConfigurationResourceType,
        resource_id: str,
        permission: ConfigurationPermission,
    ) -> ConfigurationAccessResult:
        """Evaluate access to a specific resource."""

        if not isinstance(principal, ConfigurationPrincipal):
            raise TypeError(
                "principal must be a ConfigurationPrincipal"
            )

        if not isinstance(resource_type, ConfigurationResourceType):
            raise TypeError("Invalid resource_type")

        if not isinstance(resource_id, str) or not resource_id.strip():
            raise ValueError("resource_id must be non-empty")

        if not isinstance(permission, ConfigurationPermission):
            raise TypeError("Invalid permission")

        if not principal.is_active:
            return self._denied(
                principal,
                resource_type,
                resource_id,
                "Principal is inactive",
            )

        rule = self.get_rule(resource_type, resource_id)

        if rule is not None:
            if principal.principal_id in rule.denied_principals:
                return self._denied(
                    principal,
                    resource_type,
                    resource_id,
                    "Principal is explicitly denied",
                )

            if (
                rule.allowed_principals is not None
                and principal.principal_id not in rule.allowed_principals
            ):
                return self._denied(
                    principal,
                    resource_type,
                    resource_id,
                    "Principal is not in the resource allowlist",
                )

            if (
                rule.required_permissions
                and permission not in rule.required_permissions
            ):
                return self._denied(
                    principal,
                    resource_type,
                    resource_id,
                    "Permission is not allowed by the resource rule",
                )

        permission_result = self._permission_service.check(
            principal,
            permission,
        )

        if not permission_result.allowed:
            return self._denied(
                principal,
                resource_type,
                resource_id,
                permission_result.reason,
            )

        return ConfigurationAccessResult(
            allowed=True,
            principal_id=principal.principal_id,
            resource_type=resource_type,
            resource_id=resource_id,
            reason="Resource access granted",
        )

    def require(
        self,
        principal: ConfigurationPrincipal,
        resource_type: ConfigurationResourceType,
        resource_id: str,
        permission: ConfigurationPermission,
    ) -> None:
        """Raise an exception if resource access is denied."""

        result = self.check(
            principal,
            resource_type,
            resource_id,
            permission,
        )

        if not result.allowed:
            raise ConfigurationAccessDenied(result)

    def require_all(
        self,
        principal: ConfigurationPrincipal,
        resource_type: ConfigurationResourceType,
        resource_id: str,
        permissions: Iterable[ConfigurationPermission],
    ) -> None:
        """Require every supplied permission for a resource."""

        for permission in permissions:
            self.require(
                principal,
                resource_type,
                resource_id,
                permission,
            )

    def _denied(
        self,
        principal: ConfigurationPrincipal,
        resource_type: ConfigurationResourceType,
        resource_id: str,
        reason: str,
    ) -> ConfigurationAccessResult:
        return ConfigurationAccessResult(
            allowed=False,
            principal_id=principal.principal_id,
            resource_type=resource_type,
            resource_id=resource_id,
            reason=reason,
        )
