
"""Tests for the scheduler runtime lifespan health API."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services.scheduling import (
    scheduler_runtime_lifespan_health_api as health_api,
)
from app.services.scheduling.scheduler_runtime_lifespan_health import (
    SchedulerLifespanHealthStatus,
)
from app.services.scheduling.scheduler_runtime_lifespan_health_integration import (
    SchedulerLifespanHealthIntegrationError,
)


@pytest.fixture
def app() -> FastAPI:
    """Create a FastAPI application with the health API installed."""

    application = FastAPI()
    health_api.install_scheduler_health_api(application)
    return application


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    """Create a test client."""

    return TestClient(app)


def make_health_report(
    health_status: SchedulerLifespanHealthStatus,
) -> dict:
    """Create a representative scheduler health report."""

    return {
        "status": health_status.value,
        "runtime_installed": True,
        "lifecycle_state": "running",
        "is_running": True,
        "task_count": 4,
        "job_count": 3,
        "checked_at": datetime.now(UTC).isoformat(),
        "details": [],
    }


@pytest.mark.parametrize(
    ("health_status", "expected_http_status"),
    [
        (SchedulerLifespanHealthStatus.HEALTHY, 200),
        (SchedulerLifespanHealthStatus.DEGRADED, 503),
        (SchedulerLifespanHealthStatus.UNAVAILABLE, 503),
        (SchedulerLifespanHealthStatus.FAILED, 503),
    ],
)
def test_http_status_mapping(
    health_status: SchedulerLifespanHealthStatus,
    expected_http_status: int,
) -> None:
    """Health states must map to the expected HTTP status codes."""

    actual = health_api._http_status_for_health(
        health_status.value
    )

    assert actual == expected_http_status


def test_unknown_health_status_returns_service_unavailable() -> None:
    """Unknown health states must fail closed."""

    assert (
        health_api._http_status_for_health("unknown")
        == 503
    )


def test_build_health_response_returns_healthy_status() -> None:
    """A healthy report must produce HTTP 200."""

    report = make_health_report(
        SchedulerLifespanHealthStatus.HEALTHY
    )

    response = health_api._build_health_response(report)

    assert response.status_code == 200
    assert response.body


def test_build_health_response_returns_unhealthy_status() -> None:
    """A degraded report must produce HTTP 503."""

    report = make_health_report(
        SchedulerLifespanHealthStatus.DEGRADED
    )

    response = health_api._build_health_response(report)

    assert response.status_code == 503


def test_build_health_response_rejects_missing_status() -> None:
    """A report without a status must be rejected."""

    with pytest.raises(
        ValueError,
        match="string status",
    ):
        health_api._build_health_response({})


def test_build_health_response_rejects_non_string_status() -> None:
    """A non-string status must be rejected."""

    with pytest.raises(
        ValueError,
        match="string status",
    ):
        health_api._build_health_response(
            {"status": 123}
        )


def test_endpoint_returns_healthy_report(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The endpoint must return the health service report."""

    report = make_health_report(
        SchedulerLifespanHealthStatus.HEALTHY
    )

    monkeypatch.setattr(
        health_api,
        "get_scheduler_lifespan_health_status",
        lambda app: report,
    )

    response = client.get("/health/scheduler")

    assert response.status_code == 200
    assert response.json() == report


def test_endpoint_returns_degraded_report(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A degraded scheduler must return HTTP 503."""

    report = make_health_report(
        SchedulerLifespanHealthStatus.DEGRADED
    )

    monkeypatch.setattr(
        health_api,
        "get_scheduler_lifespan_health_status",
        lambda app: report,
    )

    response = client.get("/health/scheduler")

    assert response.status_code == 503
    assert response.json()["status"] == "degraded"


def test_endpoint_handles_missing_health_service(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing health integration must return HTTP 503."""

    def raise_integration_error(app: FastAPI) -> None:
        raise SchedulerLifespanHealthIntegrationError(
            "Health service is not installed"
        )

    monkeypatch.setattr(
        health_api,
        "get_scheduler_lifespan_health_status",
        raise_integration_error,
    )

    response = client.get("/health/scheduler")

    assert response.status_code == 503
    assert response.json() == {
        "detail": "Scheduler health service is unavailable"
    }


def test_endpoint_handles_invalid_report(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Invalid reports must return HTTP 503."""

    monkeypatch.setattr(
        health_api,
        "get_scheduler_lifespan_health_status",
        lambda app: {"status": None},
    )

    response = client.get("/health/scheduler")

    assert response.status_code == 503
    assert response.json() == {
        "detail": "Scheduler health report is invalid"
    }


def test_endpoint_handles_unexpected_exception(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unexpected inspection failures must return HTTP 500."""

    def raise_unexpected_error(app: FastAPI) -> None:
        raise RuntimeError("Internal diagnostic failure")

    monkeypatch.setattr(
        health_api,
        "get_scheduler_lifespan_health_status",
        raise_unexpected_error,
    )

    response = client.get("/health/scheduler")

    assert response.status_code == 500
    assert response.json() == {
        "detail": "Unable to inspect scheduler health"
    }

    assert "Internal diagnostic failure" not in response.text


def test_endpoint_uses_current_application(
    client: TestClient,
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The endpoint must pass its own application to the integration."""

    received_apps: list[FastAPI] = []

    def inspect_application(application: FastAPI) -> dict:
        received_apps.append(application)

        return make_health_report(
            SchedulerLifespanHealthStatus.HEALTHY
        )

    monkeypatch.setattr(
        health_api,
        "get_scheduler_lifespan_health_status",
        inspect_application,
    )

    response = client.get("/health/scheduler")

    assert response.status_code == 200
    assert received_apps == [app]


def test_install_rejects_non_fastapi_application() -> None:
    """Installation must require a FastAPI application."""

    with pytest.raises(
        TypeError,
        match="FastAPI instance",
    ):
        health_api.install_scheduler_health_api(
            Mock()
        )


def test_install_rejects_non_boolean_replace_flag() -> None:
    """The replace argument must be a boolean."""

    application = FastAPI()

    with pytest.raises(
        TypeError,
        match="replace must be a boolean",
    ):
        health_api.install_scheduler_health_api(
            application,
            replace="yes",  # type: ignore[arg-type]
        )


def test_install_registers_router() -> None:
    """Installation must register the scheduler health route."""

    application = FastAPI()

    installed_router = health_api.install_scheduler_health_api(
        application
    )

    assert installed_router is health_api.router
    assert getattr(
        application.state,
        "scheduler_health_api_installed",
        False,
    )

    paths = {
        route.path
        for route in application.routes
    }

    assert "/health/scheduler" in paths


def test_install_rejects_duplicate_registration() -> None:
    """Repeated installation must be rejected by default."""

    application = FastAPI()

    health_api.install_scheduler_health_api(application)

    with pytest.raises(
        RuntimeError,
        match="already installed",
    ):
        health_api.install_scheduler_health_api(application)


def test_install_with_replace_does_not_duplicate_routes() -> None:
    """replace=True must not register the router a second time."""

    application = FastAPI()

    health_api.install_scheduler_health_api(application)

    original_route_count = len(application.routes)

    result = health_api.install_scheduler_health_api(
        application,
        replace=True,
    )

    assert result is health_api.router
    assert len(application.routes) == original_route_count
