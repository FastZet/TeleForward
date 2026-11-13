
"""Tests for the consolidated security audit health-status API."""

from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.testclient import TestClient

from app.services.scheduling.configuration_api_security_audit_health_status_integration import (
    install_configuration_api_security_audit_health_status,
)
from app.services.scheduling.configuration_api_security_audit_health_status_api import (
    DEFAULT_STATUS_PREFIX,
    DEFAULT_STATUS_ROUTE,
    create_security_audit_health_status_router,
    register_security_audit_health_status_routes,
)


@pytest.fixture
def app() -> FastAPI:
    return FastAPI()


@pytest.fixture
def configured_app(app: FastAPI) -> FastAPI:
    install_configuration_api_security_audit_health_status(app)
    register_security_audit_health_status_routes(app)
    return app


# ---------------------------------------------------------------------------
# Router construction
# ---------------------------------------------------------------------------


def test_create_router_returns_api_router():
    from fastapi import APIRouter

    router = create_security_audit_health_status_router()

    assert isinstance(router, APIRouter)


def test_default_router_prefix():
    router = create_security_audit_health_status_router()

    paths = {route.path for route in router.routes}

    assert (
        f"{DEFAULT_STATUS_PREFIX}{DEFAULT_STATUS_ROUTE}"
        in paths
    )


def test_custom_prefix_is_supported():
    router = create_security_audit_health_status_router(
        prefix="/internal/security"
    )

    paths = {route.path for route in router.routes}

    assert "/internal/security/status" in paths


def test_prefix_without_leading_slash_is_normalized():
    router = create_security_audit_health_status_router(
        prefix="internal/security"
    )

    paths = {route.path for route in router.routes}

    assert "/internal/security/status" in paths


def test_trailing_prefix_slash_is_removed():
    router = create_security_audit_health_status_router(
        prefix="/internal/security/"
    )

    paths = {route.path for route in router.routes}

    assert "/internal/security/status" in paths


def test_empty_prefix_is_rejected():
    import pytest

    with pytest.raises(ValueError):
        create_security_audit_health_status_router(prefix=" ")


def test_root_prefix_is_rejected():
    import pytest

    with pytest.raises(ValueError):
        create_security_audit_health_status_router(prefix="/")


def test_consecutive_slashes_are_rejected():
    import pytest

    with pytest.raises(ValueError):
        create_security_audit_health_status_router(
            prefix="/internal//security"
        )


def test_parameterized_prefix_is_rejected():
    import pytest

    with pytest.raises(ValueError):
        create_security_audit_health_status_router(
            prefix="/internal/{tenant}"
        )


def test_non_string_prefix_is_rejected():
    import pytest

    with pytest.raises(TypeError):
        create_security_audit_health_status_router(
            prefix=123,  # type: ignore[arg-type]
        )


def test_invalid_dependency_is_rejected():
    import pytest

    with pytest.raises(TypeError):
        create_security_audit_health_status_router(
            dependencies=[object()],  # type: ignore[list-item]
        )


def test_valid_dependency_is_accepted():
    def authenticate() -> None:
        return None

    router = create_security_audit_health_status_router(
        dependencies=[Depends(authenticate)]
    )

    assert router is not None


def test_invalid_tags_are_rejected():
    import pytest

    with pytest.raises(TypeError):
        create_security_audit_health_status_router(
            tags=["Security", " "],
        )


# ---------------------------------------------------------------------------
# Successful endpoint responses
# ---------------------------------------------------------------------------


def test_status_endpoint_returns_200(
    configured_app: FastAPI,
):
    client = TestClient(configured_app)

    response = client.get(
        f"{DEFAULT_STATUS_PREFIX}{DEFAULT_STATUS_ROUTE}"
    )

    assert response.status_code == status.HTTP_200_OK


def test_status_endpoint_returns_consolidated_snapshot(
    configured_app: FastAPI,
):
    client = TestClient(configured_app)

    response = client.get(
        f"{DEFAULT_STATUS_PREFIX}{DEFAULT_STATUS_ROUTE}"
    )

    data = response.json()

    assert "status" in data
    assert "healthy" in data
    assert "checked_at" in data
    assert "components" in data
    assert "messages" in data


def test_status_endpoint_includes_audit_component(
    configured_app: FastAPI,
):
    client = TestClient(configured_app)

    response = client.get(
        f"{DEFAULT_STATUS_PREFIX}{DEFAULT_STATUS_ROUTE}"
    )

    data = response.json()

    audit_component = next(
        (
            component
            for component in data["components"]
            if component["name"] == "audit_logger"
        ),
        None,
    )

    assert audit_component is not None
    assert audit_component["status"] == "unknown"


def test_status_endpoint_includes_health_api_component(
    configured_app: FastAPI,
):
    client = TestClient(configured_app)

    response = client.get(
        f"{DEFAULT_STATUS_PREFIX}{DEFAULT_STATUS_ROUTE}"
    )

    data = response.json()

    api_component = next(
        (
            component
            for component in data["components"]
            if component["name"] == "health_api"
        ),
        None,
    )

    assert api_component is not None
    assert api_component["status"] == "healthy"


def test_status_endpoint_uses_custom_prefix(
    app: FastAPI,
):
    install_configuration_api_security_audit_health_status(app)

    register_security_audit_health_status_routes(
        app,
        prefix="/internal/audit",
    )

    response = TestClient(app).get(
        "/internal/audit/status"
    )

    assert response.status_code == status.HTTP_200_OK


def test_status_endpoint_returns_json(
    configured_app: FastAPI,
):
    response = TestClient(configured_app).get(
        f"{DEFAULT_STATUS_PREFIX}{DEFAULT_STATUS_ROUTE}"
    )

    assert response.headers["content-type"].startswith(
        "application/json"
    )


