
"""Tests for scheduler runtime lifespan health API integration."""

from __future__ import annotations

from unittest.mock import Mock

import pytest
from fastapi import FastAPI

from app.services.scheduling import (
    scheduler_runtime_lifespan_health_api_integration as integration,
)
from app.services.scheduling.scheduler_runtime_lifespan_health import (
    SchedulerRuntimeLifespanHealthService,
)
from app.services.scheduling.scheduler_runtime_lifespan_health_integration import (
    get_scheduler_lifespan_health_optional,
    install_scheduler_lifespan_health,
)


@pytest.fixture
def app() -> FastAPI:
    """Create a FastAPI application."""

    return FastAPI()


@pytest.fixture
def service(
    app: FastAPI,
) -> SchedulerRuntimeLifespanHealthService:
    """Create a scheduler health service."""

    return SchedulerRuntimeLifespanHealthService(app=app)


def test_install_integrates_health_service_and_api(
    app: FastAPI,
) -> None:
    """Installation must register both integration components."""

    installed_service = (
        integration.install_scheduler_health_api_integration(
            app
        )
    )

    assert isinstance(
        installed_service,
        SchedulerRuntimeLifespanHealthService,
    )

    assert integration.is_scheduler_health_api_integrated(app)

    state = integration.get_scheduler_health_api_integration_status(
        app
    )

    assert state == {
        "integrated": True,
        "health_service_installed": True,
        "api_installed": True,
        "consistent": True,
    }

    assert "/health/scheduler" in {
        route.path
        for route in app.routes
    }


def test_install_uses_supplied_service(
    app: FastAPI,
    service: SchedulerRuntimeLifespanHealthService,
) -> None:
    """A supplied service must be installed and returned."""

    installed_service = (
        integration.install_scheduler_health_api_integration(
            app,
            service=service,
        )
    )

    assert installed_service is service

    assert (
        get_scheduler_lifespan_health_optional(app)
        is service
    )


def test_install_rejects_duplicate_integration(
    app: FastAPI,
) -> None:
    """Duplicate installation must be rejected by default."""

    integration.install_scheduler_health_api_integration(
        app
    )

    with pytest.raises(
        integration.SchedulerHealthAPIIntegrationError,
        match="already installed",
    ):
        integration.install_scheduler_health_api_integration(
            app
        )


def test_replace_returns_existing_service(
    app: FastAPI,
) -> None:
    """replace=True must preserve the existing integration."""

    original = integration.install_scheduler_health_api_integration(
        app
    )

    replacement = integration.install_scheduler_health_api_integration(
        app,
        replace=True,
    )

    assert replacement is original


def test_replace_rejects_different_service(
    app: FastAPI,
    service: SchedulerRuntimeLifespanHealthService,
) -> None:
    """Replacing the service behind an installed router is unsupported."""

    original = integration.install_scheduler_health_api_integration(
        app
    )

    assert original is not service

    with pytest.raises(
        integration.SchedulerHealthAPIIntegrationError,
        match="Replacing an installed health service",
    ):
        integration.install_scheduler_health_api_integration(
            app,
            service=service,
            replace=True,
        )

    assert (
        integration.get_scheduler_health_api_integration(app)
        is original
    )


def test_install_rejects_invalid_application() -> None:
    """Installation must require a FastAPI application."""

    with pytest.raises(
        TypeError,
        match="FastAPI instance",
    ):
        integration.install_scheduler_health_api_integration(
            Mock()
        )


def test_install_rejects_invalid_service(
    app: FastAPI,
) -> None:
    """Installation must validate the supplied service."""

    with pytest.raises(
        TypeError,
        match="SchedulerRuntimeLifespanHealthService",
    ):
        integration.install_scheduler_health_api_integration(
            app,
            service=Mock(),  # type: ignore[arg-type]
        )


def test_install_rejects_invalid_replace_argument(
    app: FastAPI,
) -> None:
    """The replace argument must be boolean."""

    with pytest.raises(
        TypeError,
        match="replace must be a boolean",
    ):
        integration.install_scheduler_health_api_integration(
            app,
            replace="true",  # type: ignore[arg-type]
        )


