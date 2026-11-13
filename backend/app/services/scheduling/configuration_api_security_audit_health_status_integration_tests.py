
"""Tests for consolidated security audit health integration."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi import FastAPI

from app.services.scheduling.configuration_api_security_audit_health_integration import (
    install_configuration_api_security_audit_health,
)
from app.services.scheduling.configuration_api_security_audit_health_api_integration import (
    install_configuration_api_security_audit_health_api,
)
from app.services.scheduling.configuration_api_security_audit_health_status import (
    SecurityAuditComponentStatus,
    SecurityAuditSubsystemHealth,
    SecurityAuditSubsystemStatus,
)
from app.services.scheduling.configuration_api_security_audit_health_status_integration import (
    HEALTH_STATUS_INSTALLATION_STATE_KEY,
    HEALTH_STATUS_STATE_KEY,
    SecurityAuditHealthStatusIntegrationError,
    check_configuration_api_security_audit_health_status,
    get_configuration_api_security_audit_health_status_dict,
    get_configuration_api_security_audit_health_status_snapshot,
    install_configuration_api_security_audit_health_status,
    is_configuration_api_security_audit_health_status_installed,
    remove_configuration_api_security_audit_health_status,
)


@pytest.fixture
def app() -> FastAPI:
    return FastAPI()


# ---------------------------------------------------------------------------
# Installation
# ---------------------------------------------------------------------------


def test_install_creates_initial_snapshot(
    app: FastAPI,
) -> None:
    snapshot = install_configuration_api_security_audit_health_status(
        app
    )

    assert isinstance(snapshot, SecurityAuditSubsystemHealth)
    assert snapshot.get_component("audit_logger") is not None
    assert snapshot.get_component("health_api") is not None


def test_install_stores_snapshot_in_application_state(
    app: FastAPI,
) -> None:
    snapshot = install_configuration_api_security_audit_health_status(
        app
    )

    assert getattr(app.state, HEALTH_STATUS_STATE_KEY) is snapshot
    assert (
        getattr(app.state, HEALTH_STATUS_INSTALLATION_STATE_KEY)
        is True
    )


def test_install_rejects_non_fastapi_application() -> None:
    with pytest.raises(TypeError):
        install_configuration_api_security_audit_health_status(
            object()  # type: ignore[arg-type]
        )


def test_duplicate_installation_is_rejected(
    app: FastAPI,
) -> None:
    first = install_configuration_api_security_audit_health_status(
        app
    )

    with pytest.raises(SecurityAuditHealthStatusIntegrationError):
        install_configuration_api_security_audit_health_status(app)

    assert (
        get_configuration_api_security_audit_health_status_snapshot(app)
        is first
    )


def test_installation_status_is_true_after_installation(
    app: FastAPI,
) -> None:
    install_configuration_api_security_audit_health_status(app)

    assert (
        is_configuration_api_security_audit_health_status_installed(app)
        is True
    )


def test_installation_status_is_false_before_installation(
    app: FastAPI,
) -> None:
    assert (
        is_configuration_api_security_audit_health_status_installed(app)
        is False
    )


def test_install_rejects_invalid_existing_state(
    app: FastAPI,
) -> None:
    setattr(app.state, HEALTH_STATUS_INSTALLATION_STATE_KEY, True)
    setattr(app.state, HEALTH_STATUS_STATE_KEY, object())

    assert (
        is_configuration_api_security_audit_health_status_installed(app)
        is False
    )

    with pytest.raises(SecurityAuditHealthStatusIntegrationError):
        install_configuration_api_security_audit_health_status(app)


# ---------------------------------------------------------------------------
# Initial snapshot semantics
# ---------------------------------------------------------------------------


def test_missing_audit_service_produces_unknown_component(
    app: FastAPI,
) -> None:
    snapshot = install_configuration_api_security_audit_health_status(
        app
    )

    component = snapshot.get_component("audit_logger")

    assert component is not None
    assert component.status is SecurityAuditComponentStatus.UNKNOWN


def test_missing_health_api_produces_uninstalled_component(
    app: FastAPI,
) -> None:
    snapshot = install_configuration_api_security_audit_health_status(
        app
    )

    component = snapshot.get_component("health_api")

    assert component is not None
    assert component.status is SecurityAuditComponentStatus.NOT_INSTALLED


def test_missing_audit_service_and_api_produce_unknown_overall_status(
    app: FastAPI,
) -> None:
    snapshot = install_configuration_api_security_audit_health_status(
        app
    )

    assert snapshot.status is SecurityAuditSubsystemStatus.UNKNOWN


def test_installed_health_api_is_reflected_in_snapshot(
    app: FastAPI,
) -> None:
    install_configuration_api_security_audit_health_api(app)

    snapshot = install_configuration_api_security_audit_health_status(
        app
    )

    component = snapshot.get_component("health_api")

    assert component is not None
    assert component.status is SecurityAuditComponentStatus.HEALTHY
    assert component.details["installed"] is True


def test_health_api_prefix_is_included_in_snapshot(
    app: FastAPI,
) -> None:
    install_configuration_api_security_audit_health_api(
        app,
        prefix="/internal/audit",
    )

    snapshot = install_configuration_api_security_audit_health_status(
        app
    )

    component = snapshot.get_component("health_api")

    assert component is not None
    assert component.details["prefix"] == "/internal/audit"


# ---------------------------------------------------------------------------
# Snapshot retrieval
# ---------------------------------------------------------------------------


def test_get_snapshot_returns_stored_snapshot(
    app: FastAPI,
) -> None:
    snapshot = install_configuration_api_security_audit_health_status(
        app
    )

    retrieved = (
        get_configuration_api_security_audit_health_status_snapshot(app)
    )

    assert retrieved is snapshot


def test_get_snapshot_rejects_uninstalled_integration(
    app: FastAPI,
) -> None:
    with pytest.raises(SecurityAuditHealthStatusIntegrationError):
        get_configuration_api_security_audit_health_status_snapshot(app)


def test_get_snapshot_rejects_invalid_application_state(
    app: FastAPI,
) -> None:
    setattr(app.state, HEALTH_STATUS_INSTALLATION_STATE_KEY, True)
    setattr(app.state, HEALTH_STATUS_STATE_KEY, object())

    with pytest.raises(SecurityAuditHealthStatusIntegrationError):
        get_configuration_api_security_audit_health_status_snapshot(app)


def test_get_snapshot_rejects_non_fastapi_application() -> None:
    with pytest.raises(TypeError):
        get_configuration_api_security_audit_health_status_snapshot(
            object()  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------------------
# Refreshing the health snapshot
# ---------------------------------------------------------------------------


def test_check_refreshes_snapshot(
    app: FastAPI,
) -> None:
    initial = install_configuration_api_security_audit_health_status(
        app
    )

    refreshed = check_configuration_api_security_audit_health_status(
        app
    )

    assert isinstance(refreshed, SecurityAuditSubsystemHealth)
    assert refreshed is not initial
    assert (
        get_configuration_api_security_audit_health_status_snapshot(app)
        is refreshed
    )


def test_check_uses_supplied_timestamp(
    app: FastAPI,
) -> None:
    install_configuration_api_security_audit_health_status(app)

    timestamp = datetime(
        2026, 11, 13, 10, 30, tzinfo=timezone.utc
    )

    refreshed = check_configuration_api_security_audit_health_status(
        app,
        checked_at=timestamp,
    )

    assert refreshed.checked_at == timestamp


def test_check_rejects_naive_timestamp(
    app: FastAPI,
) -> None:
    install_configuration_api_security_audit_health_status(app)

    with pytest.raises(SecurityAuditHealthStatusIntegrationError):
        check_configuration_api_security_audit_health_status(
            app,
            checked_at=datetime(2026, 11, 13, 10, 30),
        )


def test_check_rejects_non_datetime_timestamp(
    app: FastAPI,
) -> None:
    install_configuration_api_security_audit_health_status(app)

    with pytest.raises(SecurityAuditHealthStatusIntegrationError):
        check_configuration_api_security_audit_health_status(
            app,
            checked_at="2026-11-13",  # type: ignore[arg-type]
        )


def test_check_requires_installed_integration(
    app: FastAPI,
) -> None:
    with pytest.raises(SecurityAuditHealthStatusIntegrationError):
        check_configuration_api_security_audit_health_status(app)


def test_check_rejects_non_fastapi_application() -> None:
    with pytest.raises(TypeError):
        check_configuration_api_security_audit_health_status(
            object()  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------------------
# Dictionary representation
# ---------------------------------------------------------------------------


def test_get_dict_refreshes_by_default(
    app: FastAPI,
) -> None:
    install_configuration_api_security_audit_health_status(app)

    result = get_configuration_api_security_audit_health_status_dict(
        app
    )

    assert isinstance(result, dict)
    assert result["status"] == "unknown"
    assert result["healthy"] is False
    assert isinstance(result["components"], list)


def test_get_dict_can_return_cached_snapshot(
    app: FastAPI,
) -> None:
    initial = install_configuration_api_security_audit_health_status(
        app
    )

    result = get_configuration_api_security_audit_health_status_dict(
        app,
        refresh=False,
    )

    assert result == initial.to_dict()


def test_get_dict_refresh_flag_must_be_boolean(
    app: FastAPI,
) -> None:
    install_configuration_api_security_audit_health_status(app)

    with pytest.raises(TypeError):
        get_configuration_api_security_audit_health_status_dict(
            app,
            refresh=1,  # type: ignore[arg-type]
        )


def test_get_dict_requires_installed_integration(
    app: FastAPI,
) -> None:
    with pytest.raises(SecurityAuditHealthStatusIntegrationError):
        get_configuration_api_security_audit_health_status_dict(app)


def test_get_dict_rejects_non_fastapi_application() -> None:
    with pytest.raises(TypeError):
        get_configuration_api_security_audit_health_status_dict(
            object()  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------------------
# Removal
# ---------------------------------------------------------------------------


def test_remove_returns_last_snapshot(
    app: FastAPI,
) -> None:
    snapshot = install_configuration_api_security_audit_health_status(
        app
    )

    removed = (
        remove_configuration_api_security_audit_health_status(app)
    )

    assert removed is snapshot


def test_remove_clears_application_state(
    app: FastAPI,
) -> None:
    install_configuration_api_security_audit_health_status(app)

    remove_configuration_api_security_audit_health_status(app)

    assert getattr(app.state, HEALTH_STATUS_STATE_KEY) is None
    assert (
        getattr(app.state, HEALTH_STATUS_INSTALLATION_STATE_KEY)
        is False
    )
    assert (
        is_configuration_api_security_audit_health_status_installed(app)
        is False
    )


def test_remove_requires_installed_integration(
    app: FastAPI,
) -> None:
    with pytest.raises(SecurityAuditHealthStatusIntegrationError):
        remove_configuration_api_security_audit_health_status(app)


def test_remove_rejects_non_fastapi_application() -> None:
    with pytest.raises(TypeError):
        remove_configuration_api_security_audit_health_status(
            object()  # type: ignore[arg-type]
        )


def test_removed_integration_can_be_reinstalled(
    app: FastAPI,
) -> None:
    first = install_configuration_api_security_audit_health_status(
        app
    )

    remove_configuration_api_security_audit_health_status(app)

    second = install_configuration_api_security_audit_health_status(
        app
    )

    assert first is not second
    assert (
        get_configuration_api_security_audit_health_status_snapshot(app)
        is second
    )


# ---------------------------------------------------------------------------
# Application isolation
# ---------------------------------------------------------------------------


def test_health_status_is_isolated_between_applications() -> None:
    first_app = FastAPI()
    second_app = FastAPI()

    first_snapshot = (
        install_configuration_api_security_audit_health_status(
            first_app
        )
    )

    assert (
        is_configuration_api_security_audit_health_status_installed(
            first_app
        )
        is True
    )
    assert (
        is_configuration_api_security_audit_health_status_installed(
            second_app
        )
        is False
    )

    second_snapshot = (
        install_configuration_api_security_audit_health_status(
            second_app
        )
    )

    assert first_snapshot is not second_snapshot


def test_removal_from_one_application_does_not_affect_another() -> None:
    first_app = FastAPI()
    second_app = FastAPI()

    install_configuration_api_security_audit_health_status(first_app)
    install_configuration_api_security_audit_health_status(second_app)

    remove_configuration_api_security_audit_health_status(first_app)

    assert (
        is_configuration_api_security_audit_health_status_installed(
            first_app
        )
        is False
    )
    assert (
        is_configuration_api_security_audit_health_status_installed(
            second_app
        )
        is True
    )
