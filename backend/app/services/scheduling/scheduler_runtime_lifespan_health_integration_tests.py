
"""Tests for scheduler runtime lifespan health integration."""

from __future__ import annotations

from unittest.mock import Mock

import pytest
from fastapi import FastAPI

from app.services.scheduling.scheduler_runtime_lifespan_health import (
    SchedulerLifespanHealthStatus,
    SchedulerRuntimeLifespanHealthService,
)
from app.services.scheduling.scheduler_runtime_lifespan_health_integration import (
    SCHEDULER_LIFESPAN_HEALTH_STATE_KEY,
    SchedulerLifespanHealthIntegrationError,
    get_scheduler_lifespan_health,
    get_scheduler_lifespan_health_optional,
    get_scheduler_lifespan_health_status,
    install_scheduler_lifespan_health,
    is_scheduler_lifespan_health_installed,
    is_scheduler_lifespan_healthy,
    remove_scheduler_lifespan_health,
)


@pytest.fixture
def app() -> FastAPI:
    return FastAPI()


@pytest.fixture
def service(app: FastAPI) -> SchedulerRuntimeLifespanHealthService:
    return SchedulerRuntimeLifespanHealthService(app=app)


@pytest.fixture
def installed_app(
    app: FastAPI,
    service: SchedulerRuntimeLifespanHealthService,
) -> FastAPI:
    install_scheduler_lifespan_health(app, service)
    return app


def test_install_creates_default_service(app: FastAPI) -> None:
    service = install_scheduler_lifespan_health(app)

    assert isinstance(
        service,
        SchedulerRuntimeLifespanHealthService,
    )
    assert service is get_scheduler_lifespan_health(app)


def test_install_stores_service_in_application_state(
    installed_app: FastAPI,
    service: SchedulerRuntimeLifespanHealthService,
) -> None:
    assert (
        getattr(
            installed_app.state,
            SCHEDULER_LIFESPAN_HEALTH_STATE_KEY,
        )
        is service
    )


def test_install_returns_supplied_service(
    app: FastAPI,
    service: SchedulerRuntimeLifespanHealthService,
) -> None:
    result = install_scheduler_lifespan_health(
        app,
        service,
    )

    assert result is service


def test_install_rejects_invalid_application() -> None:
    with pytest.raises(TypeError, match="FastAPI"):
        install_scheduler_lifespan_health(
            object(),  # type: ignore[arg-type]
        )


def test_install_rejects_invalid_replace_option(
    app: FastAPI,
) -> None:
    with pytest.raises(TypeError, match="boolean"):
        install_scheduler_lifespan_health(
            app,
            replace=1,  # type: ignore[arg-type]
        )


def test_install_rejects_invalid_service(
    app: FastAPI,
) -> None:
    with pytest.raises(TypeError, match="SchedulerRuntimeLifespanHealthService"):
        install_scheduler_lifespan_health(
            app,
            service=object(),  # type: ignore[arg-type]
        )


def test_duplicate_installation_is_rejected(
    installed_app: FastAPI,
) -> None:
    with pytest.raises(
        SchedulerLifespanHealthIntegrationError,
        match="already installed",
    ):
        install_scheduler_lifespan_health(installed_app)


def test_replacement_is_allowed(
    installed_app: FastAPI,
    service: SchedulerRuntimeLifespanHealthService,
) -> None:
    replacement = SchedulerRuntimeLifespanHealthService(
        app=installed_app,
    )

    result = install_scheduler_lifespan_health(
        installed_app,
        replacement,
        replace=True,
    )

    assert result is replacement
    assert result is not service
    assert get_scheduler_lifespan_health(installed_app) is replacement


def test_get_service(
    installed_app: FastAPI,
    service: SchedulerRuntimeLifespanHealthService,
) -> None:
    assert get_scheduler_lifespan_health(installed_app) is service


def test_get_service_rejects_missing_registration(
    app: FastAPI,
) -> None:
    with pytest.raises(
        SchedulerLifespanHealthIntegrationError,
        match="not installed",
    ):
        get_scheduler_lifespan_health(app)


def test_get_optional_service_when_missing(
    app: FastAPI,
) -> None:
    assert get_scheduler_lifespan_health_optional(app) is None


def test_get_optional_service_when_installed(
    installed_app: FastAPI,
    service: SchedulerRuntimeLifespanHealthService,
) -> None:
    assert (
        get_scheduler_lifespan_health_optional(installed_app)
        is service
    )


