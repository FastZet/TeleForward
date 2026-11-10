
"""FastAPI integration for scheduling configuration API middleware."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI

from app.services.scheduling.configuration_api_middleware import (
    ConfigurationApiMiddleware,
    IdentityResolver,
)
from app.services.scheduling.configuration_api_security import (
    ConfigurationApiRateLimiter,
    RateLimitPolicy,
)


logger = logging.getLogger(__name__)

MIDDLEWARE_INSTALLED_STATE_KEY = (
    "configuration_api_middleware_installed"
)

RATE_LIMITER_STATE_KEY = "configuration_api_rate_limiter"

IDENTITY_RESOLVER_STATE_KEY = (
    "configuration_api_identity_resolver"
)


def install_configuration_api_middleware(
    app: FastAPI,
    *,
    api_prefix: str = "/api/v1/scheduling/configuration",
    max_request_body_bytes: int = 1_048_576,
    rate_limiter: ConfigurationApiRateLimiter | None = None,
    identity_resolver: IdentityResolver | None = None,
    enabled: bool = True,
) -> None:
    """Install configuration API middleware on a FastAPI application.

    The middleware must be installed before the application handles
    its first request.

    If dependencies are omitted, the function checks application
    state for previously configured instances. A default rate limiter
    is created when no rate limiter is configured.

    Identity resolver contract:
        The resolver receives an ASGI Scope and returns a stable
        identity string, either directly or asynchronously.

        It must obtain identity from trusted server-side authentication
        context. It must not trust arbitrary client-supplied headers.
    """

    if not isinstance(app, FastAPI):
        raise TypeError("app must be a FastAPI application")

    if not isinstance(enabled, bool):
        raise TypeError("enabled must be a boolean")

    if getattr(
        app.state,
        MIDDLEWARE_INSTALLED_STATE_KEY,
        False,
    ):
        raise RuntimeError(
            "Configuration API middleware is already installed"
        )

    if any(
        middleware.cls is ConfigurationApiMiddleware
        for middleware in app.user_middleware
    ):
        raise RuntimeError(
            "Configuration API middleware is already registered"
        )

    configured_rate_limiter = rate_limiter

    if configured_rate_limiter is None:
        configured_rate_limiter = getattr(
            app.state,
            RATE_LIMITER_STATE_KEY,
            None,
        )

    if configured_rate_limiter is None:
        configured_rate_limiter = ConfigurationApiRateLimiter(
            RateLimitPolicy()
        )

    if not callable(
        getattr(configured_rate_limiter, "check", None)
    ):
        raise TypeError(
            "rate_limiter must provide an asynchronous check(identity) method"
        )

    configured_identity_resolver = identity_resolver

    if configured_identity_resolver is None:
        configured_identity_resolver = getattr(
            app.state,
            IDENTITY_RESOLVER_STATE_KEY,
            None,
        )

    if (
        configured_identity_resolver is not None
        and not callable(configured_identity_resolver)
    ):
        raise TypeError(
            "identity_resolver must be callable"
        )

    # Store the configured dependencies so other application
    # components can inspect or reuse the same instances.
    setattr(
        app.state,
        RATE_LIMITER_STATE_KEY,
        configured_rate_limiter,
    )

    setattr(
        app.state,
        IDENTITY_RESOLVER_STATE_KEY,
        configured_identity_resolver,
    )

    try:
        app.add_middleware(
            ConfigurationApiMiddleware,
            api_prefix=api_prefix,
            max_request_body_bytes=max_request_body_bytes,
            rate_limiter=configured_rate_limiter,
            identity_resolver=configured_identity_resolver,
            enabled=enabled,
        )
    except RuntimeError:
        logger.exception(
            "Unable to install configuration API middleware"
        )
        raise

    setattr(
        app.state,
        MIDDLEWARE_INSTALLED_STATE_KEY,
        True,
    )

    logger.info(
        "Configuration API middleware registered",
        extra={
            "api_prefix": api_prefix,
            "enabled": enabled,
            "max_request_body_bytes": max_request_body_bytes,
            "identity_resolver_configured": (
                configured_identity_resolver is not None
            ),
        },
    )


def is_configuration_api_middleware_installed(
    app: FastAPI,
) -> bool:
    """Return whether the integration helper registered the middleware."""

    if not isinstance(app, FastAPI):
        raise TypeError("app must be a FastAPI application")

    return bool(
        getattr(
            app.state,
            MIDDLEWARE_INSTALLED_STATE_KEY,
            False,
        )
    )


def get_configuration_api_rate_limiter(
    app: FastAPI,
) -> ConfigurationApiRateLimiter:
    """Retrieve the rate limiter configured for the application."""

    if not isinstance(app, FastAPI):
        raise TypeError("app must be a FastAPI application")

    rate_limiter = getattr(
        app.state,
        RATE_LIMITER_STATE_KEY,
        None,
    )

    if rate_limiter is None:
        raise RuntimeError(
            "Configuration API rate limiter has not been configured"
        )

    return rate_limiter


def get_configuration_api_identity_resolver(
    app: FastAPI,
) -> IdentityResolver | None:
    """Retrieve the configured identity resolver, if available."""

    if not isinstance(app, FastAPI):
        raise TypeError("app must be a FastAPI application")

    resolver: Any = getattr(
        app.state,
        IDENTITY_RESOLVER_STATE_KEY,
        None,
    )

    if resolver is not None and not callable(resolver):
        raise TypeError(
            "Configured configuration API identity resolver is invalid"
        )

    return resolver
