
"""Tests for FastAPI bootstrap health integration."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from fastapi import FastAPI

from app.services.scheduling.integration_bootstrap import (
    BootstrapState,
    SchedulingIntegrationBootstrap,
)
from app.services.scheduling.integration_bootstrap_health import (
    BootstrapHealthStatus,
    SchedulingBootstrapHealthService,
)
from app.services.scheduling.integration_bootstrap_health_integration import (
    BOOTSTRAP_HEALTH_STATE_KEY,
    BootstrapHealthIntegrationError,
    get_bootstrap_health,
    get_bootstrap_health_optional,
    get_bootstrap_health_report,
    get_bootstrap_health_status,
    install_bootstrap_health,
    is_bootstrap_health_installed,
    is_bootstrap_healthy,
    remove_bootstrap_health,
)


class FakeScheduler:
    def add_job(self) -> None:
        pass

    def get_job(self) -> None:
        pass

    def get_jobs(self) -> list[object]:
        return []

    def remove_job(self) -> None:
        pass

    def start(self) -> None:
        pass

    def shutdown(self) -> None:
        pass

    def pause(self) -> None:
        pass

    def resume(self) -> None:
        pass


class FakeSchedulerManager:
    def __init__(self, scheduler: FakeScheduler) -> None:
        self.scheduler = scheduler

    def create_job(self) -> None:
        pass

    def update_job(self) -> None:
        pass

    def delete_job(self) -> None:
        pass

    def enable_job(self) -> None:
        pass

    def disable_job(self) -> None:
        pass

    def list_jobs(self) -> list[str]:
        return []

    def restore_jobs(self) -> int:
        return 0

    def start(self) -> None:
        pass

    def shutdown(self) -> None:
        pass


class FakeTaskRegistry:
    def register(self) -> None:
        pass

    def get(self) -> None:
        pass

    def get_optional(self) -> None:
        pass

    def unregister(self) -> None:
        pass

    def contains(self) -> bool:
        return False

    def names(self) -> tuple[str, ...]:
        return ()

    def get_all(self) -> tuple[object, ...]:
        return ()


class FakeJobStore:
    def add(self) -> None:
        pass

    def get(self) -> None:
        pass

    def list_all(self) -> list[object]:
        return []

    def update(self) -> None:
        pass

    def delete(self) -> None:
        pass

    def close(self) -> None:
        pass


@pytest.fixture
def app() -> FastAPI:
    return FastAPI()


@pytest.fixture
def bootstrap() -> SchedulingIntegrationBootstrap:
    scheduler = FakeScheduler()

    components = {
        "scheduler_manager": FakeSchedulerManager(scheduler),
        "task_registry": FakeTaskRegistry(),
        "job_store": FakeJobStore(),
        "scheduler": scheduler,
    }

    factories: dict[str, Callable[[], Any]] = {
        name: (lambda component=component: component)
        for name, component in components.items()
    }

    return SchedulingIntegrationBootstrap(factories)


@pytest.fixture
def service() -> SchedulingBootstrapHealthService:
    return SchedulingBootstrapHealthService()


def test_install_service(
    app: FastAPI,
    service: SchedulingBootstrapHealthService,
) -> None:
    installed = install_bootstrap_health(app, service)

    assert installed is service
    assert getattr(app.state, BOOTSTRAP_HEALTH_STATE_KEY) is service


def test_install_creates_unbound_service(
    app: FastAPI,
) -> None:
    installed = install_bootstrap_health(app)

    assert isinstance(
        installed,
        SchedulingBootstrapHealthService,
    )
    assert get_bootstrap_health(app) is installed


def test_install_with_bootstrap(
    app: FastAPI,
    bootstrap: SchedulingIntegrationBootstrap,
) -> None:
    installed = install_bootstrap_health(
        app,
        bootstrap=bootstrap,
    )

    assert installed.bootstrap is bootstrap


def test_install_rejects_service_and_bootstrap_together(
    app: FastAPI,
    service: SchedulingBootstrapHealthService,
    bootstrap: SchedulingIntegrationBootstrap,
) -> None:
    with pytest.raises(ValueError):
        install_bootstrap_health(
            app,
            service,
            bootstrap=bootstrap,
        )


def test_install_rejects_invalid_app() -> None:
    with pytest.raises(TypeError):
        install_bootstrap_health(
            object(),  # type: ignore[arg-type]
        )


def test_install_rejects_invalid_service(
    app: FastAPI,
) -> None:
    with pytest.raises(TypeError):
        install_bootstrap_health(
            app,
            object(),  # type: ignore[arg-type]
        )


def test_duplicate_install_is_rejected(
    app: FastAPI,
    service: SchedulingBootstrapHealthService,
) -> None:
    install_bootstrap_health(app, service)

    with pytest.raises(BootstrapHealthIntegrationError):
        install_bootstrap_health(
            app,
            SchedulingBootstrapHealthService(),
        )


def test_installing_same_service_is_idempotent(
    app: FastAPI,
    service: SchedulingBootstrapHealthService,
) -> None:
    first = install_bootstrap_health(app, service)
    second = install_bootstrap_health(app, service)

    assert first is second
    assert second is service


def test_replace_existing_service(
    app: FastAPI,
) -> None:
    original = SchedulingBootstrapHealthService()
    replacement = SchedulingBootstrapHealthService()

    install_bootstrap_health(app, original)

    installed = install_bootstrap_health(
        app,
        replacement,
        replace=True,
    )

    assert installed is replacement
    assert get_bootstrap_health(app) is replacement


def test_replace_existing_service_with_new_unbound_service(
    app: FastAPI,
) -> None:
    original = SchedulingBootstrapHealthService()

    install_bootstrap_health(app, original)

    replacement = install_bootstrap_health(
        app,
        replace=True,
    )

    assert replacement is not original
    assert get_bootstrap_health(app) is replacement


def test_replace_existing_service_with_bootstrap(
    app: FastAPI,
    bootstrap: SchedulingIntegrationBootstrap,
) -> None:
    original = SchedulingBootstrapHealthService()

    install_bootstrap_health(app, original)

    replacement = install_bootstrap_health(
        app,
        bootstrap=bootstrap,
        replace=True,
    )

    assert replacement is not original
    assert replacement.bootstrap is bootstrap


def test_get_installed_service(
    app: FastAPI,
    service: SchedulingBootstrapHealthService,
) -> None:
    install_bootstrap_health(app, service)

    assert get_bootstrap_health(app) is service


def test_get_service_rejects_missing_installation(
    app: FastAPI,
) -> None:
    with pytest.raises(BootstrapHealthIntegrationError):
        get_bootstrap_health(app)


def test_get_optional_returns_none_when_missing(
    app: FastAPI,
) -> None:
    assert get_bootstrap_health_optional(app) is None


def test_get_optional_returns_installed_service(
    app: FastAPI,
    service: SchedulingBootstrapHealthService,
) -> None:
    install_bootstrap_health(app, service)

    assert get_bootstrap_health_optional(app) is service


def test_is_installed_returns_false_when_missing(
    app: FastAPI,
) -> None:
    assert is_bootstrap_health_installed(app) is False


def test_is_installed_returns_true_when_present(
    app: FastAPI,
    service: SchedulingBootstrapHealthService,
) -> None:
    install_bootstrap_health(app, service)

    assert is_bootstrap_health_installed(app) is True


@pytest.mark.asyncio
async def test_get_health_report(
    app: FastAPI,
    bootstrap: SchedulingIntegrationBootstrap,
) -> None:
    await bootstrap.bootstrap()

    service = SchedulingBootstrapHealthService(bootstrap)
    install_bootstrap_health(app, service)

    report = get_bootstrap_health_report(app)

    assert report.status is BootstrapHealthStatus.HEALTHY


@pytest.mark.asyncio
async def test_get_health_status(
    app: FastAPI,
    bootstrap: SchedulingIntegrationBootstrap,
) -> None:
    await bootstrap.bootstrap()

    install_bootstrap_health(
        app,
        bootstrap=bootstrap,
    )

    assert (
        get_bootstrap_health_status(app)
        is BootstrapHealthStatus.HEALTHY
    )


@pytest.mark.asyncio
async def test_is_bootstrap_healthy(
    app: FastAPI,
    bootstrap: SchedulingIntegrationBootstrap,
) -> None:
    await bootstrap.bootstrap()

    install_bootstrap_health(
        app,
        bootstrap=bootstrap,
    )

    assert is_bootstrap_healthy(app) is True


def test_is_bootstrap_healthy_returns_false_before_bootstrap(
    app: FastAPI,
    bootstrap: SchedulingIntegrationBootstrap,
) -> None:
    install_bootstrap_health(
        app,
        bootstrap=bootstrap,
    )

    assert is_bootstrap_healthy(app) is False


def test_health_inspection_rejects_missing_service(
    app: FastAPI,
) -> None:
    with pytest.raises(BootstrapHealthIntegrationError):
        get_bootstrap_health_report(app)


def test_remove_installed_service(
    app: FastAPI,
    service: SchedulingBootstrapHealthService,
) -> None:
    install_bootstrap_health(app, service)

    removed = remove_bootstrap_health(app)

    assert removed is service
    assert is_bootstrap_health_installed(app) is False


def test_remove_returns_removed_service(
    app: FastAPI,
    service: SchedulingBootstrapHealthService,
) -> None:
    install_bootstrap_health(app, service)

    assert remove_bootstrap_health(app) is service


def test_remove_rejects_missing_service(
    app: FastAPI,
) -> None:
    with pytest.raises(BootstrapHealthIntegrationError):
        remove_bootstrap_health(app)


def test_remove_with_matching_expected_service(
    app: FastAPI,
    service: SchedulingBootstrapHealthService,
) -> None:
    install_bootstrap_health(app, service)

    removed = remove_bootstrap_health(
        app,
        expected_service=service,
    )

    assert removed is service
    assert is_bootstrap_health_installed(app) is False


def test_remove_rejects_mismatched_expected_service(
    app: FastAPI,
) -> None:
    original = SchedulingBootstrapHealthService()
    other = SchedulingBootstrapHealthService()

    install_bootstrap_health(app, original)

    with pytest.raises(BootstrapHealthIntegrationError):
        remove_bootstrap_health(
            app,
            expected_service=other,
        )

    assert get_bootstrap_health(app) is original


def test_remove_rejects_invalid_expected_service(
    app: FastAPI,
    service: SchedulingBootstrapHealthService,
) -> None:
    install_bootstrap_health(app, service)

    with pytest.raises(TypeError):
        remove_bootstrap_health(
            app,
            expected_service=object(),  # type: ignore[arg-type]
        )


def test_remove_rejects_invalid_app() -> None:
    with pytest.raises(TypeError):
        remove_bootstrap_health(
            object(),  # type: ignore[arg-type]
        )


def test_invalid_state_object_is_rejected(
    app: FastAPI,
) -> None:
    setattr(
        app.state,
        BOOTSTRAP_HEALTH_STATE_KEY,
        object(),
    )

    with pytest.raises(TypeError):
        get_bootstrap_health(app)


def test_optional_retrieval_rejects_invalid_state(
    app: FastAPI,
) -> None:
    setattr(
        app.state,
        BOOTSTRAP_HEALTH_STATE_KEY,
        object(),
    )

    with pytest.raises(TypeError):
        get_bootstrap_health_optional(app)


def test_removal_does_not_remove_replacement(
    app: FastAPI,
) -> None:
    original = SchedulingBootstrapHealthService()
    replacement = SchedulingBootstrapHealthService()

    install_bootstrap_health(app, original)
    install_bootstrap_health(
        app,
        replacement,
        replace=True,
    )

    with pytest.raises(BootstrapHealthIntegrationError):
        remove_bootstrap_health(
            app,
            expected_service=original,
        )

    assert get_bootstrap_health(app) is replacement


def test_installation_does_not_create_duplicate_state_entries(
    app: FastAPI,
    service: SchedulingBootstrapHealthService,
) -> None:
    install_bootstrap_health(app, service)
    install_bootstrap_health(app, service)

    assert (
        getattr(app.state, BOOTSTRAP_HEALTH_STATE_KEY)
        is service
    )


def test_removal_does_not_close_bootstrap(
    app: FastAPI,
    bootstrap: SchedulingIntegrationBootstrap,
) -> None:
    service = SchedulingBootstrapHealthService(bootstrap)

    install_bootstrap_health(app, service)
    remove_bootstrap_health(
        app,
        expected_service=service,
    )

    assert bootstrap.state is BootstrapState.NOT_STARTED
