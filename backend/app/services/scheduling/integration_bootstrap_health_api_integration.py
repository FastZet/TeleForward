
"""Combined FastAPI integration for bootstrap health and its API."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import APIRouter, FastAPI

from app.services.scheduling.integration_bootstrap import (
    SchedulingIntegrationBootstrap,
)
from app.services.scheduling.integration_bootstrap_health import (
    BootstrapHealthReport,
    BootstrapHealthStatus,
    SchedulingBootstrapHealthService,
)
from app.services.scheduling.integration_bootstrap_health_api import (
    install_bootstrap_health_api,
    is_bootstrap_health_api_installed,
)
from app.services.scheduling.integration_bootstrap_health_integration import (
    BOOTSTRAP_HEALTH_STATE_KEY,
    BootstrapHealthIntegrationError,
    get_bootstrap_health_optional,
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
    router: APIRouter


def _validate_app(app: FastAPI) -> None:
    if not isinstance(app, FastAPI):
        raise TypeError("app must be a FastAPI instance")


def _validate_service(
    service: SchedulingBootstrapHealthService,
) -> None:
    if not isinstance(service, SchedulingBootstrapHealthService):
        raise TypeError(
            "service must be a SchedulingBootstrapHealthService"
        )


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


def _create_service(
    service: SchedulingBootstrapHealthService | None,
    bootstrap: SchedulingIntegrationBootstrap | None,
) -> SchedulingBootstrapHealthService:
    if service is not None and bootstrap is not None:
        raise ValueError(
            "Provide either service or bootstrap, not both"
        )

    if service is not None:
        _validate_service(service)
        return service

    return SchedulingBootstrapHealthService(bootstrap=bootstrap)


def install_bootstrap_health_api_integration(
    app: FastAPI,
    service: SchedulingBootstrapHealthService | None = None,
    *,
    bootstrap: SchedulingIntegrationBootstrap | None = None,
    replace: bool = False,
) -> BootstrapHealthAPIIntegration:
    """Install the health service and HTTP API together.

    Repeated installation with the same service is idempotent.

    An independently installed service may be replaced when
    replace=True. The original service remains installed until
    API installation succeeds.

    FastAPI routes cannot be removed after registration. Therefore,
    an existing independent API router cannot be replaced safely.
    """
    _validate_app(app)

    candidate_service = _create_service(service, bootstrap)
    registration = _get_registration(app)

    existing_service = get_bootstrap_health_optional(app)
    api_installed = is_bootstrap_health_api_installed(app)

    if registration is not None:
        if (
            registration.service is candidate_service
            and existing_service is candidate_service
            and api_installed
        ):
            return registration

        if not replace:
            raise BootstrapHealthAPIIntegrationError(
                "Combined bootstrap health integration is already installed"
            )

        raise BootstrapHealthAPIIntegrationError(
            "Replacing a registered combined API integration is "
            "unsupported because FastAPI routes cannot be safely removed"
        )

    if existing_service is not None:
        if not replace:
            raise BootstrapHealthAPIIntegrationError(
                "A bootstrap health service is already installed independently"
            )

    if api_installed:
        raise BootstrapHealthAPIIntegrationError(
            "Bootstrap health API is already installed independently"
        )

    # Install the API first. The existing service is not modified if
    # router installation fails.
    try:
        router = install_bootstrap_health_api(app)

    except Exception as exc:
        raise BootstrapHealthAPIIntegrationError(
            "Failed to install bootstrap health API router"
        ) from exc

    # After API installation succeeds, replace the service reference
    # directly. This avoids a remove-then-install gap.
    try:
        setattr(
            app.state,
            BOOTSTRAP_HEALTH_STATE_KEY,
            candidate_service,
        )

        result = BootstrapHealthAPIIntegration(
            service=candidate_service,
            router=router,
        )

        setattr(
            app.state,
            BOOTSTRAP_HEALTH_API_INTEGRATION_STATE_KEY,
            result,
        )

        return result

    except Exception as exc:
        # The router cannot be safely removed. Restore the original
        # service reference and report the partial installation.
        try:
            if existing_service is None:
                if hasattr(app.state, BOOTSTRAP_HEALTH_STATE_KEY):
                    delattr(app.state, BOOTSTRAP_HEALTH_STATE_KEY)
            else:
                setattr(
                    app.state,
                    BOOTSTRAP_HEALTH_STATE_KEY,
                    existing_service,
                )
        except Exception as rollback_error:
            raise BootstrapHealthAPIIntegrationError(
                "Installation failed and the original health service "
                "could not be restored"
            ) from rollback_error

        raise BootstrapHealthAPIIntegrationError(
            "Health API router was installed, but service registration "
            "failed. The router remains registered."
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
    """Return a snapshot of the integration components."""
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
    """Retrieve the report through the combined integration."""
    registration = get_bootstrap_health_api_integration(app)

    service = get_bootstrap_health_optional(app)

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
    """Return the integrated bootstrap health classification."""
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
    """Remove combined integration metadata and optionally its service.

    The FastAPI route remains registered. If the service is removed,
    requests to the route will return HTTP 503.

    The underlying bootstrap is not closed by this operation.
    """
    _validate_app(app)

    registration = get_bootstrap_health_api_integration(app)

    current_service = get_bootstrap_health_optional(app)

    if current_service is not registration.service:
        raise BootstrapHealthAPIIntegrationError(
            "Installed health service no longer matches the integration"
        )

    if remove_service:
        try:
            delattr(app.state, BOOTSTRAP_HEALTH_STATE_KEY)
        except AttributeError as exc:
            raise BootstrapHealthAPIIntegrationError(
                "Failed to remove the integrated health service"
            ) from exc

    try:
        delattr(
            app.state,
            BOOTSTRAP_HEALTH_API_INTEGRATION_STATE_KEY,
        )
    except Exception as exc:
        # Restore the service if its removal was requested.
        if remove_service:
            try:
                setattr(
                    app.state,
                    BOOTSTRAP_HEALTH_STATE_KEY,
                    registration.service,
                )
            except Exception:
                logger.exception(
                    "Could not restore bootstrap health service after "
                    "integration metadata removal failed"
                )

        raise BootstrapHealthAPIIntegrationError(
            "Failed to remove combined integration metadata"
        ) from exc

    return registration
