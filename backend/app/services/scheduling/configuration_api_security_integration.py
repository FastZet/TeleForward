
"""FastAPI integration for scheduling configuration API security."""

from __future__ import annotations

import inspect
import logging
from typing import Any, Awaitable, Callable

from fastapi import FastAPI, HTTPException, Request

from app.services.scheduling.configuration_api_security import (
    ConfigurationApiSecurity,
)
from app.services.scheduling.configuration_permissions import (
    ConfigurationPrincipal,
)


logger = logging.getLogger(__name__)

SECURITY_STATE_KEY = "configuration_api_security"
PRINCIPAL_RESOLVER_STATE_KEY = "configuration_principal_resolver"

PrincipalResolver = Callable[
    [Request],
    ConfigurationPrincipal | None
    | Awaitable[ConfigurationPrincipal | None],
]


def install_configuration_api_security(
    app: FastAPI,
    *,
    security: ConfigurationApiSecurity,
    principal_resolver: PrincipalResolver,
) -> None:
    """Register configuration API security dependencies on FastAPI.

    Args:
        app: FastAPI application.
        security: Configured ConfigurationApiSecurity instance.
        principal_resolver: Trusted callback that resolves the
            authenticated principal from an incoming request.

    The principal resolver must use trusted authentication context.
    It must not construct principals from arbitrary client-supplied
    identity headers.
    """

    if not isinstance(app, FastAPI):
        raise TypeError("app must be a FastAPI application")

    if not isinstance(security, ConfigurationApiSecurity):
        raise TypeError(
            "security must be a ConfigurationApiSecurity instance"
        )

    if not callable(principal_resolver):
        raise TypeError("principal_resolver must be callable")

    if getattr(app.state, SECURITY_STATE_KEY, None) is not None:
        raise RuntimeError(
            "Configuration API security is already installed"
        )

    setattr(app.state, SECURITY_STATE_KEY, security)
    setattr(
        app.state,
        PRINCIPAL_RESOLVER_STATE_KEY,
        principal_resolver,
    )

    logger.info(
        "Configuration API security registered",
        extra={
            "principal_resolver_configured": True,
        },
    )


def get_configuration_api_security(
    app: FastAPI,
) -> ConfigurationApiSecurity:
    """Retrieve the configured security service."""

    if not isinstance(app, FastAPI):
        raise TypeError("app must be a FastAPI application")

    security = getattr(
        app.state,
        SECURITY_STATE_KEY,
        None,
    )

    if not isinstance(security, ConfigurationApiSecurity):
        raise RuntimeError(
            "Configuration API security has not been installed"
        )

    return security


def get_configuration_principal_resolver(
    app: FastAPI,
) -> PrincipalResolver:
    """Retrieve the configured principal resolver."""

    if not isinstance(app, FastAPI):
        raise TypeError("app must be a FastAPI application")

    resolver = getattr(
        app.state,
        PRINCIPAL_RESOLVER_STATE_KEY,
        None,
    )

    if not callable(resolver):
        raise RuntimeError(
            "Configuration API principal resolver has not been installed"
        )

    return resolver


async def resolve_configuration_api_principal(
    request: Request,
) -> ConfigurationPrincipal:
    """Resolve and validate the authenticated configuration principal."""

    resolver = get_configuration_principal_resolver(
        request.app
    )

    try:
        principal = resolver(request)

        if inspect.isawaitable(principal):
            principal = await principal

    except HTTPException:
        raise

    except Exception as exc:
        logger.exception(
            "Configuration API principal resolution failed"
        )

        raise HTTPException(
            status_code=401,
            detail="Unable to resolve authenticated principal",
        ) from exc

    if principal is None:
        raise HTTPException(
            status_code=401,
            detail="Authentication is required",
        )

    if not isinstance(principal, ConfigurationPrincipal):
        logger.error(
            "Principal resolver returned an invalid principal type"
        )

        raise HTTPException(
            status_code=401,
            detail="Invalid authenticated principal",
        )

    if not principal.is_active:
        raise HTTPException(
            status_code=403,
            detail="Authenticated principal is inactive",
        )

    return principal


async def validate_configuration_api_request(
    request: Request,
    principal: ConfigurationPrincipal | None = None,
) -> Any:
    """Validate the current request using ConfigurationApiSecurity.

    The security service is responsible for checking the principal,
    HTTP method, request path, and its configured rate-limit policy.

    This function is intended for use as a FastAPI dependency or
    directly from configuration API endpoints.
    """

    security = get_configuration_api_security(
        request.app
    )

    if principal is None:
        principal = await resolve_configuration_api_principal(
            request
        )

    if not isinstance(principal, ConfigurationPrincipal):
        raise HTTPException(
            status_code=401,
            detail="Invalid authenticated principal",
        )

    if not principal.is_active:
        raise HTTPException(
            status_code=403,
            detail="Authenticated principal is inactive",
        )

    try:
        result = security.validate_request(
            principal=principal,
            method=request.method,
            path=request.url.path,
        )

        if inspect.isawaitable(result):
            result = await result

        return result

    except HTTPException:
        raise

    except Exception as exc:
        logger.exception(
            "Configuration API request security validation failed"
        )

        raise HTTPException(
            status_code=403,
            detail="Configuration API request was rejected",
        ) from exc
