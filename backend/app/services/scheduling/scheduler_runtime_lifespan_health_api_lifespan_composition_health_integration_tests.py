
"""Tests for scheduler composition health application-state integration."""

from __future__ import annotations

import pytest
from fastapi import FastAPI

from app.services.scheduling.scheduler_runtime_lifespan_health_api_lifespan_composition_health import (
    CompositionHealthStatus,
    SchedulerHealthAPILifespanCompositionHealthService,
)
from app.services.scheduling.scheduler_runtime_lifespan_health_api_lifespan_composition_health_integration import (
    COMPOSITION_HEALTH_STATE_KEY,
    SchedulerHealthAPILifespanCompositionHealthIntegrationError,
    get_optional_scheduler_health_api_lifespan_composition_health,
    get_scheduler_health_api_lifespan_composition_health,
    get_scheduler_health_api_lifespan_composition_health_status,
    install_scheduler_health_api_lifespan_composition_health,
    is_scheduler_health_api_lifespan_composition_healthy,
    is_scheduler_health_api_lifespan_composition_health_installed,
    remove_scheduler_health_api_lifespan_composition_health,
)


@pytest.fixture
def app() -> FastAPI:
    return FastAPI()


@pytest.fixture
def service() -> SchedulerHealthAPILifespanCompositionHealthService:
    return SchedulerHealthAPILifespanCompositionHealthService()


def test_install_creates_and_binds_service(
    app: FastAPI,
) -> None:
    installed = (
        install_scheduler_health_api_lifespan_composition_health(app)
    )

    assert isinstance(
        installed,
        SchedulerHealthAPILifespanCompositionHealthService,
    )
    assert (
        get_scheduler_health_api_lifespan_composition_health(app)
        is installed
    )
    assert is_scheduler_health_api_lifespan_composition_health_installed(
        app
    )


def test_install_accepts_supplied_service(
    app: FastAPI,
    service: SchedulerHealthAPILifespanCompositionHealthService,
) -> None:
    installed = (
        install_scheduler_health_api_lifespan_composition_health(
            app,
            service,
        )
    )

    assert installed is service
    assert (
        get_scheduler_health_api_lifespan_composition_health(app)
        is service
    )


def test_install_is_idempotent_for_same_service(
    app: FastAPI,
    service: SchedulerHealthAPILifespanCompositionHealthService,
) -> None:
    first = install_scheduler_health_api_lifespan_composition_health(
        app,
        service,
    )
    second = install_scheduler_health_api_lifespan_composition_health(
        app,
        service,
    )

    assert first is second


def test_install_rejects_duplicate_service_without_replace(
    app: FastAPI,
    service: SchedulerHealthAPILifespanCompositionHealthService,
) -> None:
    install_scheduler_health_api_lifespan_composition_health(
        app,
        service,
    )

    replacement = SchedulerHealthAPILifespanCompositionHealthService()

    with pytest.raises(
        SchedulerHealthAPILifespanCompositionHealthIntegrationError
    ):
        install_scheduler_health_api_lifespan_composition_health(
            app,
            replacement,
        )


def test_install_replaces_existing_service_when_requested(
    app: FastAPI,
    service: SchedulerHealthAPILifespanCompositionHealthService,
) -> None:
    install_scheduler_health_api_lifespan_composition_health(
        app,
        service,
    )

    replacement = SchedulerHealthAPILifespanCompositionHealthService()

    installed = install_scheduler_health_api_lifespan_composition_health(
        app,
        replacement,
        replace=True,
    )

    assert installed is replacement
    assert (
        get_scheduler_health_api_lifespan_composition_health(app)
        is replacement
    )


def test_get_optional_returns_none_when_not_installed(
    app: FastAPI,
) -> None:
    assert (
        get_optional_scheduler_health_api_lifespan_composition_health(
            app
        )
        is None
    )


def test_get_required_raises_when_not_installed(
    app: FastAPI,
) -> None:
    with pytest.raises(
        SchedulerHealthAPILifespanCompositionHealthIntegrationError
    ):
        get_scheduler_health_api_lifespan_composition_health(app)


