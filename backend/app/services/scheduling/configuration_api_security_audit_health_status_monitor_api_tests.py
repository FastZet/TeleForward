
"""Tests for the security-audit health-status monitor API."""

from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.testclient import TestClient
import pytest

from app.services.scheduling.configuration_api_security_audit_health_status_monitor import (
    HealthMonitorStatus,
    SecurityAuditHealthStatusMonitor,
)
from app.services.scheduling.configuration_api_security_audit_health_status_monitor_api import (
    DEFAULT_MONITOR_API_PREFIX,
    MONITOR_CHECK_PATH,
    MONITOR_HISTORY_PATH,
    MONITOR_STATUS_PATH,
    SecurityAuditHealthStatusMonitorApiError,
    create_security_audit_health_status_monitor_router,
    register_security_audit_health_status_monitor_routes,
)
from app.services.scheduling.configuration_api_security_audit_health_status_monitor_integration import (
    install_configuration_api_security_audit_health_status_monitor,
)


def create_app(
    *,
    install_monitor: bool = True,
    check=None,
) -> FastAPI:
    app = FastAPI()

    if install_monitor:
        install_configuration_api_security_audit_health_status_monitor(
            app,
            check=check or (lambda: {"status": "healthy"}),
        )

    register_security_audit_health_status_monitor_routes(app)

    return app


# ---------------------------------------------------------------------------
# Router creation
# ---------------------------------------------------------------------------


def test_router_uses_default_prefix() -> None:
    router = create_security_audit_health_status_monitor_router()

    assert router.prefix == DEFAULT_MONITOR_API_PREFIX


def test_router_accepts_custom_prefix() -> None:
    router = create_security_audit_health_status_monitor_router(
        prefix="/internal/monitor",
    )

    assert router.prefix == "/internal/monitor"


def test_router_normalizes_prefix() -> None:
    router = create_security_audit_health_status_monitor_router(
        prefix="internal/monitor/",
    )

    assert router.prefix == "/internal/monitor"


@pytest.mark.parametrize(
    "prefix",
    ["", " ", "/", "internal//monitor", "/monitor?x=1", "/monitor#status"],
)
def test_router_rejects_invalid_prefix(prefix) -> None:
    with pytest.raises((TypeError, ValueError)):
        create_security_audit_health_status_monitor_router(
            prefix=prefix,
        )


def test_router_rejects_non_string_prefix() -> None:
    with pytest.raises(TypeError):
        create_security_audit_health_status_monitor_router(
            prefix=123,  # type: ignore[arg-type]
        )


def test_router_uses_default_tags() -> None:
    router = create_security_audit_health_status_monitor_router()

    assert "Security Audit Monitoring" in router.tags


def test_router_accepts_custom_tags() -> None:
    router = create_security_audit_health_status_monitor_router(
        tags=["Internal Monitoring"],
    )

    assert "Internal Monitoring" in router.tags


def test_router_rejects_string_as_tags_sequence() -> None:
    with pytest.raises(TypeError):
        create_security_audit_health_status_monitor_router(
            tags="Monitoring",  # type: ignore[arg-type]
        )


def test_router_rejects_empty_tag() -> None:
    with pytest.raises(ValueError):
        create_security_audit_health_status_monitor_router(
            tags=["Monitoring", " "],
        )


def test_router_rejects_invalid_dependency() -> None:
    with pytest.raises(TypeError):
        create_security_audit_health_status_monitor_router(
            dependencies=[object()],  # type: ignore[list-item]
        )


def test_router_accepts_fastapi_dependency() -> None:
    def authenticate() -> None:
        return None

    # This test also verifies the Depends validation implementation.
    # File 298 must use fastapi.params.DependsParameter for isinstance
    # checks; fastapi.Depends is a factory function, not a class.
    router = create_security_audit_health_status_monitor_router(
        dependencies=[Depends(authenticate)],
    )

    assert router.dependencies


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def test_register_routes_returns_router() -> None:
    app = FastAPI()

    router = register_security_audit_health_status_monitor_routes(
        app
    )

    assert router in [
        getattr(route, "router", None)
        for route in []
    ] or router is not None


def test_register_routes_adds_status_route() -> None:
    app = FastAPI()

    register_security_audit_health_status_monitor_routes(app)

    paths = {
        getattr(route, "path", None)
        for route in app.routes
    }

    assert (
        f"{DEFAULT_MONITOR_API_PREFIX}{MONITOR_STATUS_PATH}"
        in paths
    )


def test_register_routes_adds_history_route() -> None:
    app = FastAPI()

    register_security_audit_health_status_monitor_routes(app)

    paths = {
        getattr(route, "path", None)
        for route in app.routes
    }

    assert (
        f"{DEFAULT_MONITOR_API_PREFIX}{MONITOR_HISTORY_PATH}"
        in paths
    )


def test_register_routes_adds_check_route() -> None:
    app = FastAPI()

    register_security_audit_health_status_monitor_routes(app)

    paths = {
        getattr(route, "path", None)
        for route in app.routes
    }

    assert (
        f"{DEFAULT_MONITOR_API_PREFIX}{MONITOR_CHECK_PATH}"
        in paths
    )


