
"""Tests for configuration API security routes integration."""

from __future__ import annotations

import pytest

from fastapi import APIRouter, FastAPI, Request

from app.services.scheduling.configuration_api_security import (
    ConfigurationApiSecurity,
)
from app.services.scheduling.configuration_api_security_integration import (
    install_configuration_api_security,
)
from app.services.scheduling.configuration_api_security_routes_integration import (
    ROUTES_INSTALLED_STATE_KEY,
    ROUTES_PREFIX_STATE_KEY,
    are_configuration_api_security_routes_installed,
    get_configuration_api_security_routes_prefix,
    install_configuration_api_security_routes,
    install_configuration_api_security_routes_with_router,
)
from app.services.scheduling.configuration_permissions import (
    ConfigurationPermissionService,
    ConfigurationPrincipal,
)


def make_principal() -> ConfigurationPrincipal:
    """Create a minimal principal for integration tests."""

    principal = object.__new__(ConfigurationPrincipal)
    object.__setattr__(principal, "is_active", True)
    return principal


def make_security() -> ConfigurationApiSecurity:
    """Create a security instance for integration tests."""

    return object.__new__(ConfigurationApiSecurity)


def make_permission_service() -> ConfigurationPermissionService:
    """Create a permission service for integration tests."""

    return object.__new__(ConfigurationPermissionService)


def create_configured_app() -> FastAPI:
    """Create an application with configuration security installed."""

    app = FastAPI()

    async def resolver(
        request: Request,
    ) -> ConfigurationPrincipal:
        return make_principal()

    install_configuration_api_security(
        app,
        security=make_security(),
        principal_resolver=resolver,
    )

    return app


def test_rejects_non_fastapi_application() -> None:
    with pytest.raises(TypeError, match="FastAPI"):
        install_configuration_api_security_routes(
            object(),  # type: ignore[arg-type]
            permission_service=make_permission_service(),
        )


def test_rejects_invalid_permission_service() -> None:
    app = create_configured_app()

    with pytest.raises(
        TypeError,
        match="ConfigurationPermissionService",
    ):
        install_configuration_api_security_routes(
            app,
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
def test_rejects_invalid_prefix(prefix: str) -> None:
    app = create_configured_app()

    with pytest.raises(ValueError):
        install_configuration_api_security_routes(
            app,
            permission_service=make_permission_service(),
            prefix=prefix,
        )


def test_requires_security_to_be_installed() -> None:
    app = FastAPI()

    with pytest.raises(
        RuntimeError,
        match="security must be installed",
    ):
        install_configuration_api_security_routes(
            app,
            permission_service=make_permission_service(),
        )


def test_installs_security_routes() -> None:
    app = create_configured_app()

    router = install_configuration_api_security_routes(
        app,
        permission_service=make_permission_service(),
    )

    assert isinstance(router, APIRouter)
    assert are_configuration_api_security_routes_installed(app)
    assert (
        get_configuration_api_security_routes_prefix(app)
        == "/configuration/security"
    )


def test_installer_records_application_state() -> None:
    app = create_configured_app()

    install_configuration_api_security_routes(
        app,
        permission_service=make_permission_service(),
    )

    assert getattr(app.state, ROUTES_INSTALLED_STATE_KEY) is True
    assert (
        getattr(app.state, ROUTES_PREFIX_STATE_KEY)
        == "/configuration/security"
    )


def test_rejects_duplicate_installation() -> None:
    app = create_configured_app()

    install_configuration_api_security_routes(
        app,
        permission_service=make_permission_service(),
    )

    with pytest.raises(
        RuntimeError,
        match="already installed",
    ):
        install_configuration_api_security_routes(
            app,
            permission_service=make_permission_service(),
        )


def test_custom_prefix_is_recorded() -> None:
    app = create_configured_app()

    install_configuration_api_security_routes(
        app,
        permission_service=make_permission_service(),
        prefix="/internal/security/",
    )

    assert (
        get_configuration_api_security_routes_prefix(app)
        == "/internal/security"
    )


def test_uninstalled_state_returns_false() -> None:
    app = FastAPI()

    assert not are_configuration_api_security_routes_installed(app)


def test_uninstalled_prefix_returns_none() -> None:
    app = FastAPI()

    assert get_configuration_api_security_routes_prefix(app) is None


def test_state_accessors_reject_non_fastapi_application() -> None:
    with pytest.raises(TypeError):
        are_configuration_api_security_routes_installed(
            object()  # type: ignore[arg-type]
        )

    with pytest.raises(TypeError):
        get_configuration_api_security_routes_prefix(
            object()  # type: ignore[arg-type]
        )


def test_invalid_prefix_state_returns_none() -> None:
    app = FastAPI()
    setattr(app.state, ROUTES_PREFIX_STATE_KEY, 123)

    assert get_configuration_api_security_routes_prefix(app) is None


def test_preconstructed_router_installation() -> None:
    app = create_configured_app()
    router = APIRouter(prefix="/internal/security")

    @router.get("/health")
    async def health() -> dict[str, bool]:
        return {"healthy": True}

    install_configuration_api_security_routes_with_router(
        app,
        router=router,
        prefix="/internal/security",
    )

    assert are_configuration_api_security_routes_installed(app)
    assert (
        get_configuration_api_security_routes_prefix(app)
        == "/internal/security"
    )

    paths = {
        route.path
        for route in app.routes
    }

    assert "/internal/security/health" in paths


def test_preconstructed_router_rejects_invalid_application() -> None:
    with pytest.raises(TypeError, match="FastAPI"):
        install_configuration_api_security_routes_with_router(
            object(),  # type: ignore[arg-type]
            router=APIRouter(),
            prefix="/internal/security",
        )


def test_preconstructed_router_rejects_invalid_router() -> None:
    app = create_configured_app()

    with pytest.raises(TypeError, match="APIRouter"):
        install_configuration_api_security_routes_with_router(
            app,
            router=object(),  # type: ignore[arg-type]
            prefix="/internal/security",
        )


def test_preconstructed_router_requires_security() -> None:
    app = FastAPI()

    with pytest.raises(RuntimeError, match="security must be installed"):
        install_configuration_api_security_routes_with_router(
            app,
            router=APIRouter(),
            prefix="/internal/security",
        )


def test_preconstructed_router_rejects_duplicate_installation() -> None:
    app = create_configured_app()

    install_configuration_api_security_routes_with_router(
        app,
        router=APIRouter(),
        prefix="/internal/security",
    )

    with pytest.raises(RuntimeError, match="already installed"):
        install_configuration_api_security_routes_with_router(
            app,
            router=APIRouter(),
            prefix="/another/security",
        )


@pytest.mark.parametrize(
    "prefix",
    [
        "",
        "internal/security",
        "/",
    ],
)
def test_preconstructed_router_rejects_invalid_prefix(
    prefix: str,
) -> None:
    app = create_configured_app()

    with pytest.raises(ValueError):
        install_configuration_api_security_routes_with_router(
            app,
            router=APIRouter(),
            prefix=prefix,
        )


def test_preconstructed_router_records_normalized_prefix() -> None:
    app = create_configured_app()

    install_configuration_api_security_routes_with_router(
        app,
        router=APIRouter(),
        prefix="/internal/security/",
    )

    assert (
        get_configuration_api_security_routes_prefix(app)
        == "/internal/security"
    )