def test_installed_check_returns_false_when_absent(
    app: FastAPI,
) -> None:
    assert not (
        is_scheduler_health_api_lifespan_composition_health_installed(
            app
        )
    )


def test_status_reports_unavailable_when_not_installed(
    app: FastAPI,
) -> None:
    status = (
        get_scheduler_health_api_lifespan_composition_health_status(
            app
        )
    )

    assert status["installed"] is False
    assert status["healthy"] is False
    assert status["status"] == CompositionHealthStatus.UNAVAILABLE.value
    assert status["report"] is None


def test_status_inspects_installed_service(
    app: FastAPI,
    service: SchedulerHealthAPILifespanCompositionHealthService,
) -> None:
    install_scheduler_health_api_lifespan_composition_health(
        app,
        service,
    )

    status = (
        get_scheduler_health_api_lifespan_composition_health_status(
            app
        )
    )

    assert status["installed"] is True
    assert status["status"] in {
        status_value.value for status_value in CompositionHealthStatus
    }
    assert isinstance(status["healthy"], bool)


def test_health_check_returns_false_when_service_is_absent(
    app: FastAPI,
) -> None:
    assert not (
        is_scheduler_health_api_lifespan_composition_healthy(app)
    )


def test_health_check_returns_false_when_inspection_fails(
    app: FastAPI,
    service: SchedulerHealthAPILifespanCompositionHealthService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failing_inspect():
        raise RuntimeError("Inspection failed")

    monkeypatch.setattr(service, "inspect", failing_inspect)

    install_scheduler_health_api_lifespan_composition_health(
        app,
        service,
    )

    assert not (
        is_scheduler_health_api_lifespan_composition_healthy(app)
    )

    status = (
        get_scheduler_health_api_lifespan_composition_health_status(
            app
        )
    )

    assert status["installed"] is True
    assert status["healthy"] is False
    assert status["status"] == CompositionHealthStatus.FAILED.value
    assert status["error"] == "Inspection failed"


def test_invalid_service_in_application_state_is_rejected(
    app: FastAPI,
) -> None:
    setattr(app.state, COMPOSITION_HEALTH_STATE_KEY, object())

    with pytest.raises(
        SchedulerHealthAPILifespanCompositionHealthIntegrationError
    ):
        get_scheduler_health_api_lifespan_composition_health(app)


def test_remove_returns_installed_service(
    app: FastAPI,
    service: SchedulerHealthAPILifespanCompositionHealthService,
) -> None:
    install_scheduler_health_api_lifespan_composition_health(
        app,
        service,
    )

    removed = (
        remove_scheduler_health_api_lifespan_composition_health(app)
    )

    assert removed is service
    assert not (
        is_scheduler_health_api_lifespan_composition_health_installed(
            app
        )
    )


def test_remove_returns_none_when_absent(
    app: FastAPI,
) -> None:
    removed = (
        remove_scheduler_health_api_lifespan_composition_health(app)
    )

    assert removed is None


def test_remove_can_require_existing_service(
    app: FastAPI,
) -> None:
    with pytest.raises(
        SchedulerHealthAPILifespanCompositionHealthIntegrationError
    ):
        remove_scheduler_health_api_lifespan_composition_health(
            app,
            required=True,
        )


def test_remove_does_not_remove_application_lifespan(
    app: FastAPI,
    service: SchedulerHealthAPILifespanCompositionHealthService,
) -> None:
    original_lifespan = app.router.lifespan_context

    install_scheduler_health_api_lifespan_composition_health(
        app,
        service,
    )

    remove_scheduler_health_api_lifespan_composition_health(app)

    assert app.router.lifespan_context is original_lifespan


@pytest.mark.parametrize(
    "invalid_app",
    [
        None,
        object(),
        "not-an-application",
    ],
)
def test_install_rejects_invalid_application(
    invalid_app: object,
) -> None:
    with pytest.raises(TypeError):
        install_scheduler_health_api_lifespan_composition_health(
            invalid_app  # type: ignore[arg-type]
        )


def test_install_rejects_invalid_service(
    app: FastAPI,
) -> None:
    with pytest.raises(TypeError):
        install_scheduler_health_api_lifespan_composition_health(
            app,
            object(),  # type: ignore[arg-type]
        )