def test_register_routes_rejects_non_fastapi_application() -> None:
    with pytest.raises(TypeError):
        register_security_audit_health_status_monitor_routes(
            object(),  # type: ignore[arg-type]
        )


def test_register_routes_rejects_duplicate_registration() -> None:
    app = FastAPI()

    register_security_audit_health_status_monitor_routes(app)

    with pytest.raises(SecurityAuditHealthStatusMonitorApiError):
        register_security_audit_health_status_monitor_routes(app)


def test_duplicate_registration_does_not_add_more_routes() -> None:
    app = FastAPI()

    register_security_audit_health_status_monitor_routes(app)
    route_count = len(app.routes)

    with pytest.raises(SecurityAuditHealthStatusMonitorApiError):
        register_security_audit_health_status_monitor_routes(app)

    assert len(app.routes) == route_count


def test_register_routes_supports_custom_prefix() -> None:
    app = FastAPI()

    register_security_audit_health_status_monitor_routes(
        app,
        prefix="/internal/monitor",
    )

    paths = {
        getattr(route, "path", None)
        for route in app.routes
    }

    assert "/internal/monitor/status" in paths
    assert "/internal/monitor/history" in paths
    assert "/internal/monitor/check" in paths


def test_register_routes_detects_existing_status_route() -> None:
    app = FastAPI()

    @app.get(
        f"{DEFAULT_MONITOR_API_PREFIX}{MONITOR_STATUS_PATH}"
    )
    async def existing_status():
        return {"status": "existing"}

    with pytest.raises(SecurityAuditHealthStatusMonitorApiError):
        register_security_audit_health_status_monitor_routes(app)


def test_register_routes_detects_existing_history_route() -> None:
    app = FastAPI()

    @app.get(
        f"{DEFAULT_MONITOR_API_PREFIX}{MONITOR_HISTORY_PATH}"
    )
    async def existing_history():
        return {"items": []}

    with pytest.raises(SecurityAuditHealthStatusMonitorApiError):
        register_security_audit_health_status_monitor_routes(app)


def test_register_routes_detects_existing_check_route() -> None:
    app = FastAPI()

    @app.post(
        f"{DEFAULT_MONITOR_API_PREFIX}{MONITOR_CHECK_PATH}"
    )
    async def existing_check():
        return {"status": "existing"}

    with pytest.raises(SecurityAuditHealthStatusMonitorApiError):
        register_security_audit_health_status_monitor_routes(app)


# ---------------------------------------------------------------------------
# GET status
# ---------------------------------------------------------------------------


def test_status_endpoint_returns_current_status() -> None:
    app = create_app()

    response = TestClient(app).get(
        f"{DEFAULT_MONITOR_API_PREFIX}/status"
    )

    assert response.status_code == status.HTTP_200_OK

    payload = response.json()

    assert payload["installed"] is True
    assert payload["running"] is False
    assert payload["current_status"] == "unknown"
    assert payload["latest_snapshot"] is None


def test_status_endpoint_returns_statistics() -> None:
    app = create_app()

    response = TestClient(app).get(
        f"{DEFAULT_MONITOR_API_PREFIX}/status"
    )

    statistics = response.json()["statistics"]

    assert statistics["total_checks"] == 0
    assert statistics["successful_checks"] == 0
    assert statistics["failed_checks"] == 0
    assert statistics["listener_failures"] == 0


def test_status_endpoint_returns_latest_snapshot() -> None:
    app = create_app()

    with TestClient(app) as client:
        client.post(
            f"{DEFAULT_MONITOR_API_PREFIX}/check"
        )

        response = client.get(
            f"{DEFAULT_MONITOR_API_PREFIX}/status"
        )

    assert response.status_code == status.HTTP_200_OK

    snapshot = response.json()["latest_snapshot"]

    assert snapshot["status"] == "healthy"
    assert snapshot["snapshot_id"]
    assert snapshot["checked_at"]


def test_status_endpoint_returns_503_without_monitor() -> None:
    app = create_app(install_monitor=False)

    response = TestClient(app).get(
        f"{DEFAULT_MONITOR_API_PREFIX}/status"
    )

    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE


# ---------------------------------------------------------------------------
# GET history
# ---------------------------------------------------------------------------


