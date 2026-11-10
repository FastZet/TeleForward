
"""Integration tests for configuration API middleware installation."""

from __future__ import annotations

import pytest

from fastapi import FastAPI
from starlette.testclient import TestClient

from app.services.scheduling.configuration_api_middleware import (
    ConfigurationApiMiddleware,
)
from app.services.scheduling.configuration_api_middleware_integration import (
    IDENTITY_RESOLVER_STATE_KEY,
    MIDDLEWARE_INSTALLED_STATE_KEY,
    RATE_LIMITER_STATE_KEY,
    get_configuration_api_identity_resolver,
    get_configuration_api_rate_limiter,
    install_configuration_api_middleware,
    is_configuration_api_middleware_installed,
)


class FakeRateLimitResult:
    def __init__(
        self,
        *,
        allowed: bool = True,
        limit: int = 10,
        remaining: int = 9,
        retry_after_seconds: float = 0,
    ) -> None:
        self.allowed = allowed
        self.limit = limit
        self.remaining = remaining
        self.retry_after_seconds = retry_after_seconds


class FakeRateLimiter:
    def __init__(
        self,
        result: FakeRateLimitResult | None = None,
    ) -> None:
        self.result = result or FakeRateLimitResult()
        self.identities: list[str] = []
        self.calls = 0

    async def check(self, identity: str) -> FakeRateLimitResult:
        self.calls += 1
        self.identities.append(identity)
        return self.result


def create_test_app() -> FastAPI:
    """Create a FastAPI application with a configuration endpoint."""

    app = FastAPI()

    @app.get("/api/v1/scheduling/configuration")
    async def get_configuration() -> dict[str, bool]:
        return {"success": True}

    @app.get("/api/v1/accounts")
    async def get_accounts() -> dict[str, bool]:
        return {"success": True}

    return app


def test_installs_middleware_successfully() -> None:
    app = create_test_app()

    install_configuration_api_middleware(app)

    assert is_configuration_api_middleware_installed(app)
    assert getattr(
        app.state,
        MIDDLEWARE_INSTALLED_STATE_KEY,
    ) is True

    assert any(
        middleware.cls is ConfigurationApiMiddleware
        for middleware in app.user_middleware
    )


def test_rejects_non_fastapi_application() -> None:
    with pytest.raises(TypeError):
        install_configuration_api_middleware(object())  # type: ignore[arg-type]


def test_rejects_duplicate_installation() -> None:
    app = create_test_app()

    install_configuration_api_middleware(app)

    with pytest.raises(RuntimeError, match="already installed"):
        install_configuration_api_middleware(app)


def test_detects_direct_middleware_registration() -> None:
    app = create_test_app()

    app.add_middleware(ConfigurationApiMiddleware)

    with pytest.raises(RuntimeError, match="already registered"):
        install_configuration_api_middleware(app)


def test_rejects_invalid_enabled_value() -> None:
    app = create_test_app()

    with pytest.raises(TypeError):
        install_configuration_api_middleware(
            app,
            enabled=1,  # type: ignore[arg-type]
        )


def test_reuses_existing_rate_limiter() -> None:
    app = create_test_app()
    limiter = FakeRateLimiter()

    setattr(
        app.state,
        RATE_LIMITER_STATE_KEY,
        limiter,
    )

    install_configuration_api_middleware(app)

    assert get_configuration_api_rate_limiter(app) is limiter


def test_uses_explicit_rate_limiter() -> None:
    app = create_test_app()
    limiter = FakeRateLimiter()

    install_configuration_api_middleware(
        app,
        rate_limiter=limiter,  # type: ignore[arg-type]
    )

    assert get_configuration_api_rate_limiter(app) is limiter


def test_rejects_invalid_rate_limiter() -> None:
    app = create_test_app()

    with pytest.raises(TypeError, match="rate_limiter"):
        install_configuration_api_middleware(
            app,
            rate_limiter=object(),  # type: ignore[arg-type]
        )


def test_reuses_existing_identity_resolver() -> None:
    app = create_test_app()

    def resolver(scope: dict[str, object]) -> str:
        return "existing-user"

    setattr(
        app.state,
        IDENTITY_RESOLVER_STATE_KEY,
        resolver,
    )

    install_configuration_api_middleware(app)

    assert get_configuration_api_identity_resolver(app) is resolver


