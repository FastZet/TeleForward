
"""Tests for scheduler health API lifespan integration management."""

from __future__ import annotations

from unittest.mock import Mock

import pytest
from fastapi import FastAPI

from app.services.scheduling import (
    scheduler_runtime_lifespan_health_api_lifespan_integration as integration,
)
from app.services.scheduling.scheduler_runtime_lifespan_health import (
    SchedulerRuntimeLifespanHealthService,
)
from app.services.scheduling.scheduler_runtime_lifespan_health_api_lifespan import (
    is_scheduler_health_api_lifespan_registered,
)


@pytest.fixture
def app() -> FastAPI:
    """Create a FastAPI application."""

    return FastAPI()


@pytest.fixture
def service(
    app: FastAPI,
) -> SchedulerRuntimeLifespanHealthService:
    """Create a health service bound to the application."""

    return SchedulerRuntimeLifespanHealthService(app=app)


def test_install_registers_lifespan(
    app: FastAPI,
) -> None:
    """Installation must register a callable lifespan."""

    lifespan = (
        integration.install_scheduler_health_api_lifespan_integration(
            app
        )
    )

    assert callable(lifespan)

    assert integration.is_scheduler_health_api_lifespan_integrated(
        app
    )

    assert is_scheduler_health_api_lifespan_registered(app)


def test_install_registers_supplied_service_metadata(
    app: FastAPI,
    service: SchedulerRuntimeLifespanHealthService,
) -> None:
    """The integration must record whether a service was supplied."""

    integration.install_scheduler_health_api_lifespan_integration(
        app,
        service=service,
    )

    state = (
        integration.get_scheduler_health_api_lifespan_integration_status(
            app
        )
    )

    assert state["service_supplied"] is True
    assert state["consistent"] is True


def test_install_without_service_records_default_configuration(
    app: FastAPI,
) -> None:
    """Default service construction must be reflected in metadata."""

    integration.install_scheduler_health_api_lifespan_integration(
        app
    )

    state = (
        integration.get_scheduler_health_api_lifespan_integration_status(
            app
        )
    )

    assert state["service_supplied"] is False


def test_install_preserves_existing_lifespan(
    app: FastAPI,
) -> None:
    """The supplied lifespan factory must be retained."""

    async def existing_lifespan(application: FastAPI):
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def context():
            yield

        return context()

    lifespan = (
        integration.install_scheduler_health_api_lifespan_integration(
            app,
            existing_lifespan=existing_lifespan,
        )
    )

    assert callable(lifespan)


def test_get_returns_registered_lifespan(
    app: FastAPI,
) -> None:
    """The getter must return the exact registered factory."""

    installed = (
        integration.install_scheduler_health_api_lifespan_integration(
            app
        )
    )

    retrieved = (
        integration.get_scheduler_health_api_lifespan_integration(
            app
        )
    )

    assert retrieved is installed


def test_get_rejects_unregistered_lifespan(
    app: FastAPI,
) -> None:
    """Retrieval must fail when no integration exists."""

    with pytest.raises(
        integration.SchedulerHealthAPILifespanIntegrationError,
        match="not installed",
    ):
        integration.get_scheduler_health_api_lifespan_integration(
            app
        )


def test_duplicate_installation_is_rejected(
    app: FastAPI,
) -> None:
    """Repeated installation must be rejected."""

    integration.install_scheduler_health_api_lifespan_integration(
        app
    )

    with pytest.raises(
        integration.SchedulerHealthAPILifespanIntegrationError,
        match="already installed",
    ):
        integration.install_scheduler_health_api_lifespan_integration(
            app
        )


def test_replace_is_rejected(
    app: FastAPI,
) -> None:
    """Replacing a registered lifespan must be rejected."""

    integration.install_scheduler_health_api_lifespan_integration(
        app
    )

    with pytest.raises(
        integration.SchedulerHealthAPILifespanIntegrationError,
        match="Replacing a registered lifespan",
    ):
        integration.install_scheduler_health_api_lifespan_integration(
            app,
            replace=True,
        )


def test_install_rejects_invalid_application() -> None:
    """Installation must require a FastAPI instance."""

    with pytest.raises(
        TypeError,
        match="FastAPI instance",
    ):
        integration.install_scheduler_health_api_lifespan_integration(
            Mock()
        )


def test_install_rejects_invalid_replace_argument(
    app: FastAPI,
) -> None:
    """The replace argument must be boolean."""

    with pytest.raises(
        TypeError,
        match="replace must be a boolean",
    ):
        integration.install_scheduler_health_api_lifespan_integration(
            app,
            replace="yes",  # type: ignore[arg-type]
        )


def test_install_rejects_invalid_service(
    app: FastAPI,
) -> None:
    """Installation must reject an invalid health service."""

    with pytest.raises(
        TypeError,
        match="SchedulerRuntimeLifespanHealthService",
    ):
        integration.install_scheduler_health_api_lifespan_integration(
            app,
            service=Mock(),  # type: ignore[arg-type]
        )


