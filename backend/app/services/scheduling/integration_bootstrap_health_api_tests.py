
"""Tests for the scheduling bootstrap health API."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services.scheduling.integration_bootstrap_health import (
    BootstrapHealthStatus,
)
from app.services.scheduling.integration_bootstrap_health_api import (
    BOOTSTRAP_HEALTH_API_PATH,
    BOOTSTRAP_HEALTH_API_STATE_KEY,
    BootstrapHealthAPIResponse,
    _http_status_for_health,
    install_bootstrap_health_api,
    is_bootstrap_health_api_installed,
)
from app.services.scheduling.integration_bootstrap_health_integration import (
    BootstrapHealthIntegrationError,
)


def make_response(
    health_status: BootstrapHealthStatus,
) -> BootstrapHealthAPIResponse:
    """Build a representative public API response."""
    return BootstrapHealthAPIResponse(
        status=health_status,
        state="ready",
        context_available=True,
        components={
            "scheduler_manager": True,
            "task_registry": True,
            "job_store": True,
            "scheduler": True,
        },
        validation_passed=True,
        cleanup_errors=[],
        checked_at=datetime.now(UTC).isoformat(),
        details={},
    )


@pytest.fixture
def app() -> FastAPI:
    application = FastAPI()
    install_bootstrap_health_api(application)
    return application


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def test_health_endpoint_is_registered(
    app: FastAPI,
) -> None:
    paths = {
        route.path
        for route in app.routes
        if hasattr(route, "path")
    }

    assert BOOTSTRAP_HEALTH_API_PATH in paths


def test_install_returns_router() -> None:
    from fastapi import APIRouter

    app = FastAPI()

    router = install_bootstrap_health_api(app)

    assert isinstance(router, APIRouter)


def test_install_records_router_in_application_state(
    app: FastAPI,
) -> None:
    router = getattr(
        app.state,
        BOOTSTRAP_HEALTH_API_STATE_KEY,
    )

    from fastapi import APIRouter

    assert isinstance(router, APIRouter)


def test_install_rejects_invalid_app() -> None:
    with pytest.raises(TypeError):
        install_bootstrap_health_api(
            object(),  # type: ignore[arg-type]
        )


def test_duplicate_installation_is_rejected(
    app: FastAPI,
) -> None:
    with pytest.raises(RuntimeError):
        install_bootstrap_health_api(app)


def test_replace_does_not_claim_to_replace_registered_routes(
    app: FastAPI,
) -> None:
    with pytest.raises(RuntimeError):
        install_bootstrap_health_api(
            app,
            replace=True,
        )


def test_installation_status_is_true(
    app: FastAPI,
) -> None:
    assert is_bootstrap_health_api_installed(app) is True


def test_installation_status_is_false_when_absent() -> None:
    app = FastAPI()

    assert is_bootstrap_health_api_installed(app) is False


def test_installation_status_rejects_invalid_app() -> None:
    with pytest.raises(TypeError):
        is_bootstrap_health_api_installed(
            object(),  # type: ignore[arg-type]
        )


def test_installation_status_rejects_invalid_state(
    app: FastAPI,
) -> None:
    setattr(
        app.state,
        BOOTSTRAP_HEALTH_API_STATE_KEY,
        object(),
    )

    with pytest.raises(TypeError):
        is_bootstrap_health_api_installed(app)


@pytest.mark.parametrize(
    ("health_status", "expected_http_status"),
    [
        (BootstrapHealthStatus.HEALTHY, 200),
        (BootstrapHealthStatus.DEGRADED, 200),
        (BootstrapHealthStatus.UNAVAILABLE, 503),
        (BootstrapHealthStatus.FAILED, 503),
    ],
)
def test_http_status_mapping(
    health_status: BootstrapHealthStatus,
    expected_http_status: int,
) -> None:
    assert (
        _http_status_for_health(health_status)
        == expected_http_status
    )


@pytest.mark.parametrize(
    ("health_status", "expected_http_status"),
    [
        (BootstrapHealthStatus.HEALTHY, 200),
        (BootstrapHealthStatus.DEGRADED, 200),
        (BootstrapHealthStatus.UNAVAILABLE, 503),
        (BootstrapHealthStatus.FAILED, 503),
    ],
)
def test_endpoint_maps_health_status_to_http_status(
    app: FastAPI,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    health_status: BootstrapHealthStatus,
    expected_http_status: int,
) -> None:
    from app.services.scheduling import (
        integration_bootstrap_health_api as api_module,
    )

    monkeypatch.setattr(
        api_module,
        "get_bootstrap_health_report",
        lambda _app: Mock(),
    )
    monkeypatch.setattr(
        api_module,
        "serialize_bootstrap_health_report",
        lambda _report: make_response(health_status),
    )

    response = client.get(BOOTSTRAP_HEALTH_API_PATH)

    assert response.status_code == expected_http_status

    if expected_http_status == 200:
        assert response.json()["status"] == health_status.value
    else:
        assert response.json()["detail"]["status"] == health_status.value


def test_endpoint_returns_503_when_integration_is_missing(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.scheduling import (
        integration_bootstrap_health_api as api_module,
    )

    def raise_missing_integration(
        _app: FastAPI,
    ) -> None:
        raise BootstrapHealthIntegrationError(
            "Bootstrap health service is not installed"
        )

    monkeypatch.setattr(
        api_module,
        "get_bootstrap_health_report",
        raise_missing_integration,
    )

    response = client.get(BOOTSTRAP_HEALTH_API_PATH)

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "Scheduling bootstrap health is unavailable"
    )


def test_endpoint_returns_500_for_unexpected_errors(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.scheduling import (
        integration_bootstrap_health_api as api_module,
    )

    def raise_unexpected_error(
        _app: FastAPI,
    ) -> None:
        raise RuntimeError("internal failure")

    monkeypatch.setattr(
        api_module,
        "get_bootstrap_health_report",
        raise_unexpected_error,
    )

    response = client.get(BOOTSTRAP_HEALTH_API_PATH)

    assert response.status_code == 500
    assert response.json()["detail"] == (
        "Unable to retrieve scheduling bootstrap health"
    )


def test_endpoint_returns_500_for_serialization_errors(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.scheduling import (
        integration_bootstrap_health_api as api_module,
    )

    monkeypatch.setattr(
        api_module,
        "get_bootstrap_health_report",
        lambda _app: Mock(),
    )

    def fail_serialization(_report: object) -> None:
        raise ValueError("invalid report")

    monkeypatch.setattr(
        api_module,
        "serialize_bootstrap_health_report",
        fail_serialization,
    )

    response = client.get(BOOTSTRAP_HEALTH_API_PATH)

    assert response.status_code == 500


def test_endpoint_does_not_expose_internal_exception_text(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.scheduling import (
        integration_bootstrap_health_api as api_module,
    )

    def raise_internal_error(
        _app: FastAPI,
    ) -> None:
        raise RuntimeError("sensitive-internal-detail")

    monkeypatch.setattr(
        api_module,
        "get_bootstrap_health_report",
        raise_internal_error,
    )

    response = client.get(BOOTSTRAP_HEALTH_API_PATH)

    assert response.status_code == 500
    assert "sensitive-internal-detail" not in response.text


def test_response_model_rejects_unexpected_fields() -> None:
    with pytest.raises(ValueError):
        BootstrapHealthAPIResponse(
            status=BootstrapHealthStatus.HEALTHY,
            state="ready",
            context_available=True,
            components={},
            validation_passed=True,
            cleanup_errors=[],
            checked_at=datetime.now(UTC).isoformat(),
            details={},
            unexpected_field=True,  # type: ignore[call-arg]
        )


def test_response_model_serializes_status_enum() -> None:
    response = make_response(BootstrapHealthStatus.HEALTHY)

    data = response.model_dump(mode="json")

    assert data["status"] == BootstrapHealthStatus.HEALTHY.value


def test_response_model_serializes_timestamp() -> None:
    timestamp = datetime.now(UTC).isoformat()

    response = BootstrapHealthAPIResponse(
        status=BootstrapHealthStatus.HEALTHY,
        state="ready",
        context_available=True,
        components={},
        validation_passed=True,
        cleanup_errors=[],
        checked_at=timestamp,
        details={},
    )

    assert response.checked_at == timestamp
