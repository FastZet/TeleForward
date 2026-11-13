
"""FastAPI integration for consolidated security audit health status."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import FastAPI

from app.services.scheduling.configuration_api_security_audit_health_integration import (
    SecurityAuditHealthIntegrationError,
    check_configuration_api_security_audit_health,
    is_configuration_api_security_audit_health_installed,
)
from app.services.scheduling.configuration_api_security_audit_health_api_integration import (
    SecurityAuditHealthApiIntegrationError,
    get_configuration_api_security_audit_health_api_prefix,
    is_configuration_api_security_audit_health_api_installed,
)
from app.services.scheduling.configuration_api_security_audit_health_status import (
    SecurityAuditSubsystemHealth,
    build_security_audit_health_status,
)


HEALTH_STATUS_STATE_KEY = (
    "configuration_api_security_audit_health_status"
)
HEALTH_STATUS_INSTALLATION_STATE_KEY = (
    "configuration_api_security_audit_health_status_installed"
)


class SecurityAuditHealthStatusIntegrationError(RuntimeError):
    """Raised when consolidated health integration fails."""


def install_configuration_api_security_audit_health_status(
    app: FastAPI,
) -> SecurityAuditSubsystemHealth:
    """Install consolidated health-status integration.

    Installation registers the integration in application state.
    It does not install the audit logger or health API themselves.

    Args:
        app: FastAPI application.

    Returns:
        An initial consolidated health snapshot.

    Raises:
        TypeError: If app is not a FastAPI application.
        SecurityAuditHealthStatusIntegrationError: If installation fails.
    """
    if not isinstance(app, FastAPI):
        raise TypeError("app must be a FastAPI application")

    if is_configuration_api_security_audit_health_status_installed(app):
        raise SecurityAuditHealthStatusIntegrationError(
            "Consolidated security audit health status is already installed"
        )

    try:
        report = _get_audit_report(app)
        api_installed = (
            is_configuration_api_security_audit_health_api_installed(app)
        )
        api_prefix = _get_api_prefix(app, api_installed)

        snapshot = build_security_audit_health_status(
            audit_report=report,
            api_installed=api_installed,
            api_prefix=api_prefix,
        )

        setattr(app.state, HEALTH_STATUS_STATE_KEY, snapshot)
        setattr(
            app.state,
            HEALTH_STATUS_INSTALLATION_STATE_KEY,
            True,
        )

        return snapshot

    except Exception as exc:
        raise SecurityAuditHealthStatusIntegrationError(
            "Could not install consolidated security audit health status"
        ) from exc


def _get_audit_report(app: FastAPI) -> Any:
    """Return an audit report when the health service is installed."""
    if not is_configuration_api_security_audit_health_installed(app):
        return None

    try:
        return check_configuration_api_security_audit_health(app)
    except SecurityAuditHealthIntegrationError:
        return None


def _get_api_prefix(
    app: FastAPI,
    api_installed: bool,
) -> str | None:
    """Return the health API prefix when available."""
    if not api_installed:
        return None

    try:
        return get_configuration_api_security_audit_health_api_prefix(
            app
        )
    except SecurityAuditHealthApiIntegrationError:
        return None


def is_configuration_api_security_audit_health_status_installed(
    app: FastAPI,
) -> bool:
    """Return whether consolidated health integration is installed."""
    if not isinstance(app, FastAPI):
        raise TypeError("app must be a FastAPI application")

    installed = getattr(
        app.state,
        HEALTH_STATUS_INSTALLATION_STATE_KEY,
        False,
    )

    snapshot = getattr(
        app.state,
        HEALTH_STATUS_STATE_KEY,
        None,
    )

    return (
        installed is True
        and isinstance(snapshot, SecurityAuditSubsystemHealth)
    )


def get_configuration_api_security_audit_health_status_snapshot(
    app: FastAPI,
) -> SecurityAuditSubsystemHealth:
    """Return the last consolidated health snapshot."""
    if not isinstance(app, FastAPI):
        raise TypeError("app must be a FastAPI application")

    if not is_configuration_api_security_audit_health_status_installed(app):
        raise SecurityAuditHealthStatusIntegrationError(
            "Consolidated security audit health status is not installed"
        )

    snapshot = getattr(
        app.state,
        HEALTH_STATUS_STATE_KEY,
        None,
    )

    if not isinstance(snapshot, SecurityAuditSubsystemHealth):
        raise SecurityAuditHealthStatusIntegrationError(
            "Consolidated security audit health snapshot is unavailable"
        )

    return snapshot


def check_configuration_api_security_audit_health_status(
    app: FastAPI,
    *,
    checked_at: datetime | None = None,
) -> SecurityAuditSubsystemHealth:
    """Run component checks and build a fresh consolidated snapshot.

    The result is also stored in application state.

    Args:
        app: FastAPI application.
        checked_at: Optional timezone-aware snapshot timestamp.

    Returns:
        A fresh consolidated health snapshot.

    Raises:
        TypeError: If app is invalid.
        SecurityAuditHealthStatusIntegrationError: If integration
            is not installed or snapshot construction fails.
    """
    if not isinstance(app, FastAPI):
        raise TypeError("app must be a FastAPI application")

    if not is_configuration_api_security_audit_health_status_installed(app):
        raise SecurityAuditHealthStatusIntegrationError(
            "Consolidated security audit health status is not installed"
        )

    try:
        report = _get_audit_report(app)
        api_installed = (
            is_configuration_api_security_audit_health_api_installed(app)
        )
        api_prefix = _get_api_prefix(app, api_installed)

        snapshot = build_security_audit_health_status(
            audit_report=report,
            api_installed=api_installed,
            api_prefix=api_prefix,
            checked_at=checked_at,
        )

        setattr(app.state, HEALTH_STATUS_STATE_KEY, snapshot)

        return snapshot

    except SecurityAuditHealthStatusIntegrationError:
        raise
    except Exception as exc:
        raise SecurityAuditHealthStatusIntegrationError(
            "Could not build consolidated security audit health status"
        ) from exc


def get_configuration_api_security_audit_health_status_dict(
    app: FastAPI,
    *,
    refresh: bool = True,
) -> dict[str, Any]:
    """Return a JSON-compatible consolidated health status.

    Args:
        app: FastAPI application.
        refresh: Run new component checks when True. When False,
            return the last stored snapshot.

    Returns:
        JSON-compatible health status dictionary.
    """
    if not isinstance(app, FastAPI):
        raise TypeError("app must be a FastAPI application")

    if not isinstance(refresh, bool):
        raise TypeError("refresh must be a boolean")

    if refresh:
        snapshot = check_configuration_api_security_audit_health_status(
            app
        )
    else:
        snapshot = (
            get_configuration_api_security_audit_health_status_snapshot(
                app
            )
        )

    return snapshot.to_dict()


def remove_configuration_api_security_audit_health_status(
    app: FastAPI,
) -> SecurityAuditSubsystemHealth:
    """Remove consolidated health integration state.

    This does not remove the audit logger, health service, or health API.
    It only removes the consolidated snapshot and installation metadata.

    Args:
        app: FastAPI application.

    Returns:
        The last stored health snapshot.
    """
    if not isinstance(app, FastAPI):
        raise TypeError("app must be a FastAPI application")

    snapshot = (
        get_configuration_api_security_audit_health_status_snapshot(
            app
        )
    )

    setattr(app.state, HEALTH_STATUS_STATE_KEY, None)
    setattr(
        app.state,
        HEALTH_STATUS_INSTALLATION_STATE_KEY,
        False,
    )

    return snapshot
