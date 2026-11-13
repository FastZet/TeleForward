
"""Integration helpers for configuration API security auditing."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI

from app.services.scheduling.configuration_api_security_audit import (
    SecurityAuditEvent,
    SecurityAuditEventType,
    SecurityAuditLogger,
)


logger = logging.getLogger(__name__)

AUDIT_STATE_KEY = "configuration_api_security_audit_logger"
AUDIT_INSTALLATION_STATE_KEY = "configuration_api_security_audit_installed"


class SecurityAuditIntegrationError(RuntimeError):
    """Raised when security audit integration cannot be completed."""


def install_configuration_api_security_audit(
    app: FastAPI,
    audit_logger: SecurityAuditLogger,
    *,
    replace_existing: bool = False,
) -> SecurityAuditLogger:
    """Register the audit logger in FastAPI application state.

    The logger remains owned by the caller. Application shutdown does not
    automatically close it.
    """
    if not isinstance(app, FastAPI):
        raise TypeError("app must be a FastAPI instance")

    if not isinstance(audit_logger, SecurityAuditLogger):
        raise TypeError("audit_logger must be a SecurityAuditLogger instance")

    existing = getattr(app.state, AUDIT_STATE_KEY, None)

    if existing is not None and existing is not audit_logger:
        if not replace_existing:
            raise SecurityAuditIntegrationError(
                "A different security audit logger is already installed"
            )

    setattr(app.state, AUDIT_STATE_KEY, audit_logger)
    setattr(app.state, AUDIT_INSTALLATION_STATE_KEY, True)

    logger.info("Configuration API security audit logger installed")
    return audit_logger


def get_configuration_api_security_audit_logger(
    app: FastAPI,
) -> SecurityAuditLogger:
    """Retrieve the installed audit logger."""
    if not isinstance(app, FastAPI):
        raise TypeError("app must be a FastAPI instance")

    audit_logger = getattr(app.state, AUDIT_STATE_KEY, None)

    if not isinstance(audit_logger, SecurityAuditLogger):
        raise SecurityAuditIntegrationError(
            "Configuration API security audit logger is not installed"
        )

    return audit_logger


def is_configuration_api_security_audit_installed(
    app: FastAPI,
) -> bool:
    """Return whether an audit logger is registered."""
    if not isinstance(app, FastAPI):
        raise TypeError("app must be a FastAPI instance")

    audit_logger = getattr(app.state, AUDIT_STATE_KEY, None)
    return isinstance(audit_logger, SecurityAuditLogger)


def record_security_audit_event(
    app: FastAPI,
    event_type: SecurityAuditEventType,
    *,
    principal_id: str | None = None,
    success: bool = False,
    reason: str | None = None,
    path: str | None = None,
    method: str | None = None,
    source_ip: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> SecurityAuditEvent:
    """Record a security event through the installed audit logger."""
    audit_logger = get_configuration_api_security_audit_logger(app)

    event_metadata: dict[str, Any] = dict(metadata or {})

    if reason is not None:
        event_metadata["reason"] = reason

    if path is not None:
        event_metadata["path"] = path

    if method is not None:
        event_metadata["method"] = method

    if source_ip is not None:
        event_metadata["source_ip"] = source_ip

    return audit_logger.record_event(
        event_type,
        principal_id=principal_id,
        success=success,
        reason=reason,
        path=path,
        method=method,
        source_ip=source_ip,
        metadata=event_metadata,
    )


def record_authentication_result(
    app: FastAPI,
    *,
    success: bool,
    principal_id: str | None = None,
    reason: str | None = None,
    source_ip: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> SecurityAuditEvent:
    """Record an authentication success or failure."""
    event_type = (
        SecurityAuditEventType.AUTHENTICATION_SUCCESS
        if success
        else SecurityAuditEventType.AUTHENTICATION_FAILURE
    )

    return record_security_audit_event(
        app,
        event_type,
        principal_id=principal_id,
        success=success,
        reason=reason,
        source_ip=source_ip,
        metadata=metadata,
    )


def record_authorization_result(
    app: FastAPI,
    *,
    success: bool,
    principal_id: str | None = None,
    permission: str | None = None,
    resource: str | None = None,
    reason: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> SecurityAuditEvent:
    """Record an authorization success or failure."""
    event_type = (
        SecurityAuditEventType.AUTHORIZATION_SUCCESS
        if success
        else SecurityAuditEventType.AUTHORIZATION_FAILURE
    )

    event_metadata = dict(metadata or {})

    if permission is not None:
        event_metadata["permission"] = permission

    if resource is not None:
        event_metadata["resource"] = resource

    return record_security_audit_event(
        app,
        event_type,
        principal_id=principal_id,
        success=success,
        reason=reason,
        metadata=event_metadata,
    )


def record_rate_limit_rejection(
    app: FastAPI,
    *,
    principal_id: str | None = None,
    path: str | None = None,
    method: str | None = None,
    source_ip: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> SecurityAuditEvent:
    """Record a rejected request caused by rate limiting."""
    return record_security_audit_event(
        app,
        SecurityAuditEventType.RATE_LIMIT_REJECTED,
        principal_id=principal_id,
        success=False,
        reason="rate_limit_exceeded",
        path=path,
        method=method,
        source_ip=source_ip,
        metadata=metadata,
    )


def record_request_rejection(
    app: FastAPI,
    *,
    reason: str,
    principal_id: str | None = None,
    path: str | None = None,
    method: str | None = None,
    source_ip: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> SecurityAuditEvent:
    """Record a rejected API request."""
    return record_security_audit_event(
        app,
        SecurityAuditEventType.REQUEST_REJECTED,
        principal_id=principal_id,
        success=False,
        reason=reason,
        path=path,
        method=method,
        source_ip=source_ip,
        metadata=metadata,
    )


def remove_configuration_api_security_audit(
    app: FastAPI,
    *,
    close_logger: bool = False,
) -> SecurityAuditLogger:
    """Remove the logger registration.

    By default, the logger is not closed because its lifecycle may be
    managed externally or shared with another component.
    """
    audit_logger = get_configuration_api_security_audit_logger(app)

    delattr(app.state, AUDIT_STATE_KEY)
    setattr(app.state, AUDIT_INSTALLATION_STATE_KEY, False)

    if close_logger:
        audit_logger.close()

    logger.info("Configuration API security audit logger uninstalled")
    return audit_logger


__all__ = [
    "AUDIT_INSTALLATION_STATE_KEY",
    "AUDIT_STATE_KEY",
    "SecurityAuditIntegrationError",
    "get_configuration_api_security_audit_logger",
    "install_configuration_api_security_audit",
    "is_configuration_api_security_audit_installed",
    "record_authentication_result",
    "record_authorization_result",
    "record_rate_limit_rejection",
    "record_request_rejection",
    "record_security_audit_event",
    "remove_configuration_api_security_audit",
]
