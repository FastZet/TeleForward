
"""Tests for scheduling configuration API security integration."""

from __future__ import annotations

from typing import Any

import pytest

from fastapi import FastAPI, HTTPException
from starlette.requests import Request

from app.services.scheduling.configuration_api_security import (
    ConfigurationApiSecurity,
)
from app.services.scheduling.configuration_api_security_integration import (
    PRINCIPAL_RESOLVER_STATE_KEY,
    SECURITY_STATE_KEY,
    get_configuration_api_security,
    get_configuration_principal_resolver,
    install_configuration_api_security,
    resolve_configuration_api_principal,
    validate_configuration_api_request,
)
from app.services.scheduling.configuration_permissions import (
    ConfigurationPrincipal,
)


def make_app() -> FastAPI:
    """Create a minimal FastAPI application."""

    return FastAPI()


def make_principal(
    *,
    active: bool = True,
) -> ConfigurationPrincipal:
    """Create a principal without depending on domain constructor details."""

    principal = object.__new__(ConfigurationPrincipal)
    object.__setattr__(principal, "is_active", active)

    return principal


def make_security() -> ConfigurationApiSecurity:
    """Create a security instance for tests without invoking its constructor."""

    return object.__new__(ConfigurationApiSecurity)


def make_request(
    app: FastAPI,
    *,
    path: str = "/api/v1/scheduling/configuration",
    method: str = "GET",
) -> Request:
    """Create a Starlette request associated with the test application."""

    scope = {
        "type": "http",
        "asgi": {
            "version": "3.0",
            "spec_version": "2.3",
        },
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("utf-8"),
        "query_string": b"",
        "root_path": "",
        "headers": [],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
        "app": app,
    }

    return Request(scope)


def install_test_security(
    app: FastAPI,
    *,
    principal: ConfigurationPrincipal | None = None,
) -> ConfigurationApiSecurity:
    """Install a security instance and a simple trusted resolver."""

    security = make_security()

    async def resolver(
        request: Request,
    ) -> ConfigurationPrincipal | None:
        return principal

    install_configuration_api_security(
        app,
        security=security,
        principal_resolver=resolver,
    )

    return security


def test_installs_configuration_security() -> None:
    app = make_app()
    security = make_security()

    def resolver(request: Request) -> ConfigurationPrincipal:
        return make_principal()

    install_configuration_api_security(
        app,
        security=security,
        principal_resolver=resolver,
    )

    assert getattr(app.state, SECURITY_STATE_KEY) is security
    assert getattr(app.state, PRINCIPAL_RESOLVER_STATE_KEY) is resolver


def test_rejects_non_fastapi_application() -> None:
    with pytest.raises(TypeError, match="FastAPI"):
        install_configuration_api_security(
            object(),  # type: ignore[arg-type]
            security=make_security(),
            principal_resolver=lambda request: make_principal(),
        )


def test_rejects_invalid_security_instance() -> None:
    app = make_app()

    with pytest.raises(TypeError, match="ConfigurationApiSecurity"):
        install_configuration_api_security(
            app,
            security=object(),  # type: ignore[arg-type]
            principal_resolver=lambda request: make_principal(),
        )


def test_rejects_non_callable_principal_resolver() -> None:
    app = make_app()

    with pytest.raises(TypeError, match="principal_resolver"):
        install_configuration_api_security(
            app,
            security=make_security(),
            principal_resolver="invalid",  # type: ignore[arg-type]
        )


def test_rejects_duplicate_security_installation() -> None:
    app = make_app()
    security = make_security()

    resolver = lambda request: make_principal()

    install_configuration_api_security(
        app,
        security=security,
        principal_resolver=resolver,
    )

    with pytest.raises(RuntimeError, match="already installed"):
        install_configuration_api_security(
            app,
            security=security,
            principal_resolver=resolver,
        )


def test_retrieves_installed_security() -> None:
    app = make_app()
    security = make_security()

    install_configuration_api_security(
        app,
        security=security,
        principal_resolver=lambda request: make_principal(),
    )

    assert get_configuration_api_security(app) is security


