
"""Consolidated security audit subsystem health status."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Mapping

from app.services.scheduling.configuration_api_security_audit_health import (
    AuditHealthReport,
    AuditHealthStatus,
)


class SecurityAuditSubsystemStatus(StrEnum):
    """Overall security audit subsystem status."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class SecurityAuditComponentStatus(StrEnum):
    """Status of an individual security audit component."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    NOT_INSTALLED = "not_installed"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class SecurityAuditComponentHealth:
    """Health information for one subsystem component."""

    name: str
    status: SecurityAuditComponentStatus
    message: str | None = None
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("Component name must be a non-empty string")

        if not isinstance(self.status, SecurityAuditComponentStatus):
            raise TypeError(
                "status must be a SecurityAuditComponentStatus"
            )

        if self.message is not None and not isinstance(self.message, str):
            raise TypeError("message must be a string or None")

        if not isinstance(self.details, Mapping):
            raise TypeError("details must be a mapping")

        object.__setattr__(self, "name", self.name.strip())
        object.__setattr__(self, "details", dict(self.details))

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible representation."""
        return {
            "name": self.name,
            "status": self.status.value,
            "message": self.message,
            "details": dict(self.details),
        }


@dataclass(frozen=True, slots=True)
class SecurityAuditSubsystemHealth:
    """Immutable consolidated health snapshot."""

    status: SecurityAuditSubsystemStatus
    checked_at: datetime
    components: tuple[SecurityAuditComponentHealth, ...]
    messages: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.status, SecurityAuditSubsystemStatus):
            raise TypeError(
                "status must be a SecurityAuditSubsystemStatus"
            )

        if not isinstance(self.checked_at, datetime):
            raise TypeError("checked_at must be a datetime")

        if (
            self.checked_at.tzinfo is None
            or self.checked_at.utcoffset() is None
        ):
            raise ValueError("checked_at must be timezone-aware")

        components = tuple(self.components)

        if any(
            not isinstance(component, SecurityAuditComponentHealth)
            for component in components
        ):
            raise TypeError(
                "components must contain SecurityAuditComponentHealth objects"
            )

        names = [component.name for component in components]

        if len(names) != len(set(names)):
            raise ValueError("Component names must be unique")

        messages = tuple(self.messages)

        if any(
            not isinstance(message, str)
            for message in messages
        ):
            raise TypeError("messages must contain strings")

        object.__setattr__(
            self,
            "checked_at",
            self.checked_at.astimezone(timezone.utc),
        )
        object.__setattr__(self, "components", components)
        object.__setattr__(self, "messages", messages)

    @property
    def healthy(self) -> bool:
        """Return whether every component is healthy."""
        return self.status is SecurityAuditSubsystemStatus.HEALTHY

    def get_component(
        self,
        name: str,
    ) -> SecurityAuditComponentHealth | None:
        """Return a component by name."""
        return next(
            (
                component
                for component in self.components
                if component.name == name
            ),
            None,
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible health snapshot."""
        return {
            "status": self.status.value,
            "healthy": self.healthy,
            "checked_at": self.checked_at.isoformat(),
            "components": [
                component.to_dict()
                for component in self.components
            ],
            "messages": list(self.messages),
        }


class SecurityAuditHealthStatusBuilder:
    """Build consolidated health snapshots from component reports."""

    _STATUS_PRIORITY = {
        SecurityAuditComponentStatus.HEALTHY: 0,
        SecurityAuditComponentStatus.DEGRADED: 1,
        SecurityAuditComponentStatus.NOT_INSTALLED: 2,
        SecurityAuditComponentStatus.UNKNOWN: 3,
        SecurityAuditComponentStatus.UNHEALTHY: 4,
    }

    def __init__(self) -> None:
        self._components: list[SecurityAuditComponentHealth] = []

    def add_component(
        self,
        component: SecurityAuditComponentHealth,
    ) -> None:
        """Add a component to the health snapshot."""
        if not isinstance(component, SecurityAuditComponentHealth):
            raise TypeError(
                "component must be a SecurityAuditComponentHealth"
            )

        if any(
            existing.name == component.name
            for existing in self._components
        ):
            raise ValueError(
                f"Component already exists: {component.name}"
            )

        self._components.append(component)

    def add_audit_health_report(
        self,
        report: AuditHealthReport,
    ) -> None:
        """Convert an audit health report into a component."""
        if not isinstance(report, AuditHealthReport):
            raise TypeError("report must be an AuditHealthReport")

        status_map = {
            AuditHealthStatus.HEALTHY:
                SecurityAuditComponentStatus.HEALTHY,
            AuditHealthStatus.DEGRADED:
                SecurityAuditComponentStatus.DEGRADED,
            AuditHealthStatus.UNHEALTHY:
                SecurityAuditComponentStatus.UNHEALTHY,
        }

        component_status = status_map.get(
            report.status,
            SecurityAuditComponentStatus.UNKNOWN,
        )

        self.add_component(
            SecurityAuditComponentHealth(
                name="audit_logger",
                status=component_status,
                message=f"Audit logger status: {report.status.value}",
                details=report.to_dict(),
            )
        )

    def add_api_component(
        self,
        *,
        installed: bool,
        prefix: str | None = None,
    ) -> None:
        """Add the health API installation status."""
        if not isinstance(installed, bool):
            raise TypeError("installed must be a boolean")

        if prefix is not None and not isinstance(prefix, str):
            raise TypeError("prefix must be a string or None")

        component_status = (
            SecurityAuditComponentStatus.HEALTHY
            if installed
            else SecurityAuditComponentStatus.NOT_INSTALLED
        )

        details: dict[str, Any] = {
            "installed": installed,
        }

        if prefix is not None:
            details["prefix"] = prefix

        self.add_component(
            SecurityAuditComponentHealth(
                name="health_api",
                status=component_status,
                message=(
                    "Health API is installed"
                    if installed
                    else "Health API is not installed"
                ),
                details=details,
            )
        )

    def build(
        self,
        *,
        checked_at: datetime | None = None,
    ) -> SecurityAuditSubsystemHealth:
        """Build the consolidated health snapshot."""
        timestamp = checked_at or datetime.now(timezone.utc)

        if not isinstance(timestamp, datetime):
            raise TypeError("checked_at must be a datetime")

        if (
            timestamp.tzinfo is None
            or timestamp.utcoffset() is None
        ):
            raise ValueError("checked_at must be timezone-aware")

        if not self._components:
            overall_status = SecurityAuditSubsystemStatus.UNKNOWN
            messages = ("No health components were registered",)
        else:
            worst_status = max(
                self._components,
                key=lambda component: self._STATUS_PRIORITY[
                    component.status
                ],
            ).status

            status_map = {
                SecurityAuditComponentStatus.HEALTHY:
                    SecurityAuditSubsystemStatus.HEALTHY,
                SecurityAuditComponentStatus.DEGRADED:
                    SecurityAuditSubsystemStatus.DEGRADED,
                SecurityAuditComponentStatus.NOT_INSTALLED:
                    SecurityAuditSubsystemStatus.DEGRADED,
                SecurityAuditComponentStatus.UNKNOWN:
                    SecurityAuditSubsystemStatus.UNKNOWN,
                SecurityAuditComponentStatus.UNHEALTHY:
                    SecurityAuditSubsystemStatus.UNHEALTHY,
            }

            overall_status = status_map[worst_status]

            messages = tuple(
                component.message
                for component in self._components
                if component.message is not None
                and component.status
                is not SecurityAuditComponentStatus.HEALTHY
            )

        return SecurityAuditSubsystemHealth(
            status=overall_status,
            checked_at=timestamp,
            components=tuple(self._components),
            messages=messages,
        )


def build_security_audit_health_status(
    *,
    audit_report: AuditHealthReport | None,
    api_installed: bool,
    api_prefix: str | None = None,
    checked_at: datetime | None = None,
) -> SecurityAuditSubsystemHealth:
    """Build a consolidated health snapshot from available inputs."""
    if audit_report is not None and not isinstance(
        audit_report,
        AuditHealthReport,
    ):
        raise TypeError("audit_report must be an AuditHealthReport or None")

    if not isinstance(api_installed, bool):
        raise TypeError("api_installed must be a boolean")

    builder = SecurityAuditHealthStatusBuilder()

    if audit_report is None:
        builder.add_component(
            SecurityAuditComponentHealth(
                name="audit_logger",
                status=SecurityAuditComponentStatus.UNKNOWN,
                message="Audit logger health report is unavailable",
            )
        )
    else:
        builder.add_audit_health_report(audit_report)

    builder.add_api_component(
        installed=api_installed,
        prefix=api_prefix,
    )

    return builder.build(checked_at=checked_at)
