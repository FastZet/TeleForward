
"""Tests for scheduling configuration API security diagnostic routes."""

from __future__ import annotations

from typing import Any

import pytest

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.services.scheduling.configuration_api_security import (
    ConfigurationApiSecurity,
)
from app.services.scheduling.configuration_api_security_integration import (
    install_configuration_api_security,
)
from app.services.scheduling.configuration_api_security_routes import (
    create_configuration_security_router,
)
from app.services.scheduling.configuration_permissions import (
    ConfigurationPermission,
    ConfigurationPermissionService,
    ConfigurationPrincipal,
)


def make_principal(
    *,
    active: bool = True,
) -> ConfigurationPrincipal:
    """Create a principal for route tests."""

    principal = object.__new__(ConfigurationPrincipal)
    object.__setattr__(principal, "is_active", active)
    return principal


def make_security() -> ConfigurationApiSecurity:
    """Create a security instance for isolated tests."""

    return object.__new__(ConfigurationApiSecurity)


def make_permission_service() -> ConfigurationPermissionService:
    """Create a permission service for isolated tests."""

    return object.__new__(ConfigurationPermissionService)


def create_test_app(
    *,
    principal: ConfigurationPrincipal | None = None,
    permissions: set[ConfigurationPermission] | None = None,
    prefix: str = "/configuration/security",
) -> FastAPI:
    """Create an application with installed security and diagnostic routes."""

    app = FastAPI()
    security = make_security()
    permission_service = make_permission_service()

    async def principal_resolver(
        request: Request,
    ) -> ConfigurationPrincipal | None:
        return principal

    def get_permissions(
        current_principal: ConfigurationPrincipal,
    ) -> set[ConfigurationPermission]:
        return permissions or set()

    permission_service.get_permissions = get_permissions  # type: ignore[method-assign]

    install_configuration_api_security(
        app,
        security=security,
        principal_resolver=principal_resolver,
    )

    app.include_router(
        create_configuration_security_router(
            permission_service=permission_service,
            prefix=prefix,
        )
    )

    return app


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch):
    """Provide an authenticated test client."""

    principal = make_principal()

    app = create_test_app(
        principal=principal,
        permissions={
            ConfigurationPermission.READ_CONFIGURATION,
        },
    )

    def validate_request(
        self: ConfigurationApiSecurity,
        *,
        principal: ConfigurationPrincipal,
        method: str,
        path: str,
    ) -> dict[str, bool]:
        return {"allowed": True}

    monkeypatch.setattr(
        ConfigurationApiSecurity,
        "validate_request",
        validate_request,
    )

    with TestClient(app) as test_client:
        yield test_client


def test_router_rejects_invalid_permission_service() -> None:
    with pytest.raises(
        TypeError,
        match="ConfigurationPermissionService",
    ):
        create_configuration_security_router(
            permission_service=object(),  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    "prefix",
    [
        "",
        "configuration/security",
        "/",
    ],
)
def test_router_rejects_invalid_prefix(prefix: str) -> None:
    with pytest.raises(ValueError):
        create_configuration_security_router(
            permission_service=make_permission_service(),
            prefix=prefix,
        )


def test_router_normalizes_trailing_slash() -> None:
    router = create_configuration_security_router(
        permission_service=make_permission_service(),
        prefix="/configuration/security/",
    )

    assert router.prefix == "/configuration/security"


def test_security_status_returns_authenticated_state(
    client: TestClient,
) -> None:
    response = client.get(
        "/configuration/security/status"
    )

    assert response.status_code == 200
    assert response.json() == {
        "configured": True,
        "principal_authenticated": True,
        "principal_active": True,
    }


def test_permissions_endpoint_returns_granted_permissions(
    client: TestClient,
) -> None:
    response = client.get(
        "/configuration/security/permissions"
    )

    assert response.status_code == 200

    payload = response.json()

    assert payload["active"] is True
    assert payload["permissions"] == [
        {
            "permission": (
                ConfigurationPermission.READ_CONFIGURATION.value
            ),
            "granted": True,
        }
    ]


def test_permissions_endpoint_returns_empty_permissions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_test_app(
        principal=make_principal(),
        permissions=set(),
    )

    monkeypatch.setattr(
        ConfigurationApiSecurity,
        "validate_request",
        lambda self, **kwargs: None,
    )

    with TestClient(app) as test_client:
        response = test_client.get(
            "/configuration/security/permissions"
        )

    assert response.status_code == 200
    assert response.json() == {
        "active": True,
        "permissions": [],
    }


