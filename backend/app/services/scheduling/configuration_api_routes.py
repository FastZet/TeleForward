"""Route registration for scheduling configuration APIs."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI

from app.services.scheduling.configuration_api import (
    ConfigurationApiDependencies,
    create_configuration_router,
)
from app.services.scheduling.configuration_api_dependencies import (
    configure_configuration_api,
    get_configuration_principal,
)
from app.services.scheduling.configuration_api_errors import (
    register_configuration_exception_handlers,
)


logger = logging.getLogger(__name__)

DEFAULT_CONFIGURATION_API_PREFIX = "/api/v1"


def register_configuration_api(
    app: FastAPI,
    dependencies: ConfigurationApiDependencies,
    principal_resolver: Any,
    *,
    prefix: str = DEFAULT_CONFIGURATION_API_PREFIX,
) -> None:
    """Configure and register scheduling configuration routes.

    Args:
        app: Main FastAPI application.
        dependencies: Scheduling configuration service dependencies.
        principal_resolver: Sync or async callable resolving an authenticated
            ConfigurationPrincipal from a Request.
        prefix: API version prefix.

    Raises:
        TypeError: If supplied application dependencies are invalid.
        ValueError: If the API prefix is invalid.
    """

    if not isinstance(app, FastAPI):
        raise TypeError("app must be a FastAPI instance")

    if not isinstance(
        dependencies,
        ConfigurationApiDependencies,
    ):
        raise TypeError(
            "dependencies must be ConfigurationApiDependencies"
        )

    if not callable(principal_resolver):
        raise TypeError(
            "principal_resolver must be callable"
        )

    if not isinstance(prefix, str):
        raise TypeError("prefix must be a string")

    normalized_prefix = prefix.strip().rstrip("/")

    if not normalized_prefix.startswith("/"):
        raise ValueError("prefix must start with '/'")

    if normalized_prefix == "/":
        raise ValueError("prefix must not be the root path")

    if getattr(
        app.state,
        "configuration_api_registered",
        False,
    ):
        raise RuntimeError(
            "Scheduling configuration API is already registered"
        )

    configure_configuration_api(
        app,
        dependencies=dependencies,
        principal_resolver=principal_resolver,
    )

    router = create_configuration_router(
        dependencies,
        principal_dependency=get_configuration_principal,
    )

    # Include the version prefix without modifying the router's own prefix.
    app.include_router(
        router,
        prefix=normalized_prefix,
    )

    register_configuration_exception_handlers(app)

    app.state.configuration_api_registered = True

    logger.info(
        "Scheduling configuration API registered at %s%s",
        normalized_prefix,
        router.prefix,
    )
