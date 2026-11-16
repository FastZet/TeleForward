
"""Combined FastAPI integration for bootstrap health and its API."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from fastapi import FastAPI

from app.services.scheduling.integration_bootstrap import (
    SchedulingIntegrationBootstrap,
)
from app.services.scheduling.integration_bootstrap_health import (
    BootstrapHealthReport,
    BootstrapHealthStatus,
    SchedulingBootstrapHealthService,
)
from app.services.scheduling.integration_bootstrap_health_api import (
    BOOTSTRAP_HEALTH_API_STATE_KEY,
    install_bootstrap_health_api,
    is_bootstrap_health_api_installed,
)
from app.services.scheduling.integration_bootstrap_health_integration import (
    BootstrapHealthIntegrationError,
    get_bootstrap_health,
    get_bootstrap_health_optional,
    install_bootstrap_health,
    is_bootstrap_health_installed,
    remove_bootstrap_health,
)


BOOTSTRAP_HEALTH_API_INTEGRATION_STATE_KEY = (
    "scheduling_bootstrap_health_api_integration"
)


class BootstrapHealthAPIIntegrationError(RuntimeError):
    """Raised when combined bootstrap health API integration fails."""


@dataclass(frozen=True, slots=True)
class BootstrapHealthAPIIntegrationStatus:
    """Snapshot of the combined integration state."""

    installed: bool
    service_installed: bool
    api_installed: bool
    service_matches_registration: bool


@dataclass(frozen=True, slots=True)
class BootstrapHealthAPIIntegration:
    """Metadata describing an installed combined integration."""

    service: SchedulingBootstrapHealthService
    router: object


def _validate_app(app: FastAPI) -> None:
    if not isinstance(app, FastAPI):
        raise TypeError("app must be a FastAPI instance")


def _get_registration(
    app: FastAPI,
) -> BootstrapHealthAPIIntegration | None:
    registration = getattr(
        app.state,
        BOOTSTRAP_HEALTH_API_INTEGRATION_STATE_KEY,
        None,
    )

    if registration is None:
        return None

    if not isinstance(registration, BootstrapHealthAPIIntegration):
        raise BootstrapHealthAPIIntegrationError(
            "Combined bootstrap health integration state is invalid"
        )

    return registration


def install_bootstrap_health_api_integration(
    app: FastAPI,
    service: SchedulingBootstrapHealthService | None = None,
    *,
    bootstrap: SchedulingIntegrationBootstrap | None = None,
    replace: bool = False,
) -> BootstrapHealthAPIIntegration:
    """Install the health service and its HTTP API together.

    Installation is idempotent when the same service is already
    registered through this integration.

    If API installation fails after a new service has been installed,
    the newly installed service is removed as a rollback operation.
    """
    _validate_app(app)

    if service is not None and bootstrap is not None:
        raise ValueError(
            "Provide either service or bootstrap, not both"
        )

    registration = _get_registration(app)

    if registration is not None:
        if (
            service is not None
            and registration.service is service
            and is_bootstrap_health_installed(app)
            and is_bootstrap_health_api_installed(app)
        ):
            return registration

        if not replace:
            raise BootstrapHealthAPIIntegrationError(
                "Combined bootstrap health integration is already installed"
            )

        raise BootstrapHealthAPIIntegrationError(
            "Replacing an installed API integration is not supported; "
            "remove its service integration and install a new one"
        )

    existing_service = get_bootstrap_health_optional(app)

    if existing_service is not None and not replace:
        raise BootstrapHealthAPIIntegrationError(
            "A bootstrap health service is already installed independently"
        )

    if existing_service is not None and service is not None:
        raise BootstrapHealthAPIIntegrationError(
            "An existing service cannot be replaced while another "
            "service instance is explicitly supplied"
        )

    if existing_service is not None and bootstrap is not None:
        raise BootstrapHealthAPIIntegrationError(
            "An existing service cannot be replaced while a bootstrap "
            "instance is explicitly supplied"
        )

    if is_bootstrap_health_api_installed(app):
        raise BootstrapHealthAPIIntegrationError(
            "Bootstrap health API is already installed independently"
        )

    installed_service: SchedulingBootstrapHealthService | None = None
    service_was_installed_here = False

    try:
        if existing_service is not None:
            if not replace:
                raise BootstrapHealthAPIIntegrationError(
                    "Bootstrap health service already exists"
                )

            remove_bootstrap_health(
                app,
                expected_service=existing_service,
            )

        installed_service = install_bootstrap_health(
            app,
            service,
            bootstrap=bootstrap,
        )
        service_was_installed_here = True

        router = install_bootstrap_health_api(app)

        result = BootstrapHealthAPIIntegration(
            service=installed_service,
            router=router,
        )

        setattr(
            app.state,
            BOOTSTRAP_HEALTH_API_INTEGRATION_STATE_KEY,
            result,
        )

        return result

    except Exception as exc:
        if service_was_installed_here and installed_service is not None:
            try:
                remove_bootstrap_health(
                    app,
                    expected_service=installed_service,
                )
            except Exception as cleanup_error:
                raise BootstrapHealthAPIIntegrationError(
                    "Installation failed and the newly installed "
                    "health service could not be rolled back"
                ) from cleanup_error

        if isinstance(exc, BootstrapHealthAPIIntegrationError):
            raise

        raise BootstrapHealthAPIIntegrationError(
            "Failed to install combined bootstrap health API integration"
        ) from exc


def get_bootstrap_health_api_integration(
    app: FastAPI,
) -> BootstrapHealthAPIIntegration:
    """Retrieve the combined integration registration."""
    _validate_app(app)

    registration = _get_registration(app)

    if registration is None:
        raise BootstrapHealthAPIIntegrationError(
            "Combined bootstrap health integration is not installed"
        )

    return registration


def get_bootstrap_health_api_integration_optional(
    app: FastAPI,
) -> BootstrapHealthAPIIntegration | None:
    """Retrieve the registration without raising when absent."""
    _validate_app(app)
    return _get_registration(app)


def is_bootstrap_health_api_integration_installed(
    app: FastAPI,
) -> bool:
    """Return whether the combined integration is fully installed."""
    _validate_app(app)

    registration = _get_registration(app)

    if registration is None:
        return False

    service = get_bootstrap_health_optional(app)

    return (
        service is registration.service
        and is_bootstrap_health_api_installed(app)
    )


def get_bootstrap_health_api_integration_status(
    app: FastAPI,
) -> BootstrapHealthAPIIntegrationStatus:
    """Return a consistent snapshot of integration installation."""
    _validate_app(app)

    registration = _get_registration(app)
    service = get_bootstrap_health_optional(app)
    service_installed = service is not None
    api_installed = is_bootstrap_health_api_installed(app)

    matches = (
        registration is not None
        and service is registration.service
    )

    fully_installed = (
        registration is not None
        and matches
        and service_installed
        and api_installed
    )

    return BootstrapHealthAPIIntegrationStatus(
        installed=fully_installed,
        service_installed=service_installed,
        api_installed=api_installed,
        service_matches_registration=matches,
    )


def get_integrated_bootstrap_health_report(
    app: FastAPI,
) -> BootstrapHealthReport:
    """Retrieve the report through the registered integration."""
    registration = get_bootstrap_health_api_integration(app)

    service = get_bootstrap_health(app)

    if service is not registration.service:
        raise BootstrapHealthAPIIntegrationError(
            "Installed health service does not match the integration"
        )

    if not is_bootstrap_health_api_installed(app):
        raise BootstrapHealthAPIIntegrationError(
            "Bootstrap health API router is not installed"
        )

    try:
        return service.inspect()
    except Exception as exc:
        raise BootstrapHealthAPIIntegrationError(
            "Unable to inspect integrated bootstrap health"
        ) from exc


def get_integrated_bootstrap_health_status(
    app: FastAPI,
) -> BootstrapHealthStatus:
    """Return the health classification through the integration."""
    return get_integrated_bootstrap_health_report(app).status


def is_integrated_bootstrap_healthy(app: FastAPI) -> bool:
    """Return whether the integrated bootstrap is healthy."""
    return (
        get_integrated_bootstrap_health_status(app)
        is BootstrapHealthStatus.HEALTHY
    )


def remove_bootstrap_health_api_integration(
    app: FastAPI,
    *,
    remove_service: bool = True,
) -> BootstrapHealthAPIIntegration:
    """Remove the combined integration registration and service.

    FastAPI routes cannot safely be removed after registration.
    Consequently, the HTTP route remains registered and returns HTTP
    503 after the health service has been removed.
    """
    _validate_app(app)

    registration = get_bootstrap_health_api_integration(app)

    current_service = get_bootstrap_health_optional(app)

    if current_service is not registration.service:
        raise BootstrapHealthAPIIntegrationError(
            "The installed health service no longer matches "
            "the combined integration"
        )

    if remove_service:
        try:
            remove_bootstrap_health(
                app,
                expected_service=registration.service,
            )
        except BootstrapHealthIntegrationError as exc:
            raise BootstrapHealthAPIIntegrationError(
                "Failed to remove the integrated health service"
            ) from exc

    delattr(
        app.state,
        BOOTSTRAP_HEALTH_API_INTEGRATION_STATE_KEY,
    )

    return registration
