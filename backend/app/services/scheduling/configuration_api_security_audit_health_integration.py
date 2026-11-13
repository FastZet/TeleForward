
"""FastAPI integration for security audit health monitoring."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI

from app.services.scheduling.configuration_api_security_audit import (
    SecurityAuditLogger,
)
from app.services.scheduling.configuration_api_security_audit_health import (
    AuditHealthReport,
    SecurityAuditHealthService,
)


logger = logging.getLogger(__name__)

HEALTH_SERVICE_STATE_KEY = (
    "configuration_api_security_audit_health_service"
)
HEALTH_INSTALLATION_STATE_KEY = (
    "configuration_api_security_audit_health_installed"
)


class SecurityAuditHealthIntegrationError(RuntimeError):
    """Raised when audit health integration cannot be completed."""


def install_configuration_api_security_audit_health(
    app: FastAPI,
    *,
    audit_logger: SecurityAuditLogger | None = None,
    audit_file_path: str | None = None,
    replace_existing: bool = False,
) -> SecurityAuditHealthService:
    """Create and register the audit health service.

    The service does not take ownership of the audit logger. Its lifecycle
    remains controlled by the component that created the logger.
    """
    if not isinstance(app, FastAPI):
        raise TypeError("app must be a FastAPI instance")

    existing = getattr(app.state, HEALTH_SERVICE_STATE_KEY, None)

    if existing is not None:
        if not isinstance(existing, SecurityAuditHealthService):
            raise SecurityAuditHealthIntegrationError(
                "An invalid audit health service is registered"
            )

        if not replace_existing:
            raise SecurityAuditHealthIntegrationError(
                "Security audit health service is already installed"
            )

    service = SecurityAuditHealthService(
        audit_logger,
        audit_file_path=audit_file_path,
    )

    setattr(app.state, HEALTH_SERVICE_STATE_KEY, service)
    setattr(app.state, HEALTH_INSTALLATION_STATE_KEY, True)

    logger.info("Configuration API security audit health service installed")

    return service


def get_configuration_api_security_audit_health_service(
    app: FastAPI,
) -> SecurityAuditHealthService:
    """Retrieve the registered audit health service."""
    if not isinstance(app, FastAPI):
        raise TypeError("app must be a FastAPI instance")

    service = getattr(app.state, HEALTH_SERVICE_STATE_KEY, None)

    if not isinstance(service, SecurityAuditHealthService):
        raise SecurityAuditHealthIntegrationError(
            "Security audit health service is not installed"
        )

    return service


def is_configuration_api_security_audit_health_installed(
    app: FastAPI,
) -> bool:
    """Return whether the health service is installed."""
    if not isinstance(app, FastAPI):
        raise TypeError("app must be a FastAPI instance")

    service = getattr(app.state, HEALTH_SERVICE_STATE_KEY, None)

    return isinstance(service, SecurityAuditHealthService)


def check_configuration_api_security_audit_health(
    app: FastAPI,
) -> AuditHealthReport:
    """Run the registered audit health checks."""
    service = get_configuration_api_security_audit_health_service(app)

    try:
        return service.check()
    except Exception as exc:
        logger.exception("Security audit health check execution failed")
        raise SecurityAuditHealthIntegrationError(
            "Could not execute security audit health checks"
        ) from exc


def get_configuration_api_security_audit_health_status(
    app: FastAPI,
) -> dict[str, Any]:
    """Return a serializable health report for application diagnostics."""
    report = check_configuration_api_security_audit_health(app)
    return report.to_dict()


def remove_configuration_api_security_audit_health(
    app: FastAPI,
) -> SecurityAuditHealthService:
    """Remove the health service registration.

    Removing the service does not close or otherwise modify its audit logger.
    """
    service = get_configuration_api_security_audit_health_service(app)

    delattr(app.state, HEALTH_SERVICE_STATE_KEY)
    setattr(app.state, HEALTH_INSTALLATION_STATE_KEY, False)

    logger.info("Configuration API security audit health service removed")

    return service


__all__ = [
    "HEALTH_INSTALLATION_STATE_KEY",
    "HEALTH_SERVICE_STATE_KEY",
    "SecurityAuditHealthIntegrationError",
    "check_configuration_api_security_audit_health",
    "get_configuration_api_security_audit_health_service",
    "get_configuration_api_security_audit_health_status",
    "install_configuration_api_security_audit_health",
    "is_configuration_api_security_audit_health_installed",
    "remove_configuration_api_security_audit_health",
]