def test_security_accessor_rejects_non_fastapi_object() -> None:
    with pytest.raises(TypeError):
        get_configuration_api_security(object())  # type: ignore[arg-type]


def test_security_accessor_rejects_unconfigured_application() -> None:
    app = make_app()

    with pytest.raises(RuntimeError, match="not been installed"):
        get_configuration_api_security(app)


def test_retrieves_principal_resolver() -> None:
    app = make_app()

    def resolver(request: Request) -> ConfigurationPrincipal:
        return make_principal()

    install_configuration_api_security(
        app,
        security=make_security(),
        principal_resolver=resolver,
    )

    assert get_configuration_principal_resolver(app) is resolver


def test_principal_resolver_accessor_rejects_non_fastapi_object() -> None:
    with pytest.raises(TypeError):
        get_configuration_principal_resolver(
            object()  # type: ignore[arg-type]
        )


def test_principal_resolver_accessor_rejects_unconfigured_application() -> None:
    app = make_app()

    with pytest.raises(RuntimeError, match="not been installed"):
        get_configuration_principal_resolver(app)


@pytest.mark.asyncio
async def test_resolves_synchronous_principal() -> None:
    app = make_app()
    principal = make_principal()

    install_configuration_api_security(
        app,
        security=make_security(),
        principal_resolver=lambda request: principal,
    )

    resolved = await resolve_configuration_api_principal(
        make_request(app)
    )

    assert resolved is principal


@pytest.mark.asyncio
async def test_resolves_asynchronous_principal() -> None:
    app = make_app()
    principal = make_principal()

    async def resolver(request: Request) -> ConfigurationPrincipal:
        return principal

    install_configuration_api_security(
        app,
        security=make_security(),
        principal_resolver=resolver,
    )

    resolved = await resolve_configuration_api_principal(
        make_request(app)
    )

    assert resolved is principal


@pytest.mark.asyncio
async def test_rejects_missing_principal() -> None:
    app = make_app()

    install_configuration_api_security(
        app,
        security=make_security(),
        principal_resolver=lambda request: None,
    )

    with pytest.raises(HTTPException) as exc_info:
        await resolve_configuration_api_principal(
            make_request(app)
        )

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_rejects_inactive_principal() -> None:
    app = make_app()
    principal = make_principal(active=False)

    install_configuration_api_security(
        app,
        security=make_security(),
        principal_resolver=lambda request: principal,
    )

    with pytest.raises(HTTPException) as exc_info:
        await resolve_configuration_api_principal(
            make_request(app)
        )

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_rejects_invalid_principal_type() -> None:
    app = make_app()

    install_configuration_api_security(
        app,
        security=make_security(),
        principal_resolver=lambda request: object(),
    )

    with pytest.raises(HTTPException) as exc_info:
        await resolve_configuration_api_principal(
            make_request(app)
        )

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_preserves_http_exception_from_resolver() -> None:
    app = make_app()

    def resolver(request: Request) -> None:
        raise HTTPException(
            status_code=418,
            detail="Authentication service rejected request",
        )

    install_configuration_api_security(
        app,
        security=make_security(),
        principal_resolver=resolver,
    )

    with pytest.raises(HTTPException) as exc_info:
        await resolve_configuration_api_principal(
            make_request(app)
        )

    assert exc_info.value.status_code == 418


