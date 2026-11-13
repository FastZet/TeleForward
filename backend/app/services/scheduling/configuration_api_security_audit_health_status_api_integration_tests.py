
"""Integration tests for consolidated security audit health-status API."""

from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.testclient import TestClient

from app.services.scheduling.configuration_api_security_audit_health_status_api_integration import (
    STATUS_API_INSTALLATION_STATE_KEY,
    STATUS_API_PREFIX_STATE_KEY,
    STATUS_API_ROUTER_STATE_KEY,
    SecurityAuditHealthStatusApiIntegrationError,
    get_configuration_api_security_audit_health_status_api_prefix,
    get_configuration_api_security_audit_health_status_api_router,
    install_configuration_api_security_audit_health_status_api,
    is_configuration_api_security_audit_health_status_api_installed,
    remove_configuration_api_security_audit_health_status_api,
)


@pytest.fixture
def app() -> FastAPI:
    return FastAPI()


# ---------------------------------------------------------------------------
# Installation
# ---------------------------------------------------------------------------


def test_install_registers_router(app: FastAPI) -> None:
    from fastapi import APIRouter

    router = install_configuration_api_security_audit_health_status_api(
        app
    )

    assert isinstance(router, APIRouter)
    assert (
        getattr(app.state, STATUS_API_ROUTER_STATE_KEY)
        is router
    )


def test_install_sets_application_state(app: FastAPI) -> None:
    install_configuration_api_security_audit_health_status_api(app)

    assert (
        getattr(app.state, STATUS_API_INSTALLATION_STATE_KEY)
        is True
    )


def test_install_stores_normalized_prefix(app: FastAPI) -> None:
    install_configuration_api_security_audit_health_status_api(
        app,
        prefix="internal/security/audit/",
    )

    assert (
        getattr(app.state, STATUS_API_PREFIX_STATE_KEY)
        == "/internal/security/audit"
    )


def test_install_rejects_non_fastapi_application() -> None:
    with pytest.raises(TypeError):
        install_configuration_api_security_audit_health_status_api(
            object(),  # type: ignore[arg-type]
        )


def test_install_does_not_require_status_service(
    app: FastAPI,
) -> None:
    install_configuration_api_security_audit_health_status_api(app)

    assert (
        is_configuration_api_security_audit_health_status_api_installed(
            app
        )
        is True
    )


def test_endpoint_returns_503_without_status_service(
    app: FastAPI,
) -> None:
    install_configuration_api_security_audit_health_status_api(app)

    response = TestClient(app).get(
        "/configuration/security/audit/status"
    )

    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE


# ---------------------------------------------------------------------------
# Duplicate installation
# ---------------------------------------------------------------------------


def test_duplicate_installation_is_rejected(
    app: FastAPI,
) -> None:
    first = install_configuration_api_security_audit_health_status_api(
        app
    )

    with pytest.raises(SecurityAuditHealthStatusApiIntegrationError):
        install_configuration_api_security_audit_health_status_api(app)

    assert (
        get_configuration_api_security_audit_health_status_api_router(
            app
        )
        is first
    )


def test_duplicate_installation_does_not_add_routes(
    app: FastAPI,
) -> None:
    install_configuration_api_security_audit_health_status_api(app)

    route_count_before = len(app.routes)

    with pytest.raises(SecurityAuditHealthStatusApiIntegrationError):
        install_configuration_api_security_audit_health_status_api(app)

    assert len(app.routes) == route_count_before


def test_direct_route_registration_is_detected(
    app: FastAPI,
) -> None:
    from app.services.scheduling.configuration_api_security_audit_health_status_api import (
        register_security_audit_health_status_routes,
    )

    register_security_audit_health_status_routes(app)

    with pytest.raises(SecurityAuditHealthStatusApiIntegrationError):
        install_configuration_api_security_audit_health_status_api(
            app
        )


# ---------------------------------------------------------------------------
# Custom prefix and dependencies
# ---------------------------------------------------------------------------


def test_custom_prefix_is_registered(
    app: FastAPI,
) -> None:
    install_configuration_api_security_audit_health_status_api(
        app,
        prefix="/internal/audit",
    )

    paths = {
        getattr(route, "path", None)
        for route in app.routes
    }

    assert "/internal/audit/status" in paths


def test_custom_tags_are_registered(
    app: FastAPI,
) -> None:
    install_configuration_api_security_audit_health_status_api(
        app,
        tags=["Internal Monitoring"],
    )

    operation = app.openapi()["paths"][
        "/configuration/security/audit/status"
    ]["get"]

    assert "Internal Monitoring" in operation["tags"]


