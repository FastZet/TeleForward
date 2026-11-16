
"""Tests for the combined bootstrap health API integration."""

from __future__ import annotations

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

import pytest

from app.services.scheduling.integration_bootstrap_health import (
    BootstrapHealthStatus,
    SchedulingBootstrapHealthService,
)
from app.services.scheduling.integration_bootstrap_health_api import (
    BOOTSTRAP_HEALTH_API_PATH,
    BOOTSTRAP_HEALTH_API_STATE_KEY,
)
from app.services.scheduling.integration_bootstrap_health_api_integration import (
    BOOTSTRAP_HEALTH_API_INTEGRATION_STATE_KEY,
    BootstrapHealthAPIIntegration,
    BootstrapHealthAPIIntegrationError,
    get_bootstrap_health_api_integration,
    get_bootstrap_health_api_integration_optional,
    get_bootstrap_health_api_integration_status,
    get_integrated_bootstrap_health_report,
    get_integrated_bootstrap_health_status,
    install_bootstrap_health_api_integration,
    is_integrated_bootstrap_healthy,
    is_bootstrap_health_api_integration_installed,
    remove_bootstrap_health_api_integration,
)
from app.services.scheduling.integration_bootstrap_health_integration import (
    BOOTSTRAP_HEALTH_STATE_KEY,
    get_bootstrap_health,
    is_bootstrap_health_installed,
)


def object_factory() -> object:
    return object()


@pytest.fixture
def app() -> FastAPI:
    return FastAPI()


@pytest.fixture
def service() -> SchedulingBootstrapHealthService:
    return SchedulingBootstrapHealthService()


@pytest.fixture
def installed(
    app: FastAPI,
    service: SchedulingBootstrapHealthService,
) -> BootstrapHealthAPIIntegration:
    return install_bootstrap_health_api_integration(
        app,
        service,
    )


def test_install_combined_integration(
    app: FastAPI,
    service: SchedulingBootstrapHealthService,
) -> None:
    integration = install_bootstrap_health_api_integration(
        app,
        service,
    )

    assert integration.service is service
    assert isinstance(integration.router, APIRouter)
    assert get_bootstrap_health(app) is service
    assert is_bootstrap_health_installed(app)
    assert is_bootstrap_health_api_integration_installed(app)


def test_install_records_combined_registration(
    app: FastAPI,
    installed: BootstrapHealthAPIIntegration,
) -> None:
    registration = getattr(
        app.state,
        BOOTSTRAP_HEALTH_API_INTEGRATION_STATE_KEY,
    )

    assert registration is installed


def test_install_registers_api_router(
    app: FastAPI,
    installed: BootstrapHealthAPIIntegration,
) -> None:
    paths = {
        route.path
        for route in app.routes
        if hasattr(route, "path")
    }

    assert BOOTSTRAP_HEALTH_API_PATH in paths


def test_install_rejects_invalid_app() -> None:
    with pytest.raises(TypeError):
        install_bootstrap_health_api_integration(
            object(),  # type: ignore[arg-type]
        )


def test_install_rejects_service_and_bootstrap_together(
    app: FastAPI,
    service: SchedulingBootstrapHealthService,
) -> None:
    from app.services.scheduling.integration_bootstrap import (
        SchedulingIntegrationBootstrap,
    )

    bootstrap = SchedulingIntegrationBootstrap(
        {
            "scheduler_manager": object_factory,
            "task_registry": object_factory,
            "job_store": object_factory,
        }
    )

    with pytest.raises(ValueError):
        install_bootstrap_health_api_integration(
            app,
            service,
            bootstrap=bootstrap,
        )


def test_install_rejects_duplicate_combined_integration(
    app: FastAPI,
    installed: BootstrapHealthAPIIntegration,
) -> None:
    with pytest.raises(BootstrapHealthAPIIntegrationError):
        install_bootstrap_health_api_integration(
            app,
            SchedulingBootstrapHealthService(),
        )


def test_install_same_service_is_idempotent(
    app: FastAPI,
    service: SchedulingBootstrapHealthService,
) -> None:
    first = install_bootstrap_health_api_integration(
        app,
        service,
    )
    second = install_bootstrap_health_api_integration(
        app,
        service,
    )

    assert first is second


def test_install_rejects_different_service_without_replace(
    app: FastAPI,
    installed: BootstrapHealthAPIIntegration,
) -> None:
    with pytest.raises(BootstrapHealthAPIIntegrationError):
        install_bootstrap_health_api_integration(
            app,
            SchedulingBootstrapHealthService(),
        )


def test_replace_combined_integration_is_rejected(
    app: FastAPI,
    installed: BootstrapHealthAPIIntegration,
) -> None:
    with pytest.raises(BootstrapHealthAPIIntegrationError):
        install_bootstrap_health_api_integration(
            app,
            SchedulingBootstrapHealthHealthServiceForTest(),
            replace=True,
        )

    assert get_bootstrap_health(app) is installed.service


