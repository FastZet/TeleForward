
"""Integration tests for the security audit health API."""

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
from app.services.scheduling.configuration_api_security_audit_health_api_integration import (
    HEALTH_API_INSTALLATION_STATE_KEY,
    HEALTH_API_PREFIX_STATE_KEY,
    HEALTH_API_ROUTER_STATE_KEY,
    SecurityAuditHealthApiIntegrationError,
    get_configuration_api_security_audit_health_api_prefix,
    get_configuration_api_security_audit_health_api_router,
    install_configuration_api_security_audit_health_api,
    is_configuration_api_security_audit_health_api_installed,
    remove_configuration_api_security_audit_health_api,
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
    install_configuration_api_security_audit_health_api(app)
    return app


# ---------------------------------------------------------------------------
# Installation
# ---------------------------------------------------------------------------


def test_install_registers_router(
    app: FastAPI,
) -> None:
    from fastapi import APIRouter

    router = install_configuration_api_security_audit_health_api(app)

    assert isinstance(router, APIRouter)
    assert (
        getattr(app.state, HEALTH_API_ROUTER_STATE_KEY)
        is router
    )


def test_install_sets_application_state(
    app: FastAPI,
) -> None:
    install_configuration_api_security_audit_health_api(app)

    assert (
        getattr(app.state, HEALTH_API_INSTALLATION_STATE_KEY)
        is True
    )


def test_install_stores_normalized_prefix(
    app: FastAPI,
) -> None:
    install_configuration_api_security_audit_health_api(
        app,
        prefix="internal/audit/",
    )

    assert (
        getattr(app.state, HEALTH_API_PREFIX_STATE_KEY)
        == "/internal/audit"
    )


def test_install_rejects_non_fastapi_application() -> None:
    with pytest.raises(TypeError):
        install_configuration_api_security_audit_health_api(
            object(),  # type: ignore[arg-type]
        )


def test_install_does_not_require_health_service(
    app: FastAPI,
) -> None:
    install_configuration_api_security_audit_health_api(app)

    assert (
        is_configuration_api_security_audit_health_api_installed(app)
        is True
    )

    # The API can be registered independently. A request will return
    # HTTP 503 until the health service itself is installed.


def test_install_without_health_service_returns_503(
    app: FastAPI,
) -> None:
    install_configuration_api_security_audit_health_api(app)

    client = TestClient(app)

    response = client.get(
        "/configuration/security/audit/health"
    )

    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE


# ---------------------------------------------------------------------------
# Duplicate installation
# ---------------------------------------------------------------------------


def test_duplicate_installation_is_rejected(
    app: FastAPI,
) -> None:
    first = install_configuration_api_security_audit_health_api(app)

    with pytest.raises(SecurityAuditHealthApiIntegrationError):
        install_configuration_api_security_audit_health_api(app)

    assert (
        get_configuration_api_security_audit_health_api_router(app)
        is first
    )


def test_duplicate_installation_does_not_add_routes(
    app: FastAPI,
) -> None:
    install_configuration_api_security_audit_health_api(app)

    route_count_before = len(app.routes)

    with pytest.raises(SecurityAuditHealthApiIntegrationError):
        install_configuration_api_security_audit_health_api(app)

    assert len(app.routes) == route_count_before


def test_direct_registration_is_detected(
    app: FastAPI,
) -> None:
    from app.services.scheduling.configuration_api_security_audit_health_api import (
        register_security_audit_health_routes,
    )

    register_security_audit_health_routes(app)

    with pytest.raises(SecurityAuditHealthApiIntegrationError):
        install_configuration_api_security_audit_health_api(app)


# ---------------------------------------------------------------------------
# Dependencies and custom configuration
# ---------------------------------------------------------------------------


def test_install_passes_authentication_dependencies(
    app: FastAPI,
    audit_logger: SecurityAuditLogger,
) -> None:
    install_configuration_api_security_audit_health(
        app,
        audit_logger=audit_logger,
    )

    def require_authentication() -> None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    install_configuration_api_security_audit_health_api(
        app,
        dependencies=[Depends(require_authentication)],
    )

    response = TestClient(app).get(
        "/configuration/security/audit/health"
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_install_passes_custom_prefix(
    app: FastAPI,
) -> None:
    install_configuration_api_security_audit_health_api(
        app,
        prefix="/internal/security/audit",
    )

    response = TestClient(app).get(
        "/internal/security/audit/health"
    )

    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE


def test_install_passes_custom_tags(
    app: FastAPI,
) -> None:
    install_configuration_api_security_audit_health_api(
        app,
        tags=["Internal Security"],
    )

    schema = app.openapi()

    operation = schema["paths"][
        "/configuration/security/audit/health"
    ]["get"]

    assert "Internal Security" in operation["tags"]


def test_invalid_prefix_does_not_mark_api_installed(
    app: FastAPI,
) -> None:
    with pytest.raises(SecurityAuditHealthApiIntegrationError):
        install_configuration_api_security_audit_health_api(
            app,
            prefix=" ",
        )

    assert (
        is_configuration_api_security_audit_health_api_installed(app)
        is False
    )


def test_invalid_dependencies_do_not_mark_api_installed(
    app: FastAPI,
) -> None:
    with pytest.raises(SecurityAuditHealthApiIntegrationError):
        install_configuration_api_security_audit_health_api(
            app,
            dependencies=[object()],  # type: ignore[list-item]
        )

    assert (
        is_configuration_api_security_audit_health_api_installed(app)
        is False
    )


# ---------------------------------------------------------------------------
# Accessors
# ---------------------------------------------------------------------------


def test_get_router_returns_registered_router(
    app: FastAPI,
) -> None:
    router = install_configuration_api_security_audit_health_api(app)

    assert (
        get_configuration_api_security_audit_health_api_router(app)
        is router
    )


def test_get_router_raises_before_installation(
    app: FastAPI,
) -> None:
    with pytest.raises(SecurityAuditHealthApiIntegrationError):
        get_configuration_api_security_audit_health_api_router(app)


def test_get_prefix_returns_registered_prefix(
    app: FastAPI,
) -> None:
    install_configuration_api_security_audit_health_api(
        app,
        prefix="/admin/audit",
    )

    assert (
        get_configuration_api_security_audit_health_api_prefix(app)
        == "/admin/audit"
    )


def test_get_prefix_raises_before_installation(
    app: FastAPI,
) -> None:
    with pytest.raises(SecurityAuditHealthApiIntegrationError):
        get_configuration_api_security_audit_health_api_prefix(app)


def test_installed_status_is_false_before_installation(
    app: FastAPI,
) -> None:
    assert (
        is_configuration_api_security_audit_health_api_installed(app)
        is False
    )


def test_installed_status_is_true_after_installation(
    app: FastAPI,
) -> None:
    install_configuration_api_security_audit_health_api(app)

    assert (
        is_configuration_api_security_audit_health_api_installed(app)
        is True
    )


def test_installed_status_rejects_non_fastapi_application() -> None:
    with pytest.raises(TypeError):
        is_configuration_api_security_audit_health_api_installed(
            object()  # type: ignore[arg-type]
        )


def test_get_router_rejects_non_fastapi_application() -> None:
    with pytest.raises(TypeError):
        get_configuration_api_security_audit_health_api_router(
            object()  # type: ignore[arg-type]
        )


def test_get_prefix_rejects_non_fastapi_application() -> None:
    with pytest.raises(TypeError):
        get_configuration_api_security_audit_health_api_prefix(
            object()  # type: ignore[arg-type]
        )


def test_invalid_router_state_is_detected(
    app: FastAPI,
) -> None:
    setattr(app.state, HEALTH_API_INSTALLATION_STATE_KEY, True)
    setattr(app.state, HEALTH_API_ROUTER_STATE_KEY, None)

    assert (
        is_configuration_api_security_audit_health_api_installed(app)
        is False
    )

    with pytest.raises(SecurityAuditHealthApiIntegrationError):
        get_configuration_api_security_audit_health_api_router(app)


# ---------------------------------------------------------------------------
# Removal semantics
# ---------------------------------------------------------------------------


def test_remove_clears_integration_state(
    app: FastAPI,
) -> None:
    router = install_configuration_api_security_audit_health_api(app)

    removed = remove_configuration_api_security_audit_health_api(app)

    assert removed is router
    assert (
        is_configuration_api_security_audit_health_api_installed(app)
        is False
    )
    assert getattr(app.state, HEALTH_API_ROUTER_STATE_KEY) is None
    assert getattr(app.state, HEALTH_API_INSTALLATION_STATE_KEY) is False
    assert getattr(app.state, HEALTH_API_PREFIX_STATE_KEY) is None


def test_remove_does_not_remove_registered_route(
    app: FastAPI,
) -> None:
    install_configuration_api_security_audit_health_api(app)

    remove_configuration_api_security_audit_health_api(app)

    response = TestClient(app).get(
        "/configuration/security/audit/health"
    )

    # The health service is absent, but the route remains registered.
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE


def test_remove_requires_installed_api(
    app: FastAPI,
) -> None:
    with pytest.raises(SecurityAuditHealthApiIntegrationError):
        remove_configuration_api_security_audit_health_api(app)


def test_remove_rejects_non_fastapi_application() -> None:
    with pytest.raises(TypeError):
        remove_configuration_api_security_audit_health_api(
            object()  # type: ignore[arg-type]
        )


def test_remove_does_not_close_audit_logger(
    app: FastAPI,
    audit_logger: SecurityAuditLogger,
) -> None:
    install_configuration_api_security_audit_health(
        app,
        audit_logger=audit_logger,
    )
    install_configuration_api_security_audit_health_api(app)

    remove_configuration_api_security_audit_health_api(app)

    # The logger remains independently usable.
    from app.services.scheduling.configuration_api_security_audit import (
        SecurityAuditEventType,
    )

    event = audit_logger.record_event(
        SecurityAuditEventType.REQUEST_REJECTED,
        reason="logger_remains_open",
    )

    assert event.event_type is SecurityAuditEventType.REQUEST_REJECTED


# ---------------------------------------------------------------------------
# Application isolation
# ---------------------------------------------------------------------------


def test_applications_have_independent_installation_state() -> None:
    first_app = FastAPI()
    second_app = FastAPI()

    first_router = install_configuration_api_security_audit_health_api(
        first_app
    )

    assert (
        is_configuration_api_security_audit_health_api_installed(first_app)
        is True
    )
    assert (
        is_configuration_api_security_audit_health_api_installed(second_app)
        is False
    )

    second_router = install_configuration_api_security_audit_health_api(
        second_app
    )

    assert first_router is not second_router


def test_removing_one_application_does_not_affect_another() -> None:
    first_app = FastAPI()
    second_app = FastAPI()

    install_configuration_api_security_audit_health_api(first_app)
    install_configuration_api_security_audit_health_api(second_app)

    remove_configuration_api_security_audit_health_api(first_app)

    assert (
        is_configuration_api_security_audit_health_api_installed(first_app)
        is False
    )
    assert (
        is_configuration_api_security_audit_health_api_installed(second_app)
        is True
    )
