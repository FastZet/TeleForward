
"""Tests for the security audit health API."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.testclient import TestClient

from app.services.scheduling.configuration_api_security_audit import (
    SecurityAuditLogger,
)
from app.services.scheduling.configuration_api_security_audit_health_integration import (
    install_configuration_api_security_audit_health,
)
from app.services.scheduling.configuration_api_security_audit_health_api import (
    DEFAULT_HEALTH_PREFIX,
    DEFAULT_HEALTH_ROUTE,
    create_security_audit_health_router,
    register_security_audit_health_routes,
)


@pytest.fixture
def app() -> FastAPI:
    return FastAPI()


@pytest.fixture
def audit_path(tmp_path: Path) -> Path:
    return tmp_path / "security-audit.jsonl"


@pytest.fixture
def audit_logger(audit_path: Path):
    logger = SecurityAuditLogger(audit_path, fsync=False)

    try:
        yield logger
    finally:
        logger.close()


@pytest.fixture
def configured_app(
    app: FastAPI,
    audit_logger: SecurityAuditLogger,
    audit_path: Path,
) -> FastAPI:
    install_configuration_api_security_audit_health(
        app,
        audit_logger=audit_logger,
        audit_file_path=str(audit_path),
    )
    register_security_audit_health_routes(app)
    return app


# ---------------------------------------------------------------------------
# Router construction
# ---------------------------------------------------------------------------


def test_create_router_returns_api_router() -> None:
    from fastapi import APIRouter

    router = create_security_audit_health_router()

    assert isinstance(router, APIRouter)


def test_default_router_prefix() -> None:
    router = create_security_audit_health_router()

    paths = {route.path for route in router.routes}

    assert (
        f"{DEFAULT_HEALTH_PREFIX}{DEFAULT_HEALTH_ROUTE}"
        in paths
    )


def test_custom_prefix_is_supported() -> None:
    router = create_security_audit_health_router(
        prefix="/internal/security"
    )

    paths = {route.path for route in router.routes}

    assert "/internal/security/health" in paths


def test_prefix_without_leading_slash_is_normalized() -> None:
    router = create_security_audit_health_router(
        prefix="internal/security"
    )

    paths = {route.path for route in router.routes}

    assert "/internal/security/health" in paths


def test_prefix_trailing_slash_is_removed() -> None:
    router = create_security_audit_health_router(
        prefix="/internal/security/"
    )

    paths = {route.path for route in router.routes}

    assert "/internal/security/health" in paths


@pytest.mark.parametrize(
    "prefix",
    [
        "",
        " ",
        "/",
    ],
)
def test_invalid_empty_prefix_is_rejected(prefix: str) -> None:
    with pytest.raises(ValueError):
        create_security_audit_health_router(prefix=prefix)


@pytest.mark.parametrize(
    "prefix",
    [
        "/internal//security",
        "//internal",
    ],
)
def test_consecutive_slashes_are_rejected(prefix: str) -> None:
    with pytest.raises(ValueError):
        create_security_audit_health_router(prefix=prefix)


def test_non_string_prefix_is_rejected() -> None:
    with pytest.raises(TypeError):
        create_security_audit_health_router(
            prefix=123,  # type: ignore[arg-type]
        )


def test_invalid_dependencies_container_is_rejected() -> None:
    with pytest.raises(TypeError):
        create_security_audit_health_router(
            dependencies=object(),  # type: ignore[arg-type]
        )


def test_invalid_dependency_entry_is_rejected() -> None:
    with pytest.raises(TypeError):
        create_security_audit_health_router(
            dependencies=[object()],  # type: ignore[list-item]
        )


def test_empty_tags_are_rejected() -> None:
    with pytest.raises(TypeError):
        create_security_audit_health_router(
            tags=["Security", " "],
        )


def test_non_list_tags_are_rejected() -> None:
    with pytest.raises(TypeError):
        create_security_audit_health_router(
            tags=("Security",),  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------------------
# Successful health endpoint
# ---------------------------------------------------------------------------


def test_health_endpoint_returns_200(
    configured_app: FastAPI,
) -> None:
    client = TestClient(configured_app)

    response = client.get(
        f"{DEFAULT_HEALTH_PREFIX}{DEFAULT_HEALTH_ROUTE}"
    )

    assert response.status_code == status.HTTP_200_OK


def test_health_endpoint_returns_health_report(
    configured_app: FastAPI,
) -> None:
    client = TestClient(configured_app)

    response = client.get(
        f"{DEFAULT_HEALTH_PREFIX}{DEFAULT_HEALTH_ROUTE}"
    )

    data = response.json()

    assert data["status"] == "healthy"
    assert data["healthy"] is True
    assert data["logger_available"] is True
    assert isinstance(data["checks"], list)


def test_health_endpoint_uses_custom_prefix(
    app: FastAPI,
    audit_logger: SecurityAuditLogger,
    audit_path: Path,
) -> None:
    install_configuration_api_security_audit_health(
        app,
        audit_logger=audit_logger,
        audit_file_path=str(audit_path),
    )

    register_security_audit_health_routes(
        app,
        prefix="/internal/health",
    )

    client = TestClient(app)

    response = client.get("/internal/health/health")

    assert response.status_code == status.HTTP_200_OK


def test_health_endpoint_does_not_expose_audit_events(
    configured_app: FastAPI,
) -> None:
    client = TestClient(configured_app)

    response = client.get(
        f"{DEFAULT_HEALTH_PREFIX}{DEFAULT_HEALTH_ROUTE}"
    )

    data = response.json()

    assert "events" not in data
    assert "records" not in data
    assert "audit_log" not in data


# ---------------------------------------------------------------------------
# Missing integration and unavailable health service
# ---------------------------------------------------------------------------


def test_missing_health_service_returns_503(
    app: FastAPI,
) -> None:
    register_security_audit_health_routes(app)

    client = TestClient(app)

    response = client.get(
        f"{DEFAULT_HEALTH_PREFIX}{DEFAULT_HEALTH_ROUTE}"
    )

    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE


def test_missing_health_service_returns_error_envelope(
    app: FastAPI,
) -> None:
    register_security_audit_health_routes(app)

    client = TestClient(app)

    response = client.get(
        f"{DEFAULT_HEALTH_PREFIX}{DEFAULT_HEALTH_ROUTE}"
    )

    data = response.json()

    assert data["detail"]["error"] == (
        "security_audit_health_unavailable"
    )
    assert isinstance(data["detail"]["message"], str)


def test_health_endpoint_reports_missing_logger_as_unhealthy(
    app: FastAPI,
) -> None:
    install_configuration_api_security_audit_health(app)
    register_security_audit_health_routes(app)

    client = TestClient(app)

    response = client.get(
        f"{DEFAULT_HEALTH_PREFIX}{DEFAULT_HEALTH_ROUTE}"
    )

    assert response.status_code == status.HTTP_200_OK

    data = response.json()

    assert data["status"] == "unhealthy"
    assert data["healthy"] is False
    assert data["logger_available"] is False


# ---------------------------------------------------------------------------
# Router-level dependencies
# ---------------------------------------------------------------------------


def test_router_dependency_is_enforced(
    app: FastAPI,
    audit_logger: SecurityAuditLogger,
) -> None:
    install_configuration_api_security_audit_health(
        app,
        audit_logger=audit_logger,
    )

    def require_token() -> None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    router = create_security_audit_health_router(
        dependencies=[Depends(require_token)],
    )

    app.include_router(router)

    client = TestClient(app)

    response = client.get(
        f"{DEFAULT_HEALTH_PREFIX}{DEFAULT_HEALTH_ROUTE}"
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_router_dependency_allows_authorized_request(
    app: FastAPI,
    audit_logger: SecurityAuditLogger,
) -> None:
    install_configuration_api_security_audit_health(
        app,
        audit_logger=audit_logger,
    )

    def require_token() -> None:
        return None

    router = create_security_audit_health_router(
        dependencies=[Depends(require_token)],
    )

    app.include_router(router)

    client = TestClient(app)

    response = client.get(
        f"{DEFAULT_HEALTH_PREFIX}{DEFAULT_HEALTH_ROUTE}"
    )

    assert response.status_code == status.HTTP_200_OK


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_register_routes_returns_router(
    app: FastAPI,
) -> None:
    from fastapi import APIRouter

    router = register_security_audit_health_routes(app)

    assert isinstance(router, APIRouter)


def test_register_routes_rejects_non_fastapi_application() -> None:
    with pytest.raises(TypeError):
        register_security_audit_health_routes(
            object(),  # type: ignore[arg-type]
        )


def test_duplicate_route_registration_is_rejected(
    app: FastAPI,
) -> None:
    register_security_audit_health_routes(app)

    with pytest.raises(RuntimeError, match="already registered"):
        register_security_audit_health_routes(app)


def test_duplicate_registration_does_not_add_another_route(
    app: FastAPI,
) -> None:
    register_security_audit_health_routes(app)

    route_count_before = sum(
        getattr(route, "name", None) == "security_audit_health"
        for route in app.routes
    )

    with pytest.raises(RuntimeError):
        register_security_audit_health_routes(app)

    route_count_after = sum(
        getattr(route, "name", None) == "security_audit_health"
        for route in app.routes
    )

    assert route_count_after == route_count_before


def test_custom_prefix_registration(
    app: FastAPI,
) -> None:
    register_security_audit_health_routes(
        app,
        prefix="/admin/audit",
    )

    paths = {
        getattr(route, "path", None)
        for route in app.routes
    }

    assert "/admin/audit/health" in paths


# ---------------------------------------------------------------------------
# OpenAPI
# ---------------------------------------------------------------------------


def test_health_route_is_in_openapi(
    app: FastAPI,
) -> None:
    register_security_audit_health_routes(app)

    schema = app.openapi()

    path = f"{DEFAULT_HEALTH_PREFIX}{DEFAULT_HEALTH_ROUTE}"

    assert path in schema["paths"]
    assert "get" in schema["paths"][path]


def test_openapi_contains_health_operation_summary(
    app: FastAPI,
) -> None:
    register_security_audit_health_routes(app)

    schema = app.openapi()

    operation = schema["paths"][
        f"{DEFAULT_HEALTH_PREFIX}{DEFAULT_HEALTH_ROUTE}"
    ]["get"]

    assert operation["summary"] == (
        "Get security audit subsystem health"
    )


def test_openapi_documents_service_unavailable_response(
    app: FastAPI,
) -> None:
    register_security_audit_health_routes(app)

    schema = app.openapi()

    operation = schema["paths"][
        f"{DEFAULT_HEALTH_PREFIX}{DEFAULT_HEALTH_ROUTE}"
    ]["get"]

    assert "503" in operation["responses"]


# ---------------------------------------------------------------------------
# Application isolation
# ---------------------------------------------------------------------------


def test_health_routes_are_isolated_between_applications() -> None:
    first_app = FastAPI()
    second_app = FastAPI()

    register_security_audit_health_routes(first_app)

    first_paths = {
        getattr(route, "path", None)
        for route in first_app.routes
    }
    second_paths = {
        getattr(route, "path", None)
        for route in second_app.routes
    }

    expected_path = (
        f"{DEFAULT_HEALTH_PREFIX}{DEFAULT_HEALTH_ROUTE}"
    )

    assert expected_path in first_paths
    assert expected_path not in second_paths