def test_api_installation_failure_rolls_back_new_service(
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A newly installed service must be removed on API failure."""

    def fail_api_installation(
        application: FastAPI,
        *,
        replace: bool = False,
    ) -> None:
        raise RuntimeError("Simulated API installation failure")

    monkeypatch.setattr(
        integration,
        "install_scheduler_health_api",
        fail_api_installation,
    )

    with pytest.raises(
        integration.SchedulerHealthAPIIntegrationError,
        match="Unable to install",
    ):
        integration.install_scheduler_health_api_integration(
            app
        )

    assert (
        get_scheduler_lifespan_health_optional(app)
        is None
    )

    assert not integration.is_scheduler_health_api_integrated(
        app
    )


def test_api_installation_failure_preserves_existing_service(
    app: FastAPI,
    service: SchedulerRuntimeLifespanHealthService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rollback must not remove a service installed beforehand."""

    install_scheduler_lifespan_health(
        app,
        service=service,
    )

    def fail_api_installation(
        application: FastAPI,
        *,
        replace: bool = False,
    ) -> None:
        raise RuntimeError("Simulated API installation failure")

    monkeypatch.setattr(
        integration,
        "install_scheduler_health_api",
        fail_api_installation,
    )

    with pytest.raises(
        integration.SchedulerHealthAPIIntegrationError,
        match="Unable to install",
    ):
        integration.install_scheduler_health_api_integration(
            app
        )

    assert (
        get_scheduler_lifespan_health_optional(app)
        is service
    )

    assert not integration.is_scheduler_health_api_integrated(
        app
    )


def test_install_rejects_different_preinstalled_service(
    app: FastAPI,
    service: SchedulerRuntimeLifespanHealthService,
) -> None:
    """A different preinstalled service must not be overwritten."""

    existing_service = (
        SchedulerRuntimeLifespanHealthService(app=app)
    )

    install_scheduler_lifespan_health(
        app,
        service=existing_service,
    )

    with pytest.raises(
        integration.SchedulerHealthAPIIntegrationError,
        match="different scheduler health service",
    ):
        integration.install_scheduler_health_api_integration(
            app,
            service=service,
        )

    assert (
        get_scheduler_lifespan_health_optional(app)
        is existing_service
    )


def test_get_integration_rejects_missing_integration(
    app: FastAPI,
) -> None:
    """Getting an absent integration must raise an error."""

    with pytest.raises(
        integration.SchedulerHealthAPIIntegrationError,
        match="not installed",
    ):
        integration.get_scheduler_health_api_integration(
            app
        )


def test_get_integration_returns_installed_service(
    app: FastAPI,
) -> None:
    """The getter must return the installed health service."""

    installed = (
        integration.install_scheduler_health_api_integration(
            app
        )
    )

    retrieved = integration.get_scheduler_health_api_integration(
        app
    )

    assert retrieved is installed


def test_get_integration_rejects_missing_service_state(
    app: FastAPI,
) -> None:
    """An integration marker without a service is inconsistent."""

    setattr(
        app.state,
        integration.INTEGRATION_STATE_KEY,
        True,
    )

    with pytest.raises(
        integration.SchedulerHealthAPIIntegrationError,
        match="health service is missing",
    ):
        integration.get_scheduler_health_api_integration(
            app
        )


def test_status_reports_uninstalled_state(
    app: FastAPI,
) -> None:
    """An untouched application must report an uninstalled state."""

    state = integration.get_scheduler_health_api_integration_status(
        app
    )

    assert state == {
        "integrated": False,
        "health_service_installed": False,
        "api_installed": False,
        "consistent": True,
    }


def test_status_reports_inconsistent_state_without_service(
    app: FastAPI,
) -> None:
    """An integration marker without a service is inconsistent."""

    setattr(
        app.state,
        integration.INTEGRATION_STATE_KEY,
        True,
    )

    state = integration.get_scheduler_health_api_integration_status(
        app
    )

    assert state["integrated"] is True
    assert state["health_service_installed"] is False
    assert state["consistent"] is False


def test_status_reports_inconsistent_api_registration(
    app: FastAPI,
    service: SchedulerRuntimeLifespanHealthService,
) -> None:
    """An integration without its API route is inconsistent."""

    install_scheduler_lifespan_health(
        app,
        service=service,
    )

    setattr(
        app.state,
        integration.INTEGRATION_STATE_KEY,
        True,
    )

    state = integration.get_scheduler_health_api_integration_status(
        app
    )

    assert state["integrated"] is True
    assert state["health_service_installed"] is True
    assert state["api_installed"] is False
    assert state["consistent"] is False


def test_remove_clears_integration_state(
    app: FastAPI,
) -> None:
    """Removal must clear the health service and integration marker."""

    integration.install_scheduler_health_api_integration(
        app
    )

    integration.remove_scheduler_health_api_integration(
        app
    )

    assert not integration.is_scheduler_health_api_integrated(
        app
    )

    assert (
        get_scheduler_lifespan_health_optional(app)
        is None
    )


def test_remove_preserves_registered_api_route(
    app: FastAPI,
) -> None:
    """Removing integration state must not pretend to unregister routes."""

    integration.install_scheduler_health_api_integration(
        app
    )

    integration.remove_scheduler_health_api_integration(
        app
    )

    assert "/health/scheduler" in {
        route.path
        for route in app.routes
    }

    state = integration.get_scheduler_health_api_integration_status(
        app
    )

    assert state["integrated"] is False
    assert state["health_service_installed"] is False
    assert state["api_installed"] is True
    assert state["consistent"] is False


def test_remove_is_safe_when_service_is_absent(
    app: FastAPI,
) -> None:
    """Removing an absent health service must be harmless."""

    integration.remove_scheduler_health_api_integration(
        app
    )

    assert not integration.is_scheduler_health_api_integrated(
        app
    )


def test_remove_rejects_invalid_application() -> None:
    """Removal must require a FastAPI application."""

    with pytest.raises(
        TypeError,
        match="FastAPI instance",
    ):
        integration.remove_scheduler_health_api_integration(
            Mock()
        )


def test_status_rejects_invalid_application() -> None:
    """Status inspection must require a FastAPI application."""

    with pytest.raises(
        TypeError,
        match="FastAPI instance",
    ):
        integration.get_scheduler_health_api_integration_status(
            Mock()
        )


def test_is_integrated_rejects_invalid_application() -> None:
    """Integration inspection must require a FastAPI application."""

    with pytest.raises(
        TypeError,
        match="FastAPI instance",
    ):
        integration.is_scheduler_health_api_integrated(
            Mock()
        )
