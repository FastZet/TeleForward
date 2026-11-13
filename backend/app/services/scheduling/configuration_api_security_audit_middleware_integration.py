
"""FastAPI integration helpers for security audit middleware."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI
from starlette.types import ASGIApp

from app.services.scheduling.configuration_api_security_audit import (
    SecurityAuditLogger,
)
from app.services.scheduling.configuration_api_security_audit_integration import (
    SecurityAuditIntegrationError,
    install_configuration_api_security_audit,
)
from app.services.scheduling.configuration_api_security_audit_middleware import (
    IdentityResolver,
    RateLimitCheck,
    SecurityAuditMiddleware,
)


logger = logging.getLogger(__name__)

MIDDLEWARE_STATE_KEY = "configuration_api_security_audit_middleware"
MIDDLEWARE_INSTALLATION_STATE_KEY = (
    "configuration_api_security_audit_middleware_installed"
)
MIDDLEWARE_CONFIGURATION_STATE_KEY = (
    "configuration_api_security_audit_middleware_configuration"
)


class SecurityAuditMiddlewareIntegrationError(RuntimeError):
    """Raised when security audit middleware integration fails."""


def install_configuration_api_security_audit_middleware(
    app: FastAPI,
    audit_logger: SecurityAuditLogger,
    *,
    identity_resolver: IdentityResolver | None = None,
    rate_limit_check: RateLimitCheck | None = None,
    max_request_body_bytes: int | None = None,
    audit_unhandled_exceptions: bool = True,
    replace_existing: bool = False,
) -> SecurityAuditMiddleware:
    """Install the audit logger and register its middleware with FastAPI.

    The audit middleware is registered through FastAPI's normal middleware
    stack. It is therefore applied to requests according to Starlette's
    middleware ordering rules.

    This function must be called before the application middleware stack
    has been built, normally during application construction.
    """
    if not isinstance(app, FastAPI):
        raise TypeError("app must be a FastAPI instance")

    if not isinstance(audit_logger, SecurityAuditLogger):
        raise TypeError("audit_logger must be a SecurityAuditLogger instance")

    existing = getattr(app.state, MIDDLEWARE_STATE_KEY, None)

    if existing is not None and not replace_existing:
        raise SecurityAuditMiddlewareIntegrationError(
            "Security audit middleware is already installed"
        )

    if existing is not None and replace_existing:
        raise SecurityAuditMiddlewareIntegrationError(
            "Replacing installed middleware requires rebuilding the "
            "application middleware stack; create a new application instance"
        )

    # Validate the middleware configuration before mutating application state.
    if (
        max_request_body_bytes is not None
        and (
            isinstance(max_request_body_bytes, bool)
            or not isinstance(max_request_body_bytes, int)
            or max_request_body_bytes < 1
        )
    ):
        raise ValueError(
            "max_request_body_bytes must be a positive integer"
        )

    # Register the audit logger first. This operation is idempotent for the
    # same logger instance and rejects conflicting logger instances.
    try:
        install_configuration_api_security_audit(
            app,
            audit_logger,
        )
    except SecurityAuditIntegrationError as exc:
        raise SecurityAuditMiddlewareIntegrationError(
            "Could not install the security audit logger"
        ) from exc

    middleware_options: dict[str, Any] = {
        "audit_app": app,
        "identity_resolver": identity_resolver,
        "rate_limit_check": rate_limit_check,
        "max_request_body_bytes": max_request_body_bytes,
        "audit_unhandled_exceptions": audit_unhandled_exceptions,
    }

    middleware_class: type[SecurityAuditMiddleware] = SecurityAuditMiddleware

    try:
        app.add_middleware(
            middleware_class,
            **middleware_options,
        )
    except RuntimeError as exc:
        raise SecurityAuditMiddlewareIntegrationError(
            "FastAPI middleware stack is already initialized. "
            "Install the security audit middleware before startup."
        ) from exc
    except Exception as exc:
        raise SecurityAuditMiddlewareIntegrationError(
            "Failed to register security audit middleware"
        ) from exc

    # Store the configuration only after middleware registration succeeds.
    setattr(app.state, MIDDLEWARE_STATE_KEY, middleware_class)
    setattr(app.state, MIDDLEWARE_INSTALLATION_STATE_KEY, True)
    setattr(
        app.state,
        MIDDLEWARE_CONFIGURATION_STATE_KEY,
        {
            "identity_resolver_configured": identity_resolver is not None,
            "rate_limit_check_configured": rate_limit_check is not None,
            "max_request_body_bytes": max_request_body_bytes,
            "audit_unhandled_exceptions": audit_unhandled_exceptions,
        },
    )

    logger.info("Configuration API security audit middleware installed")

    # Return the registered middleware class. The actual middleware instance
    # is created by Starlette when the application middleware stack is built.
    return middleware_class


def is_configuration_api_security_audit_middleware_installed(
    app: FastAPI,
) -> bool:
    """Return whether the middleware installer registered the middleware."""
    if not isinstance(app, FastAPI):
        raise TypeError("app must be a FastAPI instance")

    installed = getattr(
        app.state,
        MIDDLEWARE_INSTALLATION_STATE_KEY,
        False,
    )

    return installed is True


def get_configuration_api_security_audit_middleware(
    app: FastAPI,
) -> type[SecurityAuditMiddleware]:
    """Return the registered middleware class."""
    if not isinstance(app, FastAPI):
        raise TypeError("app must be a FastAPI instance")

    middleware_class = getattr(
        app.state,
        MIDDLEWARE_STATE_KEY,
        None,
    )

    if middleware_class is not SecurityAuditMiddleware:
        raise SecurityAuditMiddlewareIntegrationError(
            "Security audit middleware is not installed"
        )

    return middleware_class


def get_configuration_api_security_audit_middleware_configuration(
    app: FastAPI,
) -> dict[str, Any]:
    """Return a defensive copy of middleware installation settings."""
    if not isinstance(app, FastAPI):
        raise TypeError("app must be a FastAPI instance")

    configuration = getattr(
        app.state,
        MIDDLEWARE_CONFIGURATION_STATE_KEY,
        None,
    )

    if not isinstance(configuration, dict):
        raise SecurityAuditMiddlewareIntegrationError(
            "Security audit middleware configuration is unavailable"
        )

    return dict(configuration)


__all__ = [
    "MIDDLEWARE_CONFIGURATION_STATE_KEY",
    "MIDDLEWARE_INSTALLATION_STATE_KEY",
    "MIDDLEWARE_STATE_KEY",
    "SecurityAuditMiddlewareIntegrationError",
    "get_configuration_api_security_audit_middleware",
    "get_configuration_api_security_audit_middleware_configuration",
    "install_configuration_api_security_audit_middleware",
    "is_configuration_api_security_audit_middleware_installed",
]