class SchedulingBootstrapHealthHealthServiceForTest(
    SchedulingBootstrapHealthService
):
    """Distinct service instance used by replacement tests."""


def test_install_rejects_independently_installed_service(
    app: FastAPI,
    service: SchedulingBootstrapHealthService,
) -> None:
    from app.services.scheduling.integration_bootstrap_health_integration import (
        install_bootstrap_health,
    )

    install_bootstrap_health(app, service)

    with pytest.raises(BootstrapHealthAPIIntegrationError):
        install_bootstrap_health_api_integration(app)

    assert get_bootstrap_health(app) is service


def test_install_can_replace_independent_service(
    app: FastAPI,
    service: SchedulingBootstrapHealthService,
) -> None:
    from app.services.scheduling.integration_bootstrap_health_integration import (
        install_bootstrap_health,
    )

    install_bootstrap_health(app, service)

    integration = install_bootstrap_health_api_integration(
        app,
        replace=True,
    )

    assert integration.service is not service
    assert get_bootstrap_health(app) is integration.service


def test_install_rejects_independently_installed_api(
    app: FastAPI,
) -> None:
    from app.services.scheduling.integration_bootstrap_health_api import (
        install_bootstrap_health_api,
    )

    install_bootstrap_health_api(app)

    with pytest.raises(BootstrapHealthAPIIntegrationError):
        install_bootstrap_health_api_integration(app)

    assert is_bootstrap_health_api_integration_installed(app) is False


def test_get_registration(
    app: FastAPI,
    installed: BootstrapHealthAPIIntegration,
) -> None:
    assert get_bootstrap_health_api_integration(app) is installed


def test_get_registration_rejects_missing_integration(
    app: FastAPI,
) -> None:
    with pytest.raises(BootstrapHealthAPIIntegrationError):
        get_bootstrap_health_api_integration(app)


def test_get_optional_returns_none_when_missing(
    app: FastAPI,
) -> None:
    assert get_bootstrap_health_api_integration_optional(app) is None


def test_get_optional_returns_registration_when_installed(
    app: FastAPI,
    installed: BootstrapHealthAPIIntegration,
) -> None:
    assert (
        get_bootstrap_health_api_integration_optional(app)
        is installed
    )


def test_get_registration_rejects_invalid_state(
    app: FastAPI,
) -> None:
    setattr(
        app.state,
        BOOTSTRAP_HEALTH_API_INTEGRATION_STATE_KEY,
        object(),
    )

    with pytest.raises(BootstrapHealthAPIIntegrationError):
        get_bootstrap_health_api_integration(app)


def test_installation_status_is_true(
    app: FastAPI,
    installed: BootstrapHealthAPIIntegration,
) -> None:
    assert is_bootstrap_health_api_integration_installed(app) is True


def test_installation_status_is_false_when_missing(
    app: FastAPI,
) -> None:
    assert is_bootstrap_health_api_integration_installed(app) is False


def test_status_reports_all_components_installed(
    app: FastAPI,
    installed: BootstrapHealthAPIIntegration,
) -> None:
    result = get_bootstrap_health_api_integration_status(app)

    assert result.installed is True
    assert result.service_installed is True
    assert result.api_installed is True
    assert result.service_matches_registration is True


def test_status_detects_missing_service(
    app: FastAPI,
    installed: BootstrapHealthAPIIntegration,
) -> None:
    delattr(app.state, BOOTSTRAP_HEALTH_STATE_KEY)

    result = get_bootstrap_health_api_integration_status(app)

    assert result.installed is False
    assert result.service_installed is False
    assert result.api_installed is True
    assert result.service_matches_registration is False


def test_status_detects_missing_api_marker(
    app: FastAPI,
    installed: BootstrapHealthAPIIntegration,
) -> None:
    delattr(app.state, BOOTSTRAP_HEALTH_API_STATE_KEY)

    result = get_bootstrap_health_api_integration_status(app)

    assert result.installed is False
    assert result.service_installed is True
    assert result.api_installed is False


def test_status_detects_service_mismatch(
    app: FastAPI,
    installed: BootstrapHealthAPIIntegration,
) -> None:
    replacement = SchedulingBootstrapHealthService()

    setattr(
        app.state,
        BOOTSTRAP_HEALTH_STATE_KEY,
        replacement,
    )

    result = get_bootstrap_health_api_integration_status(app)

    assert result.installed is False
    assert result.service_installed is True
    assert result.service_matches_registration is False


def test_integrated_health_report(
    app: FastAPI,
    installed: BootstrapHealthAPIIntegration,
) -> None:
    report = get_integrated_bootstrap_health_report(app)

    assert report is not None
    assert report.status is BootstrapHealthStatus.UNAVAILABLE


