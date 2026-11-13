
"""Integration tests for the security-audit health monitor API."""

from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI
from fastapi.routing import APIRouter

from app.services.scheduling.configuration_api_security_audit_health_status_monitor_api import (
    DEFAULT_MONITOR_API_PREFIX,
)
from app.services.scheduling.configuration_api_security_audit_health_status_monitor_api_integration import (
    MONITOR_API_INSTALLED_STATE_KEY,
    MONITOR_API_PREFIX_STATE_KEY,
    MONITOR_API_ROUTER_STATE_KEY,
    SecurityAuditHealthStatusMonitorApiIntegrationError,
    get_configuration_api_security_audit_health_status_monitor_api_prefix,
    get_configuration_api_security_audit_health_status_monitor_api_router,
    install_configuration_api_security_audit_health_status_monitor_api,
    is_configuration_api_security_audit_health_status_monitor_api_installed,
    remove_configuration_api_security_audit_health_status_monitor_api,
)


@pytest.fixture
def app() -> FastAPI:
    return FastAPI()


# ---------------------------------------------------------------------------
# Installation
# ---------------------------------------------------------------------------


def test_install_registers_router(app: FastAPI) -> None:
    router = (
        install_configuration_api_security_audit_health_status_monitor_api(
            app
        )
    )

    assert isinstance(router, APIRouter)
    assert (
        getattr(app.state, MONITOR_API_ROUTER_STATE_KEY)
        is router
    )


def test_install_sets_installed_state(app: FastAPI) -> None:
    install_configuration_api_security_audit_health_status_monitor_api(
        app
    )

    assert (
        getattr(app.state, MONITOR_API_INSTALLED_STATE_KEY)
        is True
    )


def test_install_stores_default_prefix(app: FastAPI) -> None:
    install_configuration_api_security_audit_health_status_monitor_api(
        app
    )

    assert (
        getattr(app.state, MONITOR_API_PREFIX_STATE_KEY)
        == DEFAULT_MONITOR_API_PREFIX
    )


def test_install_stores_custom_prefix(app: FastAPI) -> None:
    install_configuration_api_security_audit_health_status_monitor_api(
        app,
        prefix="/internal/audit-monitor",
    )

    assert (
        getattr(app.state, MONITOR_API_PREFIX_STATE_KEY)
        == "/internal/audit-monitor"
    )


def test_install_rejects_non_fastapi_application() -> None:
    with pytest.raises(TypeError):
        install_configuration_api_security_audit_health_status_monitor_api(
            object(),  # type: ignore[arg-type]
        )


def test_install_rejects_duplicate_installation(
    app: FastAPI,
) -> None:
    first = (
        install_configuration_api_security_audit_health_status_monitor_api(
            app
        )
    )

    with pytest.raises(
        SecurityAuditHealthStatusMonitorApiIntegrationError
    ):
        install_configuration_api_security_audit_health_status_monitor_api(
            app
        )

    assert (
        get_configuration_api_security_audit_health_status_monitor_api_router(
            app
        )
        is first
    )


def test_install_rejects_unregistered_existing_router_state(
    app: FastAPI,
) -> None:
    existing_router = APIRouter()

    setattr(
        app.state,
        MONITOR_API_ROUTER_STATE_KEY,
        existing_router,
    )

    with pytest.raises(
        SecurityAuditHealthStatusMonitorApiIntegrationError
    ):
        install_configuration_api_security_audit_health_status_monitor_api(
            app
        )


def test_failed_installation_does_not_mark_api_installed(
    app: FastAPI,
) -> None:
    with pytest.raises(
        SecurityAuditHealthStatusMonitorApiIntegrationError
    ):
        install_configuration_api_security_audit_health_status_monitor_api(
            app,
            dependencies=[object()],  # type: ignore[list-item]
        )

    assert (
        is_configuration_api_security_audit_health_status_monitor_api_installed(
            app
        )
        is False
    )


# ---------------------------------------------------------------------------
# Dependency validation
# ---------------------------------------------------------------------------


