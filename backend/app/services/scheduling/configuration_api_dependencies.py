"""FastAPI dependency providers for scheduling configuration APIs."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import HTTPException, Request, status

from app.services.scheduling.configuration_api import (
    ConfigurationApiDependencies,
)
from app.services.scheduling.configuration_permissions import (
    ConfigurationPrincipal,
)


PrincipalResolver = Callable[
    [Request],
    ConfigurationPrincipal | Awaitable[ConfigurationPrincipal],
]


def get_configuration_api_dependencies(
    request: Request,
) -> ConfigurationApiDependencies:
    """Retrieve scheduling API dependencies from application state."""

    dependencies = getattr(
        request.app.state,
        "configuration_api_dependencies",
        None,
    )

    if not isinstance(dependencies, ConfigurationApiDependencies):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Scheduling configuration services are unavailable",
        )

    return dependencies


async def get_configuration_principal(
    request: Request,
) -> ConfigurationPrincipal:
    """Resolve the authenticated configuration principal."""

    resolver: Any = getattr(
        request.app.state,
        "configuration_principal_resolver",
        None,
    )

    if resolver is None or not callable(resolver):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication principal resolver is not configured",
        )

    try:
        principal = resolver(request)

        if inspect.isawaitable(principal):
            principal = await principal

    except HTTPException:
        raise

    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unable to resolve authenticated principal",
        ) from exc

    if not isinstance(principal, ConfigurationPrincipal):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authenticated principal",
        )

    if not principal.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authenticated principal is inactive",
        )

    return principal


def configure_configuration_api(
    app: Any,
    *,
    dependencies: ConfigurationApiDependencies,
    principal_resolver: PrincipalResolver,
) -> None:
    """Register configuration API dependencies on a FastAPI application."""

    if not isinstance(dependencies, ConfigurationApiDependencies):
        raise TypeError(
            "dependencies must be ConfigurationApiDependencies"
        )

    if not callable(principal_resolver):
        raise TypeError(
            "principal_resolver must be callable"
        )

    if not hasattr(app, "state"):
        raise TypeError(
            "app must expose FastAPI-compatible application state"
        )

    app.state.configuration_api_dependencies = dependencies
    app.state.configuration_principal_resolver = principal_resolver