def test_permissions_are_sorted_by_permission_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    granted_permissions = set(
        list(ConfigurationPermission)[:3]
    )

    app = create_test_app(
        principal=make_principal(),
        permissions=granted_permissions,
    )

    monkeypatch.setattr(
        ConfigurationApiSecurity,
        "validate_request",
        lambda self, **kwargs: None,
    )

    with TestClient(app) as test_client:
        response = test_client.get(
            "/configuration/security/permissions"
        )

    assert response.status_code == 200

    values = [
        item["permission"]
        for item in response.json()["permissions"]
    ]

    assert values == sorted(values)


def test_status_endpoint_rejects_missing_principal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_test_app(principal=None)

    monkeypatch.setattr(
        ConfigurationApiSecurity,
        "validate_request",
        lambda self, **kwargs: None,
    )

    with TestClient(app) as test_client:
        response = test_client.get(
            "/configuration/security/status"
        )

    assert response.status_code == 401


def test_status_endpoint_rejects_inactive_principal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_test_app(
        principal=make_principal(active=False)
    )

    monkeypatch.setattr(
        ConfigurationApiSecurity,
        "validate_request",
        lambda self, **kwargs: None,
    )

    with TestClient(app) as test_client:
        response = test_client.get(
            "/configuration/security/status"
        )

    assert response.status_code == 403


def test_permissions_endpoint_rejects_missing_principal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_test_app(principal=None)

    monkeypatch.setattr(
        ConfigurationApiSecurity,
        "validate_request",
        lambda self, **kwargs: None,
    )

    with TestClient(app) as test_client:
        response = test_client.get(
            "/configuration/security/permissions"
        )

    assert response.status_code == 401


def test_security_validation_rejection_is_preserved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_test_app(
        principal=make_principal()
    )

    def reject_request(
        self: ConfigurationApiSecurity,
        **kwargs: Any,
    ) -> None:
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded",
        )

    monkeypatch.setattr(
        ConfigurationApiSecurity,
        "validate_request",
        reject_request,
    )

    with TestClient(app) as test_client:
        response = test_client.get(
            "/configuration/security/status"
        )

    assert response.status_code == 429
    assert response.json()["detail"] == "Rate limit exceeded"


def test_permissions_endpoint_handles_service_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = FastAPI()
    principal = make_principal()
    permission_service = make_permission_service()

    def failing_get_permissions(
        current_principal: ConfigurationPrincipal,
    ) -> set[ConfigurationPermission]:
        raise RuntimeError("Permission backend unavailable")

    permission_service.get_permissions = failing_get_permissions  # type: ignore[method-assign]

    install_configuration_api_security(
        app,
        security=make_security(),
        principal_resolver=lambda request: principal,
    )

    app.include_router(
        create_configuration_security_router(
            permission_service=permission_service,
        )
    )

    monkeypatch.setattr(
        ConfigurationApiSecurity,
        "validate_request",
        lambda self, **kwargs: None,
    )

    with TestClient(app) as test_client:
        response = test_client.get(
            "/configuration/security/permissions"
        )

    assert response.status_code == 500
    assert response.json()["detail"] == (
        "Unable to inspect configuration permissions"
    )


def test_custom_router_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_test_app(
        principal=make_principal(),
        prefix="/api/internal/security",
    )

    monkeypatch.setattr(
        ConfigurationApiSecurity,
        "validate_request",
        lambda self, **kwargs: None,
    )

    with TestClient(app) as test_client:
        response = test_client.get(
            "/api/internal/security/status"
        )

    assert response.status_code == 200


def test_default_router_tag() -> None:
    router = create_configuration_security_router(
        permission_service=make_permission_service(),
    )

    assert router.tags == ["Configuration Security"]


def test_custom_router_tags() -> None:
    router = create_configuration_security_router(
        permission_service=make_permission_service(),
        tags=["Internal API", "Security"],
    )

    assert router.tags == ["Internal API", "Security"]


def test_openapi_contains_security_diagnostic_routes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_test_app(
        principal=make_principal()
    )

    monkeypatch.setattr(
        ConfigurationApiSecurity,
        "validate_request",
        lambda self, **kwargs: None,
    )

    with TestClient(app) as test_client:
        response = test_client.get("/openapi.json")

    assert response.status_code == 200

    paths = response.json()["paths"]

    assert "/configuration/security/status" in paths
    assert "/configuration/security/permissions" in paths