@pytest.mark.asyncio
async def test_translates_unexpected_resolver_exception() -> None:
    app = make_app()

    def resolver(request: Request) -> None:
        raise RuntimeError("Internal resolver failure")

    install_configuration_api_security(
        app,
        security=make_security(),
        principal_resolver=resolver,
    )

    with pytest.raises(HTTPException) as exc_info:
        await resolve_configuration_api_principal(
            make_request(app)
        )

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_validation_calls_security_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = make_app()
    principal = make_principal()
    security = install_test_security(
        app,
        principal=principal,
    )

    captured: dict[str, Any] = {}

    def validate_request(
        self: ConfigurationApiSecurity,
        *,
        principal: ConfigurationPrincipal,
        method: str,
        path: str,
    ) -> dict[str, bool]:
        captured["principal"] = principal
        captured["method"] = method
        captured["path"] = path

        return {"allowed": True}

    monkeypatch.setattr(
        ConfigurationApiSecurity,
        "validate_request",
        validate_request,
    )

    request = make_request(
        app,
        path="/api/v1/scheduling/configuration",
        method="POST",
    )

    result = await validate_configuration_api_request(request)

    assert result == {"allowed": True}
    assert captured["principal"] is principal
    assert captured["method"] == "POST"
    assert captured["path"] == "/api/v1/scheduling/configuration"


@pytest.mark.asyncio
async def test_validation_accepts_explicit_principal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = make_app()
    principal = make_principal()
    security = install_test_security(app)

    captured: dict[str, Any] = {}

    def validate_request(
        self: ConfigurationApiSecurity,
        *,
        principal: ConfigurationPrincipal,
        method: str,
        path: str,
    ) -> str:
        captured["principal"] = principal
        return "validated"

    monkeypatch.setattr(
        ConfigurationApiSecurity,
        "validate_request",
        validate_request,
    )

    result = await validate_configuration_api_request(
        make_request(app),
        principal=principal,
    )

    assert result == "validated"
    assert captured["principal"] is principal


@pytest.mark.asyncio
async def test_validation_supports_async_security_method(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = make_app()
    principal = make_principal()

    install_test_security(
        app,
        principal=principal,
    )

    async def validate_request(
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

    result = await validate_configuration_api_request(
        make_request(app)
    )

    assert result == {"allowed": True}


@pytest.mark.asyncio
async def test_validation_rejects_inactive_explicit_principal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = make_app()
    principal = make_principal(active=False)

    install_test_security(app)

    def validate_request(
        self: ConfigurationApiSecurity,
        **kwargs: Any,
    ) -> bool:
        pytest.fail("Security validation must not run for inactive users")

    monkeypatch.setattr(
        ConfigurationApiSecurity,
        "validate_request",
        validate_request,
    )

    with pytest.raises(HTTPException) as exc_info:
        await validate_configuration_api_request(
            make_request(app),
            principal=principal,
        )

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_validation_rejects_invalid_explicit_principal() -> None:
    app = make_app()
    install_test_security(app)

    with pytest.raises(HTTPException) as exc_info:
        await validate_configuration_api_request(
            make_request(app),
            principal=object(),  # type: ignore[arg-type]
        )

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_validation_preserves_security_http_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = make_app()
    install_test_security(
        app,
        principal=make_principal(),
    )

    def validate_request(
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
        validate_request,
    )

    with pytest.raises(HTTPException) as exc_info:
        await validate_configuration_api_request(
            make_request(app)
        )

    assert exc_info.value.status_code == 429


@pytest.mark.asyncio
async def test_validation_translates_unexpected_security_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = make_app()
    install_test_security(
        app,
        principal=make_principal(),
    )

    def validate_request(
        self: ConfigurationApiSecurity,
        **kwargs: Any,
    ) -> None:
        raise RuntimeError("Security service failure")

    monkeypatch.setattr(
        ConfigurationApiSecurity,
        "validate_request",
        validate_request,
    )

    with pytest.raises(HTTPException) as exc_info:
        await validate_configuration_api_request(
            make_request(app)
        )

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_validation_requires_installed_security() -> None:
    app = make_app()

    with pytest.raises(RuntimeError, match="not been installed"):
        await validate_configuration_api_request(
            make_request(app)
        )


@pytest.mark.asyncio
async def test_validation_requires_principal_resolver() -> None:
    app = make_app()

    app.state.configuration_api_security = make_security()

    with pytest.raises(RuntimeError, match="resolver"):
        await validate_configuration_api_request(
            make_request(app)
        )