def test_uses_explicit_identity_resolver() -> None:
    app = create_test_app()

    def resolver(scope: dict[str, object]) -> str:
        return "explicit-user"

    install_configuration_api_middleware(
        app,
        identity_resolver=resolver,  # type: ignore[arg-type]
    )

    assert get_configuration_api_identity_resolver(app) is resolver


def test_rejects_invalid_identity_resolver() -> None:
    app = create_test_app()

    with pytest.raises(TypeError, match="identity_resolver"):
        install_configuration_api_middleware(
            app,
            identity_resolver="invalid",  # type: ignore[arg-type]
        )


def test_retrieves_configured_rate_limiter() -> None:
    app = create_test_app()
    limiter = FakeRateLimiter()

    install_configuration_api_middleware(
        app,
        rate_limiter=limiter,  # type: ignore[arg-type]
    )

    assert get_configuration_api_rate_limiter(app) is limiter


def test_rate_limiter_helper_rejects_unconfigured_application() -> None:
    app = create_test_app()

    with pytest.raises(RuntimeError, match="not been configured"):
        get_configuration_api_rate_limiter(app)


def test_retrieves_identity_resolver() -> None:
    app = create_test_app()

    def resolver(scope: object) -> str:
        return "test-user"

    install_configuration_api_middleware(
        app,
        identity_resolver=resolver,  # type: ignore[arg-type]
    )

    assert get_configuration_api_identity_resolver(app) is resolver


def test_identity_resolver_helper_returns_none_when_unconfigured() -> None:
    app = create_test_app()

    assert get_configuration_api_identity_resolver(app) is None


def test_installation_registers_working_http_middleware() -> None:
    app = create_test_app()
    limiter = FakeRateLimiter()

    install_configuration_api_middleware(
        app,
        rate_limiter=limiter,  # type: ignore[arg-type]
        identity_resolver=lambda scope: "integration-user",
    )

    with TestClient(app) as client:
        response = client.get(
            "/api/v1/scheduling/configuration"
        )

        assert response.status_code == 200
        assert response.json() == {"success": True}

        assert (
            response.headers["x-content-type-options"]
            == "nosniff"
        )

        assert response.headers["x-frame-options"] == "DENY"
        assert response.headers["cache-control"] == "no-store"

    assert limiter.identities == ["integration-user"]


def test_middleware_does_not_intercept_unrelated_routes() -> None:
    app = create_test_app()
    limiter = FakeRateLimiter()

    install_configuration_api_middleware(
        app,
        rate_limiter=limiter,  # type: ignore[arg-type]
        identity_resolver=lambda scope: "integration-user",
    )

    with TestClient(app) as client:
        response = client.get("/api/v1/accounts")

    assert response.status_code == 200
    assert response.json() == {"success": True}
    assert limiter.calls == 0


def test_disabled_middleware_is_registered_but_inactive() -> None:
    app = create_test_app()
    limiter = FakeRateLimiter()

    install_configuration_api_middleware(
        app,
        rate_limiter=limiter,  # type: ignore[arg-type]
        enabled=False,
    )

    assert is_configuration_api_middleware_installed(app)

    with TestClient(app) as client:
        response = client.get(
            "/api/v1/scheduling/configuration"
        )

    assert response.status_code == 200
    assert limiter.calls == 0


def test_middleware_uses_configured_api_prefix() -> None:
    app = create_test_app()
    limiter = FakeRateLimiter()

    @app.get("/internal/configuration")
    async def internal_configuration() -> dict[str, bool]:
        return {"success": True}

    install_configuration_api_middleware(
        app,
        api_prefix="/internal/configuration",
        rate_limiter=limiter,  # type: ignore[arg-type]
        identity_resolver=lambda scope: "custom-prefix-user",
    )

    with TestClient(app) as client:
        response = client.get("/internal/configuration")

    assert response.status_code == 200
    assert limiter.identities == ["custom-prefix-user"]


def test_rejects_accessors_for_non_fastapi_objects() -> None:
    with pytest.raises(TypeError):
        is_configuration_api_middleware_installed(
            object()  # type: ignore[arg-type]
        )

    with pytest.raises(TypeError):
        get_configuration_api_rate_limiter(
            object()  # type: ignore[arg-type]
        )

    with pytest.raises(TypeError):
        get_configuration_api_identity_resolver(
            object()  # type: ignore[arg-type]
        )