def test_install_accepts_fastapi_dependency(
    app: FastAPI,
) -> None:
    def authenticate() -> None:
        return None

    router = (
        install_configuration_api_security_audit_health_status_monitor_api(
            app,
            dependencies=[Depends(authenticate)],
        )
    )

    assert isinstance(router, APIRouter)


def test_install_rejects_invalid_dependency(
    app: FastAPI,
) -> None:
    with pytest.raises(
        SecurityAuditHealthStatusMonitorApiIntegrationError
    ):
        install_configuration_api_security_audit_health_status_monitor_api(
            app,
            dependencies=[object()],  # type: ignore[list-item]
        )

    assert (
        is_configuration_api_security_audit_health_status_monitor_api_installed(
            app
        )
        is False
    )


def test_install_rejects_string_as_dependency_sequence(
    app: FastAPI,
) -> None:
    with pytest.raises(
        SecurityAuditHealthStatusMonitorApiIntegrationError
    ):
        install_configuration_api_security_audit_health_status_monitor_api(
            app,
            dependencies="invalid",  # type: ignore[arg-type]
        )


def test_installed_dependency_is_enforced(
    app: FastAPI,
) -> None:
    from fastapi import HTTPException
    from fastapi.testclient import TestClient

    def authenticate() -> None:
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
        )

    install_configuration_api_security_audit_health_status_monitor_api(
        app,
        dependencies=[Depends(authenticate)],
    )

    response = TestClient(app).get(
        f"{DEFAULT_MONITOR_API_PREFIX}/status"
    )

    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Tag validation
# ---------------------------------------------------------------------------


def test_install_accepts_custom_tags(
    app: FastAPI,
) -> None:
    router = (
        install_configuration_api_security_audit_health_status_monitor_api(
            app,
            tags=["Internal Monitoring"],
        )
    )

    assert "Internal Monitoring" in router.tags