def test_is_installed_when_missing(app: FastAPI) -> None:
    assert is_scheduler_lifespan_health_installed(app) is False


def test_is_installed_when_present(installed_app: FastAPI) -> None:
    assert is_scheduler_lifespan_health_installed(installed_app) is True


def test_remove_service(
    installed_app: FastAPI,
    service: SchedulerRuntimeLifespanHealthService,
) -> None:
    removed = remove_scheduler_lifespan_health(installed_app)

    assert removed is service
    assert is_scheduler_lifespan_health_installed(installed_app) is False


def test_remove_rejects_missing_registration(
    app: FastAPI,
) -> None:
    with pytest.raises(
        SchedulerLifespanHealthIntegrationError,
        match="not installed",
    ):
        remove_scheduler_lifespan_health(app)


def test_remove_rejects_invalid_application() -> None:
    with pytest.raises(TypeError, match="FastAPI"):
        remove_scheduler_lifespan_health(
            object(),  # type: ignore[arg-type]
        )


def test_status_returns_service_report(
    installed_app: FastAPI,
    service: SchedulerRuntimeLifespanHealthService,
) -> None:
    expected = {
        "status": SchedulerLifespanHealthStatus.UNAVAILABLE.value,
        "runtime_installed": False,
    }

    service.get_status = Mock(return_value=expected)

    result = get_scheduler_lifespan_health_status(installed_app)

    assert result == expected
    service.get_status.assert_called_once_with(installed_app)


def test_status_wraps_service_failure(
    installed_app: FastAPI,
    service: SchedulerRuntimeLifespanHealthService,
) -> None:
    service.get_status = Mock(
        side_effect=RuntimeError("Inspection failed")
    )

    with pytest.raises(
        SchedulerLifespanHealthIntegrationError,
        match="Failed to retrieve",
    ):
        get_scheduler_lifespan_health_status(installed_app)


def test_status_rejects_missing_service(
    app: FastAPI,
) -> None:
    with pytest.raises(
        SchedulerLifespanHealthIntegrationError,
        match="not installed",
    ):
        get_scheduler_lifespan_health_status(app)


def test_is_healthy_returns_service_result(
    installed_app: FastAPI,
    service: SchedulerRuntimeLifespanHealthService,
) -> None:
    service.is_healthy = Mock(return_value=True)

    assert is_scheduler_lifespan_healthy(installed_app) is True
    service.is_healthy.assert_called_once_with(installed_app)


def test_is_healthy_returns_false(
    installed_app: FastAPI,
    service: SchedulerRuntimeLifespanHealthService,
) -> None:
    service.is_healthy = Mock(return_value=False)

    assert is_scheduler_lifespan_healthy(installed_app) is False


def test_is_healthy_wraps_service_failure(
    installed_app: FastAPI,
    service: SchedulerRuntimeLifespanHealthService,
) -> None:
    service.is_healthy = Mock(
        side_effect=RuntimeError("Health check failed")
    )

    with pytest.raises(
        SchedulerLifespanHealthIntegrationError,
        match="Failed to evaluate",
    ):
        is_scheduler_lifespan_healthy(installed_app)


def test_is_healthy_rejects_missing_service(
    app: FastAPI,
) -> None:
    with pytest.raises(
        SchedulerLifespanHealthIntegrationError,
        match="not installed",
    ):
        is_scheduler_lifespan_healthy(app)


def test_invalid_state_service_is_rejected(
    app: FastAPI,
) -> None:
    setattr(
        app.state,
        SCHEDULER_LIFESPAN_HEALTH_STATE_KEY,
        object(),
    )

    with pytest.raises(
        SchedulerLifespanHealthIntegrationError,
        match="invalid",
    ):
        get_scheduler_lifespan_health(app)


def test_invalid_state_service_is_rejected_by_optional_getter(
    app: FastAPI,
) -> None:
    setattr(
        app.state,
        SCHEDULER_LIFESPAN_HEALTH_STATE_KEY,
        object(),
    )

    with pytest.raises(
        SchedulerLifespanHealthIntegrationError,
        match="invalid",
    ):
        get_scheduler_lifespan_health_optional(app)


def test_status_rejects_invalid_application() -> None:
    with pytest.raises(TypeError, match="FastAPI"):
        get_scheduler_lifespan_health_status(
            object(),  # type: ignore[arg-type]
        )


def test_health_check_rejects_invalid_application() -> None:
    with pytest.raises(TypeError, match="FastAPI"):
        is_scheduler_lifespan_healthy(
            object(),  # type: ignore[arg-type]
        )
