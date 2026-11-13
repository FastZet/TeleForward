
"""Health checks for configuration API security audit logging."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any

from app.services.scheduling.configuration_api_security_audit import (
    SecurityAuditLogger,
)


logger = logging.getLogger(__name__)


class AuditHealthStatus(StrEnum):
    """Overall audit subsystem health."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class AuditHealthCheckStatus(StrEnum):
    """Individual health-check result."""

    PASSED = "passed"
    WARNING = "warning"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True, slots=True)
class AuditHealthCheckResult:
    """Result of an individual audit health check."""

    name: str
    status: AuditHealthCheckStatus
    message: str
    checked_at: datetime
    details: dict[str, Any]

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("Health check name must be non-empty")

        if not isinstance(self.status, AuditHealthCheckStatus):
            raise TypeError("status must be an AuditHealthCheckStatus")

        if not isinstance(self.message, str):
            raise TypeError("message must be a string")

        if (
            not isinstance(self.checked_at, datetime)
            or self.checked_at.tzinfo is None
            or self.checked_at.utcoffset() is None
        ):
            raise ValueError("checked_at must be timezone-aware")

        if not isinstance(self.details, dict):
            raise TypeError("details must be a dictionary")

        object.__setattr__(self, "details", dict(self.details))


@dataclass(frozen=True, slots=True)
class AuditHealthReport:
    """Aggregated health report for the audit subsystem."""

    status: AuditHealthStatus
    checked_at: datetime
    checks: tuple[AuditHealthCheckResult, ...]
    logger_available: bool

    def __post_init__(self) -> None:
        if not isinstance(self.status, AuditHealthStatus):
            raise TypeError("status must be an AuditHealthStatus")

        if (
            not isinstance(self.checked_at, datetime)
            or self.checked_at.tzinfo is None
            or self.checked_at.utcoffset() is None
        ):
            raise ValueError("checked_at must be timezone-aware")

        if not isinstance(self.checks, tuple):
            raise TypeError("checks must be a tuple")

        if not all(
            isinstance(check, AuditHealthCheckResult)
            for check in self.checks
        ):
            raise TypeError(
                "checks must contain AuditHealthCheckResult instances"
            )

        if not isinstance(self.logger_available, bool):
            raise TypeError("logger_available must be a boolean")

    @property
    def healthy(self) -> bool:
        return self.status is AuditHealthStatus.HEALTHY

    @property
    def failed_checks(self) -> tuple[AuditHealthCheckResult, ...]:
        return tuple(
            check
            for check in self.checks
            if check.status is AuditHealthCheckStatus.FAILED
        )

    @property
    def warning_checks(self) -> tuple[AuditHealthCheckResult, ...]:
        return tuple(
            check
            for check in self.checks
            if check.status is AuditHealthCheckStatus.WARNING
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert the report into a JSON-compatible dictionary."""
        return {
            "status": self.status.value,
            "healthy": self.healthy,
            "checked_at": self.checked_at.isoformat(),
            "logger_available": self.logger_available,
            "checks": [
                {
                    "name": check.name,
                    "status": check.status.value,
                    "message": check.message,
                    "checked_at": check.checked_at.isoformat(),
                    "details": dict(check.details),
                }
                for check in self.checks
            ],
        }


class SecurityAuditHealthService:
    """Checks the operational health of the security audit subsystem.

    The service does not write probe events into the audit log. Storage
    writability is checked using filesystem permissions and directory
    metadata, avoiding additional audit records during health checks.
    """

    def __init__(
        self,
        audit_logger: SecurityAuditLogger | None,
        *,
        audit_file_path: str | Path | None = None,
    ) -> None:
        if audit_logger is not None and not isinstance(
            audit_logger,
            SecurityAuditLogger,
        ):
            raise TypeError(
                "audit_logger must be a SecurityAuditLogger or None"
            )

        if audit_file_path is not None:
            if not isinstance(audit_file_path, (str, Path)):
                raise TypeError(
                    "audit_file_path must be a string or Path"
                )

            if not str(audit_file_path).strip():
                raise ValueError("audit_file_path cannot be empty")

        self._audit_logger = audit_logger
        self._audit_file_path = (
            Path(audit_file_path)
            if audit_file_path is not None
            else None
        )

    def check(self) -> AuditHealthReport:
        """Run all available audit health checks."""
        checks: list[AuditHealthCheckResult] = []

        logger_check = self._check_logger()
        checks.append(logger_check)

        path = self._resolve_audit_path()

        if path is None:
            checks.append(
                self._result(
                    name="storage_path",
                    status=AuditHealthCheckStatus.SKIPPED,
                    message="Audit file path is not configured",
                )
            )
            checks.append(
                self._result(
                    name="storage_permissions",
                    status=AuditHealthCheckStatus.SKIPPED,
                    message="Storage permissions could not be inspected",
                )
            )
            checks.append(
                self._result(
                    name="audit_integrity",
                    status=AuditHealthCheckStatus.SKIPPED,
                    message="Audit integrity check could not be performed",
                )
            )
        else:
            checks.append(self._check_storage_path(path))
            checks.append(self._check_storage_permissions(path))
            checks.append(self._check_audit_integrity())

        if any(
            item.status is AuditHealthCheckStatus.FAILED
            for item in checks
        ):
            overall = AuditHealthStatus.UNHEALTHY
        elif any(
            item.status in (
                AuditHealthCheckStatus.WARNING,
                AuditHealthCheckStatus.SKIPPED,
            )
            for item in checks
        ):
            overall = AuditHealthStatus.DEGRADED
        else:
            overall = AuditHealthStatus.HEALTHY

        return AuditHealthReport(
            status=overall,
            checked_at=datetime.now(timezone.utc),
            checks=tuple(checks),
            logger_available=(
                logger_check.status is AuditHealthCheckStatus.PASSED
            ),
        )

    def _check_logger(self) -> AuditHealthCheckResult:
        if self._audit_logger is None:
            return self._result(
                name="logger",
                status=AuditHealthCheckStatus.FAILED,
                message="Security audit logger is not configured",
            )

        try:
            # A closed logger rejects read operations. Reading the log also
            # verifies that the logger can access its configured storage.
            self._audit_logger.read_events(limit=1)
        except Exception as exc:
            return self._result(
                name="logger",
                status=AuditHealthCheckStatus.FAILED,
                message="Security audit logger is unavailable",
                details={"error_type": type(exc).__name__},
            )

        return self._result(
            name="logger",
            status=AuditHealthCheckStatus.PASSED,
            message="Security audit logger is available",
        )

    def _resolve_audit_path(self) -> Path | None:
        if self._audit_file_path is not None:
            return self._audit_file_path

        # File 270's logger implementation should expose its configured
        # path. Keep path discovery defensive so a missing attribute does
        # not break the logger availability check.
        if self._audit_logger is None:
            return None

        for attribute in ("path", "file_path", "_path"):
            value = getattr(self._audit_logger, attribute, None)

            if isinstance(value, (str, Path)):
                return Path(value)

        return None

    def _check_storage_path(
        self,
        path: Path,
    ) -> AuditHealthCheckResult:
        try:
            parent = path.parent

            if not parent.exists():
                return self._result(
                    name="storage_path",
                    status=AuditHealthCheckStatus.FAILED,
                    message="Audit storage directory does not exist",
                    details={"directory_exists": False},
                )

            if not parent.is_dir():
                return self._result(
                    name="storage_path",
                    status=AuditHealthCheckStatus.FAILED,
                    message="Audit storage parent is not a directory",
                )

            if path.exists() and not path.is_file():
                return self._result(
                    name="storage_path",
                    status=AuditHealthCheckStatus.FAILED,
                    message="Audit path is not a regular file",
                )

            return self._result(
                name="storage_path",
                status=AuditHealthCheckStatus.PASSED,
                message="Audit storage path is accessible",
                details={
                    "file_exists": path.exists(),
                    "parent_directory": str(parent),
                },
            )

        except OSError as exc:
            return self._result(
                name="storage_path",
                status=AuditHealthCheckStatus.FAILED,
                message="Could not inspect audit storage path",
                details={"error_type": type(exc).__name__},
            )

    def _check_storage_permissions(
        self,
        path: Path,
    ) -> AuditHealthCheckResult:
        try:
            target = path if path.exists() else path.parent

            readable = os.access(target, os.R_OK)
            writable = (
                os.access(target, os.W_OK)
                if target.is_dir()
                else os.access(target, os.W_OK)
            )

            if not readable or not writable:
                return self._result(
                    name="storage_permissions",
                    status=AuditHealthCheckStatus.FAILED,
                    message="Audit storage is not readable and writable",
                    details={
                        "readable": readable,
                        "writable": writable,
                    },
                )

            return self._result(
                name="storage_permissions",
                status=AuditHealthCheckStatus.PASSED,
                message="Audit storage permissions appear usable",
                details={
                    "readable": readable,
                    "writable": writable,
                },
            )

        except OSError as exc:
            return self._result(
                name="storage_permissions",
                status=AuditHealthCheckStatus.FAILED,
                message="Could not inspect audit storage permissions",
                details={"error_type": type(exc).__name__},
            )

    def _check_audit_integrity(self) -> AuditHealthCheckResult:
        if self._audit_logger is None:
            return self._result(
                name="audit_integrity",
                status=AuditHealthCheckStatus.SKIPPED,
                message="Audit logger is unavailable",
            )

        try:
            records = self._audit_logger.read_events(limit=1)

            return self._result(
                name="audit_integrity",
                status=AuditHealthCheckStatus.PASSED,
                message="Audit records can be read and parsed",
                details={
                    "recent_records_read": len(records),
                },
            )

        except Exception as exc:
            return self._result(
                name="audit_integrity",
                status=AuditHealthCheckStatus.FAILED,
                message="Audit records could not be read or parsed",
                details={"error_type": type(exc).__name__},
            )

    @staticmethod
    def _result(
        *,
        name: str,
        status: AuditHealthCheckStatus,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> AuditHealthCheckResult:
        return AuditHealthCheckResult(
            name=name,
            status=status,
            message=message,
            checked_at=datetime.now(timezone.utc),
            details=details or {},
        )


__all__ = [
    "AuditHealthCheckResult",
    "AuditHealthCheckStatus",
    "AuditHealthReport",
    "AuditHealthStatus",
    "SecurityAuditHealthService",
]