def test_integrated_health_status(
    app: FastAPI,
    installed: BootstrapHealthAPIIntegration,
) -> None:
    assert (
        get_integrated_bootstrap_health_status(app)
        is BootstrapHealthStatus.UNAVAILABLE
    )


def test_integrated_health_check_returns_false(
    app: FastAPI,
    installed: BootstrapHealthAPIIntegration,
) -> None:
    assert is_integrated_bootstrap_healthy(app) is False


def test_report_retrieval_rejects_missing_registration(
    app: FastAPI,
) -> None:
    with pytest.raises(BootstrapHealthAPIIntegrationError):
        get_integrated_bootstrap_health_report(app)


def test_report_retrieval_rejects_service_mismatch(
    app: FastAPI,
    installed: BootstrapHealthAPIIntegration,
) -> None:
    setattr(
        app.state,
        BOOTSTRAP_HEALTH_STATE_KEY,
        SchedulingBootstrapHealthService(),
    )

    with pytest.raises(BootstrapHealthAPIIntegrationError):
        get_integrated_bootstrap_health_report(app)


def test_report_retrieval_rejects_missing_api(
    app: FastAPI,
    installed: BootstrapHealthAPIIntegration,
) -> None:
    delattr(app.state, BOOTSTRAP_HEALTH_API_STATE_KEY)

    with pytest.raises(BootstrapHealthAPIIntegrationError):
        get_integrated_bootstrap_health_report(app)


def test_remove_combined_integration(
    app: FastAPI,
    installed: BootstrapHealthAPIIntegration,
) -> None:
    removed = remove_bootstrap_health_api_integration(app)

    assert removed is installed
    assert get_bootstrap_health_api_integration_optional(app) is None
    assert is_bootstrap_health_installed(app) is False


def test_remove_keeps_api_route_registered(
    app: FastAPI,
    installed: BootstrapHealthAPIIntegration,
) -> None:
    remove_bootstrap_health_api_integration(app)

    paths = {
        route.path
        for route in app.routes
        if hasattr(route, "path")
    }

    assert BOOTSTRAP_HEALTH_API_PATH in paths


def test_removed_api_returns_service_unavailable(
    app: FastAPI,
    installed: BootstrapHealthAPIIntegration,
) -> None:
    remove_bootstrap_health_api_integration(app)

    response = TestClient(app).get(BOOTSTRAP_HEALTH_API_PATH)

    assert response.status_code == 503


def test_remove_without_removing_service(
    app: FastAPI,
    installed: BootstrapHealthAPIIntegration,
) -> None:
    service = installed.service

    removed = remove_bootstrap_health_api_integration(
        app,
        remove_service=False,
    )

    assert removed is installed
    assert get_bootstrap_health(app) is service
    assert is_bootstrap_health_installed(app) is True
    assert (
        get_bootstrap_health_api_integration_optional(app)
        is None
    )


def test_remove_rejects_missing_registration(
    app: FastAPI,
) -> None:
    with pytest.raises(BootstrapHealthAPIIntegrationError):
        remove_bootstrap_health_api_integration(app)


def test_remove_rejects_service_mismatch(
    app: FastAPI,
    installed: BootstrapHealthAPIIntegration,
) -> None:
    setattr(
        app.state,
        BOOTSTRAP_HEALTH_STATE_KEY,
        SchedulingBootstrapHealthService(),
    )

    with pytest.raises(BootstrapHealthAPIIntegrationError):
        remove_bootstrap_health_api_integration(app)

    assert (
        get_bootstrap_health_api_integration_optional(app)
        is installed
    )


def test_remove_rejects_invalid_app() -> None:
    with pytest.raises(TypeError):
        remove_bootstrap_health_api_integration(
            object(),  # type: ignore[arg-type]
        )


def test_remove_does_not_close_bootstrap(
    app: FastAPI,
) -> None:
    from app.services.scheduling.integration_bootstrap import (
        BootstrapState,
        SchedulingIntegrationBootstrap,
    )

    bootstrap = SchedulingIntegrationBootstrap(
        {
            "scheduler_manager": object_factory,
            "task_registry": object_factory,
            "job_store": object_factory,
        }
    )
    service = SchedulingBootstrapHealthService(bootstrap)

    install_bootstrap_health_api_integration(
        app,
        service,
    )

    remove_bootstrap_health_api_integration(app)

    assert bootstrap.state is BootstrapState.NOT_STARTED


def test_combined_installation_does_not_add_duplicate_routes(
    app: FastAPI,
    service: SchedulingBootstrapHealthService,
) -> None:
    first = install_bootstrap_health_api_integration(
        app,
        service,
    )
    second = install_bootstrap_health_api_integration(
        app,
        service,
    )

    assert first is second

    matching_routes = [
        route
        for route in app.routes
        if getattr(route, "path", None) == BOOTSTRAP_HEALTH_API_PATH
    ]

    assert len(matching_routes) == 1