def test_install_rejects_existing_unmanaged_lifespan(
    app: FastAPI,
) -> None:
    """An independently registered lifespan must not be overwritten."""

    from app.services.scheduling.scheduler_runtime_lifespan_health_api_lifespan import (
        install_scheduler_health_api_lifespan,
    )

    install_scheduler_health_api_lifespan(app)

    with pytest.raises(
        integration.SchedulerHealthAPILifespanIntegrationError,
        match="already registered outside this integration",
    ):
        integration.install_scheduler_health_api_lifespan_integration(
            app
        )


def test_status_reports_uninstalled_state(
    app: FastAPI,
) -> None:
    """An untouched application must report no integration."""

    state = (
        integration.get_scheduler_health_api_lifespan_integration_status(
            app
        )
    )

    assert state == {
        "integrated": False,
        "lifespan_registered": False,
        "lifespan_valid": False,
        "consistent": True,
        "service_supplied": False,
    }


def test_status_reports_installed_state(
    app: FastAPI,
) -> None:
    """A correctly installed integration must be consistent."""

    integration.install_scheduler_health_api_lifespan_integration(
        app
    )

    state = (
        integration.get_scheduler_health_api_lifespan_integration_status(
            app
        )
    )

    assert state["integrated"] is True
    assert state["lifespan_registered"] is True
    assert state["lifespan_valid"] is True
    assert state["consistent"] is True


def test_status_detects_missing_underlying_registration(
    app: FastAPI,
) -> None:
    """Missing underlying registration must be reported."""

    integration.install_scheduler_health_api_lifespan_integration(
        app
    )

    setattr(
        app.state,
        "scheduler_health_api_lifespan",
        None,
    )

    state = (
        integration.get_scheduler_health_api_lifespan_integration_status(
            app
        )
    )

    assert state["integrated"] is True
    assert state["lifespan_registered"] is False
    assert state["lifespan_valid"] is True
    assert state["consistent"] is False


def test_status_detects_invalid_integration_state(
    app: FastAPI,
) -> None:
    """Malformed integration metadata must raise an error."""

    setattr(
        app.state,
        integration.INTEGRATION_STATE_KEY,
        "invalid",
    )

    with pytest.raises(
        integration.SchedulerHealthAPILifespanIntegrationError,
        match="state is invalid",
    ):
        integration.get_scheduler_health_api_lifespan_integration_status(
            app
        )


def test_status_detects_non_callable_lifespan(
    app: FastAPI,
) -> None:
    """A non-callable registered lifespan must be reported as invalid."""

    integration.install_scheduler_health_api_lifespan_integration(
        app
    )

    state = getattr(
        app.state,
        integration.INTEGRATION_STATE_KEY,
    )

    state["lifespan"] = "invalid"

    status = (
        integration.get_scheduler_health_api_lifespan_integration_status(
            app
        )
    )

    assert status["integrated"] is True
    assert status["lifespan_valid"] is False
    assert status["consistent"] is False


def test_remove_clears_integration_metadata(
    app: FastAPI,
) -> None:
    """Removal must clear both registration metadata entries."""

    integration.install_scheduler_health_api_lifespan_integration(
        app
    )

    integration.remove_scheduler_health_api_lifespan_integration(
        app
    )

    assert getattr(
        app.state,
        integration.INTEGRATION_STATE_KEY,
        None,
    ) is None

    assert getattr(
        app.state,
        "scheduler_health_api_lifespan",
        None,
    ) is None

    assert not integration.is_scheduler_health_api_lifespan_integrated(
        app
    )


def test_remove_is_safe_when_not_installed(
    app: FastAPI,
) -> None:
    """Removing an absent integration must be harmless."""

    integration.remove_scheduler_health_api_lifespan_integration(
        app
    )

    assert not integration.is_scheduler_health_api_lifespan_integrated(
        app
    )


def test_remove_rejects_invalid_application() -> None:
    """Removal must require a FastAPI instance."""

    with pytest.raises(
        TypeError,
        match="FastAPI instance",
    ):
        integration.remove_scheduler_health_api_lifespan_integration(
            Mock()
        )


def test_get_rejects_invalid_application() -> None:
    """Retrieval must require a FastAPI instance."""

    with pytest.raises(
        TypeError,
        match="FastAPI instance",
    ):
        integration.get_scheduler_health_api_lifespan_integration(
            Mock()
        )


def test_status_rejects_invalid_application() -> None:
    """Status inspection must require a FastAPI instance."""

    with pytest.raises(
        TypeError,
        match="FastAPI instance",
    ):
        integration.get_scheduler_health_api_lifespan_integration_status(
            Mock()
        )


def test_is_integrated_rejects_invalid_application() -> None:
    """Integration inspection must require a FastAPI instance."""

    with pytest.raises(
        TypeError,
        match="FastAPI instance",
    ):
        integration.is_scheduler_health_api_lifespan_integrated(
            Mock()
        )
