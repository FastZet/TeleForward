
"""FastAPI application integration for configuration security routes."""

from __future__ import annotations

import logging
from typing import Sequence

from fastapi import APIRouter, FastAPI

from app.services.scheduling.configuration_api_security_routes import (
    create_configuration_security_router,
)
from app.services.scheduling.configuration_permissions import (
    ConfigurationPermissionService,
)


logger = logging.getLogger(__name__)

ROUTES_INSTALLED_STATE_KEY = (
    "configuration_api_security_routes_installed"
)

ROUTES_PREFIX_STATE_KEY = (
    "configuration_api_security_routes_prefix"
)


def install_configuration_api_security_routes(
    app: FastAPI,
    *,
    permission_service: ConfigurationPermissionService,
    prefix: str = "/configuration/security",
    tags: list[str] | None = None,
) -> APIRouter:
    """Create and install configuration security diagnostic routes.

    Configuration API security must already have been installed using
    the configuration API security integration module.

    Args:
        app: FastAPI application.
        permission_service: Permission evaluation service.
        prefix: URL prefix for security diagnostic endpoints.
        tags: Optional OpenAPI tags.

    Returns:
        The installed APIRouter.

    Raises:
        TypeError: If an argument has an invalid type.
        RuntimeError: If security is not installed or routes were
            already registered.
        ValueError: If the route prefix is invalid.
    """

    if not isinstance(app, FastAPI):
        raise TypeError("app must be a FastAPI application")

    if not isinstance(
        permission_service,
        ConfigurationPermissionService,
    ):
        raise TypeError(
            "permission_service must be a ConfigurationPermissionService"
        )

    if not isinstance(prefix, str) or not prefix.startswith("/"):
        raise ValueError("prefix must be an absolute route prefix")

    if prefix == "/":
        raise ValueError("prefix must not be the root path")

    if getattr(app.state, "configuration_api_security", None) is None:
        raise RuntimeError(
            "Configuration API security must be installed before "
            "security routes"
        )

    if getattr(app.state, ROUTES_INSTALLED_STATE_KEY, False):
        raise RuntimeError(
            "Configuration API security routes are already installed"
        )

    router = create_configuration_security_router(
        permission_service=permission_service,
        prefix=prefix,
        tags=tags,
    )

    app.include_router(router)

    setattr(
        app.state,
        ROUTES_INSTALLED_STATE_KEY,
        True,
    )

    setattr(
        app.state,
        ROUTES_PREFIX_STATE_KEY,
        prefix.rstrip("/"),
    )

    logger.info(
        "Configuration API security routes installed",
        extra={
            "route_prefix": prefix.rstrip("/"),
        },
    )

    return router


def are_configuration_api_security_routes_installed(
    app: FastAPI,
) -> bool:
    """Return whether configuration security routes are installed."""

    if not isinstance(app, FastAPI):
        raise TypeError("app must be a FastAPI application")

    return bool(
        getattr(
            app.state,
            ROUTES_INSTALLED_STATE_KEY,
            False,
        )
    )


def get_configuration_api_security_routes_prefix(
    app: FastAPI,
) -> str | None:
    """Return the configured security route prefix."""

    if not isinstance(app, FastAPI):
        raise TypeError("app must be a FastAPI application")

    prefix = getattr(
        app.state,
        ROUTES_PREFIX_STATE_KEY,
        None,
    )

    if prefix is None:
        return None

    if not isinstance(prefix, str):
        logger.error(
            "Invalid configuration security route prefix in application state"
        )
        return None

    return prefix


def install_configuration_api_security_routes_with_router(
    app: FastAPI,
    *,
    router: APIRouter,
    prefix: str,
) -> None:
    """Install a preconstructed security router.

    This variant supports applications that construct routers through
    their own dependency-injection lifecycle.
    """

    if not isinstance(app, FastAPI):
        raise TypeError("app must be a FastAPI application")

    if not isinstance(router, APIRouter):
        raise TypeError("router must be an APIRouter")

    if not isinstance(prefix, str) or not prefix.startswith("/"):
        raise ValueError("prefix must be an absolute route prefix")

    if prefix == "/":
        raise ValueError("prefix must not be the root path")

    if getattr(app.state, "configuration_api_security", None) is None:
        raise RuntimeError(
            "Configuration API security must be installed before "
            "security routes"
        )

    if getattr(app.state, ROUTES_INSTALLED_STATE_KEY, False):
        raise RuntimeError(
            "Configuration API security routes are already installed"
        )

    app.include_router(router)

    setattr(
        app.state,
        ROUTES_INSTALLED_STATE_KEY,
        True,
    )

    setattr(
        app.state,
        ROUTES_PREFIX_STATE_KEY,
        prefix.rstrip("/"),
    )

    logger.info(
        "Preconstructed configuration API security router installed",
        extra={
            "route_prefix": prefix.rstrip("/"),
        },
    )


__all__ = [
    "ROUTES_INSTALLED_STATE_KEY",
    "ROUTES_PREFIX_STATE_KEY",
    "install_configuration_api_security_routes",
    "install_configuration_api_security_routes_with_router",
    "are_configuration_api_security_routes_installed",
    "get_configuration_api_security_routes_prefix",
]