# ---------------------------------------------------------------------------
# Missing integration and errors
# ---------------------------------------------------------------------------


def test_missing_status_integration_returns_503(
    app: FastAPI,
):
    register_security_audit_health_status_routes(app)

    response = TestClient(app).get(
        f"{DEFAULT_STATUS_PREFIX}{DEFAULT_STATUS_ROUTE}"
    )

    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE


def test_missing_status_integration_returns_error_envelope(
    app: FastAPI,
):
    register_security_audit_health_status_routes(app)

    response = TestClient(app).get(
        f"{DEFAULT_STATUS_PREFIX}{DEFAULT_STATUS_ROUTE}"
    )

    data = response.json()

    assert data["detail"]["error"] == (
        "security_audit_health_status_unavailable"
    )
    assert isinstance(data["detail"]["message"], str)


# ---------------------------------------------------------------------------
# Authentication and authorization dependencies
# ---------------------------------------------------------------------------


def test_authentication_dependency_is_enforced(
    app: FastAPI,
):
    install_configuration_api_security_audit_health_status(app)

    def require_authentication() -> None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    router = create_security_audit_health_status_router(
        dependencies=[Depends(require_authentication)]
    )

    app.include_router(router)

    response = TestClient(app).get(
        f"{DEFAULT_STATUS_PREFIX}{DEFAULT_STATUS_ROUTE}"
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_authorized_request_can_access_endpoint(
    app: FastAPI,
):
    install_configuration_api_security_audit_health_status(app)

    def require_authentication() -> None:
        return None

    router = create_security_audit_health_status_router(
        dependencies=[Depends(require_authentication)]
    )

    app.include_router(router)

    response = TestClient(app).get(
        f"{DEFAULT_STATUS_PREFIX}{DEFAULT_STATUS_ROUTE}"
    )

    assert response.status_code == status.HTTP_200_OK


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def test_register_routes_returns_router(
    app: FastAPI,
):
    from fastapi import APIRouter

    router = register_security_audit_health_status_routes(app)

    assert isinstance(router, APIRouter)


def test_register_routes_rejects_non_fastapi_application():
    import pytest

    with pytest.raises(TypeError):
        register_security_audit_health_status_routes(
            object(),  # type: ignore[arg-type]
        )


def test_duplicate_registration_is_rejected(
    app: FastAPI,
):
    import pytest

    register_security_audit_health_status_routes(app)

    with pytest.raises(RuntimeError, match="already exists"):
        register_security_audit_health_status_routes(app)


def test_duplicate_registration_does_not_add_route(
    app: FastAPI,
):
    import pytest

    register_security_audit_health_status_routes(app)

    route_count_before = sum(
        getattr(route, "path", None)
        == f"{DEFAULT_STATUS_PREFIX}{DEFAULT_STATUS_ROUTE}"
        and "GET" in (getattr(route, "methods", None) or set())
        for route in app.routes
    )

    with pytest.raises(RuntimeError):
        register_security_audit_health_status_routes(app)

    route_count_after = sum(
        getattr(route, "path", None)
        == f"{DEFAULT_STATUS_PREFIX}{DEFAULT_STATUS_ROUTE}"
        and "GET" in (getattr(route, "methods", None) or set())
        for route in app.routes
    )

    assert route_count_after == route_count_before


def test_custom_prefix_registration(
    app: FastAPI,
):
    register_security_audit_health_status_routes(
        app,
        prefix="/admin/security/audit",
    )

    paths = {
        getattr(route, "path", None)
        for route in app.routes
    }

    assert "/admin/security/audit/status" in paths


# ---------------------------------------------------------------------------
# OpenAPI documentation
# ---------------------------------------------------------------------------


def test_status_route_is_in_openapi(
    app: FastAPI,
):
    register_security_audit_health_status_routes(app)

    schema = app.openapi()

    path = f"{DEFAULT_STATUS_PREFIX}{DEFAULT_STATUS_ROUTE}"

    assert path in schema["paths"]
    assert "get" in schema["paths"][path]


def test_openapi_contains_operation_summary(
    app: FastAPI,
):
    register_security_audit_health_status_routes(app)

    schema = app.openapi()

    operation = schema["paths"][
        f"{DEFAULT_STATUS_PREFIX}{DEFAULT_STATUS_ROUTE}"
    ]["get"]

    assert operation["summary"] == (
        "Get consolidated security audit health status"
    )


def test_openapi_documents_503_response(
    app: FastAPI,
):
    register_security_audit_health_status_routes(app)

    schema = app.openapi()

    operation = schema["paths"][
        f"{DEFAULT_STATUS_PREFIX}{DEFAULT_STATUS_ROUTE}"
    ]["get"]

    assert "503" in operation["responses"]


def test_custom_tags_are_in_openapi(
    app: FastAPI,
):
    register_security_audit_health_status_routes(
        app,
        tags=["Internal Monitoring"],
    )

    schema = app.openapi()

    operation = schema["paths"][
        f"{DEFAULT_STATUS_PREFIX}{DEFAULT_STATUS_ROUTE}"
    ]["get"]

    assert "Internal Monitoring" in operation["tags"]


# ---------------------------------------------------------------------------
# Application isolation
# ---------------------------------------------------------------------------


def test_routes_are_isolated_between_applications():
    first_app = FastAPI()
    second_app = FastAPI()

    register_security_audit_health_status_routes(first_app)

    expected_path = (
        f"{DEFAULT_STATUS_PREFIX}{DEFAULT_STATUS_ROUTE}"
    )

    first_paths = {
        getattr(route, "path", None)
        for route in first_app.routes
    }

    second_paths = {
        getattr(route, "path", None)
        for route in second_app.routes
    }

    assert expected_path in first_paths
    assert expected_path not in second_paths