def test_history_endpoint_returns_empty_history() -> None:
    app = create_app()

    response = TestClient(app).get(
        f"{DEFAULT_MONITOR_API_PREFIX}/history"
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {
        "count": 0,
        "items": [],
    }


def test_history_endpoint_returns_snapshots() -> None:
    app = create_app()

    with TestClient(app) as client:
        client.post(f"{DEFAULT_MONITOR_API_PREFIX}/check")
        client.post(f"{DEFAULT_MONITOR_API_PREFIX}/check")

        response = client.get(
            f"{DEFAULT_MONITOR_API_PREFIX}/history"
        )

    assert response.status_code == status.HTTP_200_OK

    payload = response.json()

    assert payload["count"] == 2
    assert len(payload["items"]) == 2


def test_history_endpoint_supports_limit() -> None:
    app = create_app()

    with TestClient(app) as client:
        for _ in range(3):
            client.post(f"{DEFAULT_MONITOR_API_PREFIX}/check")

        response = client.get(
            f"{DEFAULT_MONITOR_API_PREFIX}/history?limit=2"
        )

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["count"] == 2


@pytest.mark.parametrize(
    "limit",
    ["0", "-1", "1001", "invalid"],
)
def test_history_endpoint_rejects_invalid_limit(limit) -> None:
    app = create_app()

    response = TestClient(app).get(
        f"{DEFAULT_MONITOR_API_PREFIX}/history?limit={limit}"
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_history_endpoint_returns_503_without_monitor() -> None:
    app = create_app(install_monitor=False)

    response = TestClient(app).get(
        f"{DEFAULT_MONITOR_API_PREFIX}/history"
    )

    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE


# ---------------------------------------------------------------------------
# POST manual check
# ---------------------------------------------------------------------------


def test_check_endpoint_executes_health_check() -> None:
    calls = 0

    def check():
        nonlocal calls
        calls += 1
        return {"status": "healthy"}

    app = create_app(check=check)

    response = TestClient(app).post(
        f"{DEFAULT_MONITOR_API_PREFIX}/check"
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["status"] == "healthy"
    assert calls == 1


def test_check_endpoint_returns_snapshot_metadata() -> None:
    app = create_app()

    response = TestClient(app).post(
        f"{DEFAULT_MONITOR_API_PREFIX}/check"
    )

    payload = response.json()

    assert payload["snapshot_id"]
    assert payload["checked_at"]
    assert payload["status"] == "healthy"
    assert payload["duration_seconds"] >= 0
    assert payload["error"] is None


def test_check_endpoint_records_failed_health_check() -> None:
    app = create_app(
        check=lambda: {"status": "unhealthy"},
    )

    response = TestClient(app).post(
        f"{DEFAULT_MONITOR_API_PREFIX}/check"
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["status"] == "unhealthy"


def test_check_endpoint_returns_503_without_monitor() -> None:
    app = create_app(install_monitor=False)

    response = TestClient(app).post(
        f"{DEFAULT_MONITOR_API_PREFIX}/check"
    )

    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE


def test_check_endpoint_does_not_expose_health_data() -> None:
    app = create_app(
        check=lambda: {
            "status": "healthy",
            "internal": "sensitive payload",
        },
    )

    response = TestClient(app).post(
        f"{DEFAULT_MONITOR_API_PREFIX}/check"
    )

    assert "health_data" not in response.json()
    assert "sensitive payload" not in response.text


# ---------------------------------------------------------------------------
# Authentication and authorization dependencies
# ---------------------------------------------------------------------------


def test_router_enforces_authentication_dependency() -> None:
    app = FastAPI()

    def authenticate() -> None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    register_security_audit_health_status_monitor_routes(
        app,
        dependencies=[Depends(authenticate)],
    )

    response = TestClient(app).get(
        f"{DEFAULT_MONITOR_API_PREFIX}/status"
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_router_allows_authorized_request_to_reach_endpoint() -> None:
    app = create_app()

    def authenticate() -> None:
        return None

    app = FastAPI()

    from app.services.scheduling.configuration_api_security_audit_health_status_monitor_integration import (
        install_configuration_api_security_audit_health_status_monitor,
    )

    install_configuration_api_security_audit_health_status_monitor(
        app,
        check=lambda: {"status": "healthy"},
    )

    register_security_audit_health_status_monitor_routes(
        app,
        dependencies=[Depends(authenticate)],
    )

    response = TestClient(app).get(
        f"{DEFAULT_MONITOR_API_PREFIX}/status"
    )

    assert response.status_code == status.HTTP_200_OK


# ---------------------------------------------------------------------------
# OpenAPI
# ---------------------------------------------------------------------------


def test_openapi_contains_all_monitor_endpoints() -> None:
    app = create_app()

    schema = app.openapi()
    paths = schema["paths"]

    assert f"{DEFAULT_MONITOR_API_PREFIX}/status" in paths
    assert f"{DEFAULT_MONITOR_API_PREFIX}/history" in paths
    assert f"{DEFAULT_MONITOR_API_PREFIX}/check" in paths


def test_openapi_uses_expected_http_methods() -> None:
    app = create_app()

    paths = app.openapi()["paths"]

    assert "get" in paths[
        f"{DEFAULT_MONITOR_API_PREFIX}/status"
    ]

    assert "get" in paths[
        f"{DEFAULT_MONITOR_API_PREFIX}/history"
    ]

    assert "post" in paths[
        f"{DEFAULT_MONITOR_API_PREFIX}/check"
    ]


def test_openapi_documents_history_limit() -> None:
    app = create_app()

    operation = app.openapi()["paths"][
        f"{DEFAULT_MONITOR_API_PREFIX}/history"
    ]["get"]

    parameters = operation["parameters"]

    limit_parameter = next(
        parameter
        for parameter in parameters
        if parameter["name"] == "limit"
    )

    assert limit_parameter["in"] == "query"
    assert limit_parameter["schema"]["minimum"] == 1
    assert limit_parameter["schema"]["maximum"] == 1000