def test_install_rejects_invalid_tags(
    app: FastAPI,
) -> None:
    with pytest.raises(
        SecurityAuditHealthStatusMonitorApiIntegrationError
    ):
        install_configuration_api_security_audit_health_status_monitor_api(
            app,
            tags=["Valid", ""],
        )

    assert (
        is_configuration_api_security_audit_health_status_monitor_api_installed(
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
    router = (
        install_configuration_api_security_audit_health_status_monitor_api(
            app
        )
    )

    retrieved = (
        get_configuration_api_security_audit_health_status_monitor_api_router(
            app
        )
    )

    assert retrieved is router


def test_get_router_rejects_uninstalled_api(
    app: FastAPI,
) -> None:
    with pytest.raises(
        SecurityAuditHealthStatusMonitorApiIntegrationError
    ):
        get_configuration_api_security_audit_health_status_monitor_api_router(
            app
        )


def test_get_router_detects_invalid_router_state(
    app: FastAPI,
) -> None:
    setattr(app.state, MONITOR_API_INSTALLED_STATE_KEY, True)
    setattr(app.state, MONITOR_API_ROUTER_STATE_KEY, object())

    with pytest.raises(
        SecurityAuditHealthStatusMonitorApiIntegrationError
    ):
        get_configuration_api_security_audit_health_status_monitor_api_router(
            app
        )


def test_get_router_rejects_non_fastapi_application() -> None:
    with pytest.raises(TypeError):
        get_configuration_api_security_audit_health_status_monitor_api_router(
            object()  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------------------
# Installation status
# ---------------------------------------------------------------------------


def test_installed_status_is_false_initially(
    app: FastAPI,
) -> None:
    assert (
        is_configuration_api_security_audit_health_status_monitor_api_installed(
            app
        )
        is False
    )


def test_installed_status_is_true_after_installation(
    app: FastAPI,
) -> None:
    install_configuration_api_security_audit_health_status_monitor_api(
        app
    )

    assert (
        is_configuration_api_security_audit_health_status_monitor_api_installed(
            app
        )
        is True
    )


def test_installed_status_detects_invalid_router_state(
    app: FastAPI,
) -> None:
    setattr(app.state, MONITOR_API_INSTALLED_STATE_KEY, True)
    setattr(app.state, MONITOR_API_ROUTER_STATE_KEY, None)

    assert (
        is_configuration_api_security_audit_health_status_monitor_api_installed(
            app
        )
        is False
    )


def test_installed_status_rejects_non_fastapi_application() -> None:
    with pytest.raises(TypeError):
        is_configuration_api_security_audit_health_status_monitor_api_installed(
            object()  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------------------
# Prefix accessor
# ---------------------------------------------------------------------------


def test_get_prefix_returns_default_prefix(
    app: FastAPI,
) -> None:
    install_configuration_api_security_audit_health_status_monitor_api(
        app
    )

    prefix = (
        get_configuration_api_security_audit_health_status_monitor_api_prefix(
            app
        )
    )

    assert prefix == DEFAULT_MONITOR_API_PREFIX


def test_get_prefix_returns_custom_prefix(
    app: FastAPI,
) -> None:
    install_configuration_api_security_audit_health_status_monitor_api(
        app,
        prefix="/internal/audit-monitor",
    )

    prefix = (
        get_configuration_api_security_audit_health_status_monitor_api_prefix(
            app
        )
    )

    assert prefix == "/internal/audit-monitor"


def test_get_prefix_rejects_uninstalled_api(
    app: FastAPI,
) -> None:
    with pytest.raises(
        SecurityAuditHealthStatusMonitorApiIntegrationError
    ):
        get_configuration_api_security_audit_health_status_monitor_api_prefix(
            app
        )


def test_get_prefix_detects_missing_prefix_state(
    app: FastAPI,
) -> None:
    install_configuration_api_security_audit_health_status_monitor_api(
        app
    )

    setattr(app.state, MONITOR_API_PREFIX_STATE_KEY, None)

    with pytest.raises(
        SecurityAuditHealthStatusMonitorApiIntegrationError
    ):
        get_configuration_api_security_audit_health_status_monitor_api_prefix(
            app
        )


def test_get_prefix_rejects_non_fastapi_application() -> None:
    with pytest.raises(TypeError):
        get_configuration_api_security_audit_health_status_monitor_api_prefix(
            object()  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------------------
# Actual route registration
# ---------------------------------------------------------------------------


def test_install_registers_all_expected_routes(
    app: FastAPI,
) -> None:
    install_configuration_api_security_audit_health_status_monitor_api(
        app
    )

    routes = {
        (
            getattr(route, "path", None),
            method,
        )
        for route in app.routes
        for method in getattr(route, "methods", set())
    }

    assert (
        f"{DEFAULT_MONITOR_API_PREFIX}/status",
        "GET",
    ) in routes

    assert (
        f"{DEFAULT_MONITOR_API_PREFIX}/history",
        "GET",
    ) in routes

    assert (
        f"{DEFAULT_MONITOR_API_PREFIX}/check",
        "POST",
    ) in routes


def test_custom_prefix_is_used_for_registered_routes(
    app: FastAPI,
) -> None:
    install_configuration_api_security_audit_health_status_monitor_api(
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


def test_installation_does_not_duplicate_routes(
    app: FastAPI,
) -> None:
    install_configuration_api_security_audit_health_status_monitor_api(
        app
    )

    route_count = len(app.routes)

    with pytest.raises(
        SecurityAuditHealthStatusMonitorApiIntegrationError
    ):
        install_configuration_api_security_audit_health_status_monitor_api(
            app
        )

    assert len(app.routes) == route_count


# ---------------------------------------------------------------------------
# Removal
# ---------------------------------------------------------------------------


def test_remove_returns_registered_router(
    app: FastAPI,
) -> None:
    router = (
        install_configuration_api_security_audit_health_status_monitor_api(
            app
        )
    )

    removed = (
        remove_configuration_api_security_audit_health_status_monitor_api(
            app
        )
    )

    assert removed is router


def test_remove_clears_router_state(
    app: FastAPI,
) -> None:
    install_configuration_api_security_audit_health_status_monitor_api(
        app
    )

    remove_configuration_api_security_audit_health_status_monitor_api(
        app
    )

    assert getattr(app.state, MONITOR_API_ROUTER_STATE_KEY) is None


def test_remove_clears_installed_state(
    app: FastAPI,
) -> None:
    install_configuration_api_security_audit_health_status_monitor_api(
        app
    )

    remove_configuration_api_security_audit_health_status_monitor_api(
        app
    )

    assert getattr(app.state, MONITOR_API_INSTALLED_STATE_KEY) is False


def test_remove_clears_prefix_state(
    app: FastAPI,
) -> None:
    install_configuration_api_security_audit_health_status_monitor_api(
        app
    )

    remove_configuration_api_security_audit_health_status_monitor_api(
        app
    )

    assert getattr(app.state, MONITOR_API_PREFIX_STATE_KEY) is None


def test_remove_marks_api_as_uninstalled(
    app: FastAPI,
) -> None:
    install_configuration_api_security_audit_health_status_monitor_api(
        app
    )

    remove_configuration_api_security_audit_health_status_monitor_api(
        app
    )

    assert (
        is_configuration_api_security_audit_health_status_monitor_api_installed(
            app
        )
        is False
    )


def test_remove_does_not_unregister_actual_routes(
    app: FastAPI,
) -> None:
    install_configuration_api_security_audit_health_status_monitor_api(
        app
    )

    remove_configuration_api_security_audit_health_status_monitor_api(
        app
    )

    paths = {
        getattr(route, "path", None)
        for route in app.routes
    }

    assert f"{DEFAULT_MONITOR_API_PREFIX}/status" in paths
    assert f"{DEFAULT_MONITOR_API_PREFIX}/history" in paths
    assert f"{DEFAULT_MONITOR_API_PREFIX}/check" in paths


def test_remove_rejects_uninstalled_api(
    app: FastAPI,
) -> None:
    with pytest.raises(
        SecurityAuditHealthStatusMonitorApiIntegrationError
    ):
        remove_configuration_api_security_audit_health_status_monitor_api(
            app
        )


def test_remove_rejects_non_fastapi_application() -> None:
    with pytest.raises(TypeError):
        remove_configuration_api_security_audit_health_status_monitor_api(
            object()  # type: ignore[arg-type]
        )


def test_reinstallation_after_removal_is_rejected(
    app: FastAPI,
) -> None:
    install_configuration_api_security_audit_health_status_monitor_api(
        app
    )

    remove_configuration_api_security_audit_health_status_monitor_api(
        app
    )

    with pytest.raises(
        SecurityAuditHealthStatusMonitorApiIntegrationError
    ):
        install_configuration_api_security_audit_health_status_monitor_api(
            app
        )


# ---------------------------------------------------------------------------
# Application isolation
# ---------------------------------------------------------------------------


def test_applications_have_independent_routers() -> None:
    first_app = FastAPI()
    second_app = FastAPI()

    first_router = (
        install_configuration_api_security_audit_health_status_monitor_api(
            first_app
        )
    )

    second_router = (
        install_configuration_api_security_audit_health_status_monitor_api(
            second_app
        )
    )

    assert first_router is not second_router


def test_removal_from_one_app_does_not_affect_another() -> None:
    first_app = FastAPI()
    second_app = FastAPI()

    install_configuration_api_security_audit_health_status_monitor_api(
        first_app
    )

    second_router = (
        install_configuration_api_security_audit_health_status_monitor_api(
            second_app
        )
    )

    remove_configuration_api_security_audit_health_status_monitor_api(
        first_app
    )

    assert (
        is_configuration_api_security_audit_health_status_monitor_api_installed(
            first_app
        )
        is False
    )

    assert (
        get_configuration_api_security_audit_health_status_monitor_api_router(
            second_app
        )
        is second_router
    )
