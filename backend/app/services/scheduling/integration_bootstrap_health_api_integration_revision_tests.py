
"""Regression tests for the revised bootstrap health API integration."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from starlette.datastructures import State

from app.services.scheduling.integration_bootstrap_health import (
    SchedulingBootstrapHealthService,
)
from app.services.scheduling.integration_bootstrap_health_api import (
    BOOTSTRAP_HEALTH_API_PATH,
    BOOTSTRAP_HEALTH_API_STATE_KEY,
)
from app.services.scheduling.integration_bootstrap_health_api_integration import (
    BOOTSTRAP_HEALTH_API_INTEGRATION_STATE_KEY,
    BootstrapHealthAPIIntegrationError,
    get_bootstrap_health_api_integration_optional,
    get_bootstrap_health_api_integration_status,
    install_bootstrap_health_api_integration,
    remove_bootstrap_health_api_integration,
)
from app.services.scheduling.integration_bootstrap_health_integration import (
    BOOTSTRAP_HEALTH_STATE_KEY,
    get_bootstrap_health,
    install_bootstrap_health,
)


class SelectiveFailureState:
    """Delegate application state while injecting a selected failure."""

    def __init__(
        self,
        initial_state: State,
        *,
        fail_set_key: str | None = None,
        fail_delete_key: str | None = None,
    ) -> None:
        object.__setattr__(self, "_state", initial_state)
        object.__setattr__(self, "_fail_set_key", fail_set_key)
        object.__setattr__(self, "_fail_delete_key", fail_delete_key)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._state, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name == self._fail_set_key:
            raise RuntimeError(
                f"Injected state assignment failure: {name}"
            )

        setattr(self._state, name, value)

    def __delattr__(self, name: str) -> None:
        if name == self._fail_delete_key:
            raise RuntimeError(
                f"Injected state deletion failure: {name}"
            )

        delattr(self._state, name)


@pytest.fixture
def app() -> FastAPI:
    return FastAPI()


@pytest.fixture
def original_service() -> SchedulingBootstrapHealthService:
    return SchedulingBootstrapHealthService()


def test_api_installation_failure_preserves_existing_service(
    app: FastAPI,
    original_service: SchedulingBootstrapHealthService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.scheduling import (
        integration_bootstrap_health_api_integration as integration_module,
    )

    install_bootstrap_health(app, original_service)

    def fail_api_installation(
        _app: FastAPI,
    ) -> None:
        raise RuntimeError("injected API installation failure")

    monkeypatch.setattr(
        integration_module,
        "install_bootstrap_health_api",
        fail_api_installation,
    )

    with pytest.raises(BootstrapHealthAPIIntegrationError):
        install_bootstrap_health_api_integration(
            app,
            replace=True,
        )

    assert get_bootstrap_health(app) is original_service
    assert (
        get_bootstrap_health_api_integration_optional(app)
        is None
    )


def test_api_installation_failure_does_not_register_combined_metadata(
    app: FastAPI,
    original_service: SchedulingBootstrapHealthService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.scheduling import (
        integration_bootstrap_health_api_integration as integration_module,
    )

    install_bootstrap_health(app, original_service)

    def fail_api_installation(
        _app: FastAPI,
    ) -> None:
        raise RuntimeError("injected failure")

    monkeypatch.setattr(
        integration_module,
        "install_bootstrap_health_api",
        fail_api_installation,
    )

    with pytest.raises(BootstrapHealthAPIIntegrationError):
        install_bootstrap_health_api_integration(
            app,
            replace=True,
        )

    assert not hasattr(
        app.state,
        BOOTSTRAP_HEALTH_API_INTEGRATION_STATE_KEY,
    )


def test_successful_replacement_preserves_api_registration(
    app: FastAPI,
    original_service: SchedulingBootstrapHealthService,
) -> None:
    install_bootstrap_health(app, original_service)

    integration = install_bootstrap_health_api_integration(
        app,
        replace=True,
    )

    assert integration.service is not original_service
    assert get_bootstrap_health(app) is integration.service

    paths = {
        route.path
        for route in app.routes
        if hasattr(route, "path")
    }

    assert BOOTSTRAP_HEALTH_API_PATH in paths


def test_successful_replacement_registers_matching_service(
    app: FastAPI,
    original_service: SchedulingBootstrapHealthService,
) -> None:
    install_bootstrap_health(app, original_service)

    integration = install_bootstrap_health_api_integration(
        app,
        replace=True,
    )

    status = get_bootstrap_health_api_integration_status(app)

    assert status.installed is True
    assert status.service_matches_registration is True
    assert get_bootstrap_health(app) is integration.service


def test_state_registration_failure_restores_original_service(
    app: FastAPI,
    original_service: SchedulingBootstrapHealthService,
) -> None:
    install_bootstrap_health(app, original_service)

    original_state = app.state

    app.state = SelectiveFailureState(
        original_state,
        fail_set_key=BOOTSTRAP_HEALTH_API_INTEGRATION_STATE_KEY,
    )

    with pytest.raises(BootstrapHealthAPIIntegrationError):
        install_bootstrap_health_api_integration(
            app,
            replace=True,
        )

    assert get_bootstrap_health(app) is original_service


def test_state_registration_failure_reports_partial_api_installation(
    app: FastAPI,
    original_service: SchedulingBootstrapHealthService,
) -> None:
    install_bootstrap_health(app, original_service)

    original_state = app.state

    app.state = SelectiveFailureState(
        original_state,
        fail_set_key=BOOTSTRAP_HEALTH_API_INTEGRATION_STATE_KEY,
    )

    with pytest.raises(
        BootstrapHealthAPIIntegrationError,
        match="router remains registered",
    ):
        install_bootstrap_health_api_integration(
            app,
            replace=True,
        )

    assert hasattr(
        app.state,
        BOOTSTRAP_HEALTH_API_STATE_KEY,
    )

    paths = {
        route.path
        for route in app.routes
        if hasattr(route, "path")
    }

    assert BOOTSTRAP_HEALTH_API_PATH in paths


def test_partial_installation_is_not_reported_as_complete(
    app: FastAPI,
    original_service: SchedulingBootstrapHealthService,
) -> None:
    install_bootstrap_health(app, original_service)

    original_state = app.state

    app.state = SelectiveFailureState(
        original_state,
        fail_set_key=BOOTSTRAP_HEALTH_API_INTEGRATION_STATE_KEY,
    )

    with pytest.raises(BootstrapHealthAPIIntegrationError):
        install_bootstrap_health_api_integration(
            app,
            replace=True,
        )

    status = get_bootstrap_health_api_integration_status(app)

    assert status.installed is False
    assert status.service_installed is True
    assert status.api_installed is True
    assert status.service_matches_registration is False


def test_removal_metadata_failure_restores_service(
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    integration = install_bootstrap_health_api_integration(app)
    original_service = integration.service

    original_state = app.state

    app.state = SelectiveFailureState(
        original_state,
        fail_delete_key=BOOTSTRAP_HEALTH_API_INTEGRATION_STATE_KEY,
    )

    with pytest.raises(BootstrapHealthAPIIntegrationError):
        remove_bootstrap_health_api_integration(app)

    assert get_bootstrap_health(app) is original_service
    assert (
        get_bootstrap_health_api_integration_optional(app)
        is integration
    )


def test_removal_metadata_failure_keeps_registration(
    app: FastAPI,
) -> None:
    integration = install_bootstrap_health_api_integration(app)

    app.state = SelectiveFailureState(
        app.state,
        fail_delete_key=BOOTSTRAP_HEALTH_API_INTEGRATION_STATE_KEY,
    )

    with pytest.raises(BootstrapHealthAPIIntegrationError):
        remove_bootstrap_health_api_integration(app)

    assert (
        get_bootstrap_health_api_integration_optional(app)
        is integration
    )


def test_removal_without_service_removal_preserves_service(
    app: FastAPI,
) -> None:
    integration = install_bootstrap_health_api_integration(app)

    remove_bootstrap_health_api_integration(
        app,
        remove_service=False,
    )

    assert get_bootstrap_health(app) is integration.service
    assert (
        get_bootstrap_health_api_integration_optional(app)
        is None
    )


def test_removed_integration_does_not_remove_fastapi_route(
    app: FastAPI,
) -> None:
    install_bootstrap_health_api_integration(app)

    remove_bootstrap_health_api_integration(app)

    paths = {
        route.path
        for route in app.routes
        if hasattr(route, "path")
    }

    assert BOOTSTRAP_HEALTH_API_PATH in paths


def test_existing_combined_integration_cannot_be_replaced(
    app: FastAPI,
) -> None:
    integration = install_bootstrap_health_api_integration(app)

    with pytest.raises(BootstrapHealthAPIIntegrationError):
        install_bootstrap_health_api_integration(
            app,
            SchedulingBootstrapHealthService(),
            replace=True,
        )

    assert get_bootstrap_health(app) is integration.service
    assert (
        get_bootstrap_health_api_integration_optional(app)
        is integration
    )


def test_api_marker_remains_after_failed_state_registration(
    app: FastAPI,
    original_service: SchedulingBootstrapHealthService,
) -> None:
    install_bootstrap_health(app, original_service)

    original_state = app.state

    app.state = SelectiveFailureState(
        original_state,
        fail_set_key=BOOTSTRAP_HEALTH_API_INTEGRATION_STATE_KEY,
    )

    with pytest.raises(BootstrapHealthAPIIntegrationError):
        install_bootstrap_health_api_integration(
            app,
            replace=True,
        )

    assert hasattr(
        app.state,
        BOOTSTRAP_HEALTH_API_STATE_KEY,
    )

    assert get_bootstrap_health(app) is original_service
