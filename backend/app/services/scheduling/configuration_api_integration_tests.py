"""Integration tests for scheduling configuration API registration."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI

from app.services.scheduling.configuration_api import (
    ConfigurationApiDependencies,
)
from app.services.scheduling.configuration_api_dependencies import (
    get_configuration_api_dependencies,
    get_configuration_principal,
)
from app.services.scheduling.configuration_api_errors import (
    register_configuration_exception_handlers,
)
from app.services.scheduling.configuration_api_routes import (
    DEFAULT_CONFIGURATION_API_PREFIX,
    register_configuration_api,
)


class DummyPrincipal:
    """Placeholder used to verify resolver registration."""

    pass


class TestConfigurationApiRegistration:
    @pytest.fixture
    def app(self) -> FastAPI:
        return FastAPI()

    @pytest.fixture
    def dependencies(self) -> ConfigurationApiDependencies:
        """Create dependency container for registration tests."""

        return ConfigurationApiDependencies(
            manager=object(),  # type: ignore[arg-type]
            synchronizer=object(),  # type: ignore[arg-type]
            applier=object(),  # type: ignore[arg-type]
            permission_service=object(),  # type: ignore[arg-type]
            policy_service=object(),  # type: ignore[arg-type]
        )

    @staticmethod
    async def principal_resolver(request: Any) -> Any:
        return DummyPrincipal()

    def test_registers_configuration_routes(
        self,
        app: FastAPI,
        dependencies: ConfigurationApiDependencies,
    ) -> None:
        register_configuration_api(
            app,
            dependencies,
            self.principal_resolver,
        )

        paths = set(app.openapi()["paths"])

        assert (
            "/api/v1/scheduling/configuration"
            in paths
        )
        assert (
            "/api/v1/scheduling/configuration/tasks/{task_name}"
            in paths
        )
        assert (
            "/api/v1/scheduling/configuration/preview"
            in paths
        )
        assert (
            "/api/v1/scheduling/configuration/synchronize"
            in paths
        )

    def test_custom_prefix_is_respected(
        self,
        app: FastAPI,
        dependencies: ConfigurationApiDependencies,
    ) -> None:
        register_configuration_api(
            app,
            dependencies,
            self.principal_resolver,
            prefix="/internal/v2",
        )

        paths = set(app.openapi()["paths"])

        assert (
            "/internal/v2/scheduling/configuration"
            in paths
        )

    def test_default_prefix_is_configured(self) -> None:
        assert DEFAULT_CONFIGURATION_API_PREFIX == "/api/v1"

    def test_duplicate_registration_is_rejected(
        self,
        app: FastAPI,
        dependencies: ConfigurationApiDependencies,
    ) -> None:
        register_configuration_api(
            app,
            dependencies,
            self.principal_resolver,
        )

        with pytest.raises(RuntimeError):
            register_configuration_api(
                app,
                dependencies,
                self.principal_resolver,
            )

    def test_invalid_application_is_rejected(
        self,
        dependencies: ConfigurationApiDependencies,
    ) -> None:
        with pytest.raises(TypeError):
            register_configuration_api(
                object(),  # type: ignore[arg-type]
                dependencies,
                self.principal_resolver,
            )

    def test_invalid_dependencies_are_rejected(
        self,
        app: FastAPI,
    ) -> None:
        with pytest.raises(TypeError):
            register_configuration_api(
                app,
                object(),  # type: ignore[arg-type]
                self.principal_resolver,
            )

    def test_missing_principal_resolver_is_rejected(
        self,
        app: FastAPI,
        dependencies: ConfigurationApiDependencies,
    ) -> None:
        with pytest.raises(TypeError):
            register_configuration_api(
                app,
                dependencies,
                None,
            )

    @pytest.mark.parametrize(
        "prefix",
        [
            "api/v1",
            "",
            "/",
        ],
    )
    def test_invalid_prefix_is_rejected(
        self,
        app: FastAPI,
        dependencies: ConfigurationApiDependencies,
        prefix: str,
    ) -> None:
        with pytest.raises(ValueError):
            register_configuration_api(
                app,
                dependencies,
                self.principal_resolver,
                prefix=prefix,
            )

    def test_exception_handlers_are_registered(
        self,
        app: FastAPI,
    ) -> None:
        register_configuration_exception_handlers(app)

        assert app.exception_handlers

    def test_dependencies_are_stored_on_application_state(
        self,
        app: FastAPI,
        dependencies: ConfigurationApiDependencies,
    ) -> None:
        register_configuration_api(
            app,
            dependencies,
            self.principal_resolver,
        )

        assert (
            app.state.configuration_api_dependencies
            is dependencies
        )

        assert callable(
            app.state.configuration_principal_resolver
        )

    def test_dependency_provider_rejects_unconfigured_application(
        self,
    ) -> None:
        app = FastAPI()

        async def endpoint(request: Any) -> None:
            get_configuration_api_dependencies(request)

        assert not hasattr(
            app.state,
            "configuration_api_dependencies",
        )

    def test_principal_resolver_is_available_after_registration(
        self,
        app: FastAPI,
        dependencies: ConfigurationApiDependencies,
    ) -> None:
        register_configuration_api(
            app,
            dependencies,
            self.principal_resolver,
        )

        assert (
            app.state.configuration_principal_resolver
            is self.principal_resolver
        )