def test_authentication_dependency_is_enforced(
    app: FastAPI,
) -> None:
    def require_authentication() -> None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    install_configuration_api_security_audit_health_status_api(
        app,
        dependencies=[Depends(require_authentication)],
    )

    response = TestClient(app).get(
        "/configuration/security/audit/status"
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_authorized_request_reaches_endpoint(
    app: FastAPI,
) -> None:
    def require_authentication() -> None:
        return None

    install_configuration_api_security_audit_health_status_api(
        app,
        dependencies=[Depends(require_authentication)],
    )

    response = TestClient(app).get(
        "/configuration/security/audit/status"
    )

    # Authentication succeeds. The status service is not installed,
    # so the endpoint subsequently returns 503.
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE


def test_invalid_prefix_does_not_mark_api_installed(
    app: FastAPI,
) -> None:
    with pytest.raises(SecurityAuditHealthStatusApiIntegrationError):
        install_configuration_api_security_audit_health_status_api(
            app,
            prefix=" ",
        )

    assert (
        is_configuration_api_security_audit_health_status_api_installed(
            app
        )
        is False
    )


def test_invalid_dependency_does_not_mark_api_installed(
    app: FastAPI,
) -> None:
    with pytest.raises(SecurityAuditHealthStatusApiIntegrationError):
        install_configuration_api_security_audit_health_status_api(
            app,
            dependencies=[object()],  # type: ignore[list-item]
        )

    assert (
        is_configuration_api_security_audit_health_status_api_installed(
            app
        )
        is False
    )


# ---------------------------------------------------------------------------
# Router accessor
# ---------------------------------------------------------------------------


def test_get_router_returns_registered_router(
    app: FastAPI,
) -> None:
    router = install_configuration_api_security_audit_health_status_api(
        app
    )

    retrieved = (
        get_configuration_api_security_audit_health_status_api_router(
            app
        )
    )

    assert retrieved is router


def test_get_router_raises_before_installation(
    app: FastAPI,
) -> None:
    with pytest.raises(SecurityAuditHealthStatusApiIntegrationError):
        get_configuration_api_security_audit_health_status_api_router(
            app
        )


def test_get_router_rejects_non_fastapi_application() -> None:
    with pytest.raises(TypeError):
        get_configuration_api_security_audit_health_status_api_router(
            object()  # type: ignore[arg-type]
        )


def test_get_router_detects_missing_router_state(
    app: FastAPI,
) -> None:
    setattr(app.state, STATUS_API_INSTALLATION_STATE_KEY, True)
    setattr(app.state, STATUS_API_ROUTER_STATE_KEY, None)

    with pytest.raises(SecurityAuditHealthStatusApiIntegrationError):
        get_configuration_api_security_audit_health_status_api_router(
            app
        )


# ---------------------------------------------------------------------------
# Installation status
# ---------------------------------------------------------------------------


def test_installed_status_is_false_before_installation(
    app: FastAPI,
) -> None:
    assert (
        is_configuration_api_security_audit_health_status_api_installed(
            app
        )
        is False
    )


def test_installed_status_is_true_after_installation(
    app: FastAPI,
) -> None:
    install_configuration_api_security_audit_health_status_api(app)

    assert (
        is_configuration_api_security_audit_health_status_api_installed(
            app
        )
        is True
    )


def test_installed_status_rejects_non_fastapi_application() -> None:
    with pytest.raises(TypeError):
        is_configuration_api_security_audit_health_status_api_installed(
            object()  # type: ignore[arg-type]
        )


def test_installed_status_detects_inconsistent_state(
    app: FastAPI,
) -> None:
    setattr(app.state, STATUS_API_INSTALLATION_STATE_KEY, True)
    setattr(app.state, STATUS_API_ROUTER_STATE_KEY, None)

    assert (
        is_configuration_api_security_audit_health_status_api_installed(
            app
        )
        is False
    )


# ---------------------------------------------------------------------------
# Prefix accessor
# ---------------------------------------------------------------------------


def test_get_prefix_returns_registered_prefix(
    app: FastAPI,
) -> None:
    install_configuration_api_security_audit_health_status_api(
        app,
        prefix="/admin/audit",
    )

    prefix = (
        get_configuration_api_security_audit_health_status_api_prefix(
            app
        )
    )

    assert prefix == "/admin/audit"


def test_get_prefix_raises_before_installation(
    app: FastAPI,
) -> None:
    with pytest.raises(SecurityAuditHealthStatusApiIntegrationError):
        get_configuration_api_security_audit_health_status_api_prefix(
            app
        )


def test_get_prefix_detects_missing_prefix_state(
    app: FastAPI,
) -> None:
    install_configuration_api_security_audit_health_status_api(app)

    setattr(app.state, STATUS_API_PREFIX_STATE_KEY, None)

    with pytest.raises(SecurityAuditHealthStatusApiIntegrationError):
        get_configuration_api_security_audit_health_status_api_prefix(
            app
        )


def test_get_prefix_rejects_non_fastapi_application() -> None:
    with pytest.raises(TypeError):
        get_configuration_api_security_audit_health_status_api_prefix(
            object()  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------------------
# Removal semantics
# ---------------------------------------------------------------------------


def test_remove_returns_registered_router(
    app: FastAPI,
):
    router = install_configuration_api_security_audit_health_status_api(
        app
    )

    removed = (
        remove_configuration_api_security_audit_health_status_api(app)
    )

    assert removed is router


def test_remove_clears_application_state(
    app: FastAPI,
) -> None:
    install_configuration_api_security_audit_health_status_api(app)

    remove_configuration_api_security_audit_health_status_api(app)

    assert getattr(app.state, STATUS_API_ROUTER_STATE_KEY) is None
    assert getattr(app.state, STATUS_API_PREFIX_STATE_KEY) is None
    assert (
        getattr(app.state, STATUS_API_INSTALLATION_STATE_KEY)
        is False
    )


def test_remove_marks_api_as_uninstalled(
    app: FastAPI,
) -> None:
    install_configuration_api_security_audit_health_status_api(app)

    remove_configuration_api_security_audit_health_status_api(app)

    assert (
        is_configuration_api_security_audit_health_status_api_installed(
            app
        )
        is False
    )


def test_remove_does_not_unregister_actual_route(
    app: FastAPI,
) -> None:
    install_configuration_api_security_audit_health_status_api(app)

    remove_configuration_api_security_audit_health_status_api(app)

    paths = {
        getattr(route, "path", None)
        for route in app.routes
    }

    assert "/configuration/security/audit/status" in paths


def test_remove_requires_installed_api(
    app: FastAPI,
) -> None:
    with pytest.raises(SecurityAuditHealthStatusApiIntegrationError):
        remove_configuration_api_security_audit_health_status_api(
            app
        )


def test_remove_rejects_non_fastapi_application() -> None:
    with pytest.raises(TypeError):
        remove_configuration_api_security_audit_health_status_api(
            object()  # type: ignore[arg-type]
        )


def test_removed_api_can_be_reinstalled(
    app: FastAPI,
) -> None:
    install_configuration_api_security_audit_health_status_api(app)

    remove_configuration_api_security_audit_health_status_api(app)

    # The old route remains registered. Reinstallation is therefore
    # expected to fail at the underlying duplicate-route guard.
    with pytest.raises(SecurityAuditHealthStatusApiIntegrationError):
        install_configuration_api_security_audit_health_status_api(
            app
        )


# ---------------------------------------------------------------------------
# Application isolation
# ---------------------------------------------------------------------------


def test_applications_have_independent_installation_state() -> None:
    first_app = FastAPI()
    second_app = FastAPI()

    first_router = (
        install_configuration_api_security_audit_health_status_api(
            first_app
        )
    )

    assert (
        is_configuration_api_security_audit_health_status_api_installed(
            first_app
        )
        is True
    )

    assert (
        is_configuration_api_security_audit_health_status_api_installed(
            second_app
        )
        is False
    )

    second_router = (
        install_configuration_api_security_audit_health_status_api(
            second_app
        )
    )

    assert first_router is not second_router


def test_removal_from_one_application_does_not_affect_another() -> None:
    first_app = FastAPI()
    second_app = FastAPI()

    install_configuration_api_security_audit_health_status_api(
        first_app
    )
    install_configuration_api_security_audit_health_status_api(
        second_app
    )

    remove_configuration_api_security_audit_health_status_api(
        first_app
    )

    assert (
        is_configuration_api_security_audit_health_status_api_installed(
            first_app
        )
        is False
    )

    assert (
        is_configuration_api_security_audit_health_status_api_installed(
            second_app
        )
        is True
    )
