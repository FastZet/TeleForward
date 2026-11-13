
"""Tests for scheduler runtime lifespan integration helpers."""

from __future__ import annotations

import pytest
from fastapi import FastAPI

from app.services.scheduling.scheduler_lifecycle import (
    SchedulerLifecycleState,
)
from app.services.scheduling.scheduler_runtime import SchedulerRuntime
from app.services.scheduling.scheduler_runtime_integration import (
    install_scheduler_runtime,
)
from app.services.scheduling.scheduler_runtime_lifespan import (
    create_scheduler_runtime_lifespan,
)
from app.services.scheduling.scheduler_runtime_lifespan_integration import (
    SCHEDULER_RUNTIME_LIFESPAN_FACTORY_STATE_KEY,
    SCHEDULER_RUNTIME_LIFESPAN_STATE_KEY,
    SchedulerRuntimeLifespanIntegrationError,
    get_scheduler_runtime_lifespan,
    get_scheduler_runtime_lifespan_optional,
    get_scheduler_runtime_lifespan_status,
    install_scheduler_runtime_lifespan,
    is_scheduler_runtime_lifespan_installed,
    remove_scheduler_runtime_lifespan,
)
from app.services.scheduling.tasks.task_registry import (
    ScheduledTaskRegistry,
)


class FakeManager:
    """Minimal scheduler manager for lifespan integration tests."""

    def __init__(self) -> None:
        self.start_calls = 0
        self.shutdown_calls = 0

    async def start(self) -> None:
        self.start_calls += 1

    async def shutdown(self) -> None:
        self.shutdown_calls += 1


@pytest.fixture
def app() -> FastAPI:
    return FastAPI()


@pytest.fixture
def manager() -> FakeManager:
    return FakeManager()


@pytest.fixture
def runtime(manager: FakeManager) -> SchedulerRuntime:
    return SchedulerRuntime(
        manager=manager,
        task_registry=ScheduledTaskRegistry(),
    )


@pytest.fixture
def installed_app(
    app: FastAPI,
    runtime: SchedulerRuntime,
) -> FastAPI:
    install_scheduler_runtime(app, runtime)
    return app


def test_install_scheduler_runtime_lifespan(
    installed_app: FastAPI,
) -> None:
    lifespan = install_scheduler_runtime_lifespan(installed_app)

    assert callable(lifespan)
    assert (
        getattr(
            installed_app.state,
            SCHEDULER_RUNTIME_LIFESPAN_STATE_KEY,
        )
        is lifespan
    )


def test_install_stores_factory_reference(
    installed_app: FastAPI,
) -> None:
    install_scheduler_runtime_lifespan(installed_app)

    factory = getattr(
        installed_app.state,
        SCHEDULER_RUNTIME_LIFESPAN_FACTORY_STATE_KEY,
    )

    assert factory is create_scheduler_runtime_lifespan


def test_install_requires_runtime_first(
    app: FastAPI,
) -> None:
    with pytest.raises(
        SchedulerRuntimeLifespanIntegrationError,
        match="Install the scheduler runtime",
    ):
        install_scheduler_runtime_lifespan(app)


def test_install_rejects_invalid_application() -> None:
    with pytest.raises(TypeError, match="FastAPI"):
        install_scheduler_runtime_lifespan(
            object(),  # type: ignore[arg-type]
        )


def test_install_rejects_invalid_replace_option(
    installed_app: FastAPI,
) -> None:
    with pytest.raises(TypeError, match="boolean"):
        install_scheduler_runtime_lifespan(
            installed_app,
            replace=1,  # type: ignore[arg-type]
        )


def test_install_is_rejected_when_already_installed(
    installed_app: FastAPI,
) -> None:
    install_scheduler_runtime_lifespan(installed_app)

    with pytest.raises(
        SchedulerRuntimeLifespanIntegrationError,
        match="already installed",
    ):
        install_scheduler_runtime_lifespan(installed_app)


def test_install_allows_replacement(
    installed_app: FastAPI,
) -> None:
    original = install_scheduler_runtime_lifespan(installed_app)

    replacement = install_scheduler_runtime_lifespan(
        installed_app,
        replace=True,
    )

    assert replacement is not original
    assert (
        get_scheduler_runtime_lifespan(installed_app)
        is replacement
    )


def test_install_accepts_callbacks(
    installed_app: FastAPI,
) -> None:
    def callback(app: FastAPI) -> None:
        pass

    lifespan = install_scheduler_runtime_lifespan(
        installed_app,
        before_start=callback,
        after_start=callback,
        before_shutdown=callback,
        after_shutdown=callback,
    )

    assert callable(lifespan)


@pytest.mark.parametrize(
    ("argument", "value"),
    [
        ("before_start", "invalid"),
        ("after_start", "invalid"),
        ("before_shutdown", "invalid"),
        ("after_shutdown", "invalid"),
    ],
)
def test_install_rejects_invalid_callbacks(
    installed_app: FastAPI,
    argument: str,
    value: str,
) -> None:
    with pytest.raises(TypeError):
        install_scheduler_runtime_lifespan(
            installed_app,
            **{argument: value},
        )


def test_get_scheduler_runtime_lifespan(
    installed_app: FastAPI,
) -> None:
    lifespan = install_scheduler_runtime_lifespan(installed_app)

    assert get_scheduler_runtime_lifespan(installed_app) is lifespan


def test_get_scheduler_runtime_lifespan_rejects_missing(
    installed_app: FastAPI,
) -> None:
    with pytest.raises(
        SchedulerRuntimeLifespanIntegrationError,
        match="not installed",
    ):
        get_scheduler_runtime_lifespan(installed_app)


def test_get_optional_lifespan_when_missing(
    installed_app: FastAPI,
) -> None:
    assert get_scheduler_runtime_lifespan_optional(installed_app) is None


def test_get_optional_lifespan_when_installed(
    installed_app: FastAPI,
) -> None:
    lifespan = install_scheduler_runtime_lifespan(installed_app)

    assert get_scheduler_runtime_lifespan_optional(installed_app) is lifespan


def test_is_lifespan_installed_when_missing(
    installed_app: FastAPI,
) -> None:
    assert is_scheduler_runtime_lifespan_installed(installed_app) is False


def test_is_lifespan_installed_when_present(
    installed_app: FastAPI,
) -> None:
    install_scheduler_runtime_lifespan(installed_app)

    assert is_scheduler_runtime_lifespan_installed(installed_app) is True


def test_status_before_lifespan_registration(
    installed_app: FastAPI,
) -> None:
    status = get_scheduler_runtime_lifespan_status(installed_app)

    assert status == {
        "lifespan_installed": False,
        "runtime_installed": True,
        "ready_for_application_startup": False,
    }


def test_status_after_lifespan_registration(
    installed_app: FastAPI,
) -> None:
    install_scheduler_runtime_lifespan(installed_app)

    status = get_scheduler_runtime_lifespan_status(installed_app)

    assert status == {
        "lifespan_installed": True,
        "runtime_installed": True,
        "ready_for_application_startup": True,
    }


def test_status_rejects_invalid_application() -> None:
    with pytest.raises(TypeError, match="FastAPI"):
        get_scheduler_runtime_lifespan_status(
            object(),  # type: ignore[arg-type]
        )


def test_remove_lifespan_registration(
    installed_app: FastAPI,
) -> None:
    lifespan = install_scheduler_runtime_lifespan(installed_app)

    removed = remove_scheduler_runtime_lifespan(installed_app)

    assert removed is lifespan
    assert is_scheduler_runtime_lifespan_installed(installed_app) is False


def test_remove_clears_factory_reference(
    installed_app: FastAPI,
) -> None:
    install_scheduler_runtime_lifespan(installed_app)

    remove_scheduler_runtime_lifespan(installed_app)

    assert not hasattr(
        installed_app.state,
        SCHEDULER_RUNTIME_LIFESPAN_FACTORY_STATE_KEY,
    )


def test_remove_rejects_missing_registration(
    installed_app: FastAPI,
) -> None:
    with pytest.raises(
        SchedulerRuntimeLifespanIntegrationError,
        match="not installed",
    ):
        remove_scheduler_runtime_lifespan(installed_app)


def test_remove_rejects_invalid_application() -> None:
    with pytest.raises(TypeError, match="FastAPI"):
        remove_scheduler_runtime_lifespan(
            object(),  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_registered_lifespan_starts_and_stops_runtime(
    installed_app: FastAPI,
    runtime: SchedulerRuntime,
    manager: FakeManager,
) -> None:
    lifespan = install_scheduler_runtime_lifespan(installed_app)

    async with lifespan(installed_app):
        assert runtime.state == SchedulerLifecycleState.RUNNING
        assert runtime.is_running is True

    assert runtime.state == SchedulerLifecycleState.STOPPED
    assert manager.start_calls == 1
    assert manager.shutdown_calls == 1


@pytest.mark.asyncio
async def test_registered_lifespan_executes_callbacks(
    installed_app: FastAPI,
) -> None:
    events: list[str] = []

    lifespan = install_scheduler_runtime_lifespan(
        installed_app,
        before_start=lambda app: events.append("before_start"),
        after_start=lambda app: events.append("after_start"),
        before_shutdown=lambda app: events.append("before_shutdown"),
        after_shutdown=lambda app: events.append("after_shutdown"),
    )

    async with lifespan(installed_app):
        events.append("application_running")

    assert events == [
        "before_start",
        "after_start",
        "application_running",
        "before_shutdown",
        "after_shutdown",
    ]


@pytest.mark.asyncio
async def test_registered_lifespan_preserves_application_exception(
    installed_app: FastAPI,
    runtime: SchedulerRuntime,
) -> None:
    lifespan = install_scheduler_runtime_lifespan(installed_app)

    with pytest.raises(
        RuntimeError,
        match="Application failed",
    ):
        async with lifespan(installed_app):
            raise RuntimeError("Application failed")

    assert runtime.state == SchedulerLifecycleState.STOPPED


@pytest.mark.asyncio
async def test_registration_does_not_start_runtime(
    installed_app: FastAPI,
    runtime: SchedulerRuntime,
    manager: FakeManager,
) -> None:
    install_scheduler_runtime_lifespan(installed_app)

    assert runtime.state == SchedulerLifecycleState.STOPPED
    assert manager.start_calls == 0
    assert manager.shutdown_calls == 0


@pytest.mark.asyncio
async def test_removal_does_not_stop_runtime_automatically(
    installed_app: FastAPI,
    runtime: SchedulerRuntime,
    manager: FakeManager,
) -> None:
    await runtime.start()

    install_scheduler_runtime_lifespan(installed_app)

    remove_scheduler_runtime_lifespan(installed_app)

    assert runtime.state == SchedulerLifecycleState.RUNNING
    assert manager.shutdown_calls == 0

    await runtime.shutdown()


@pytest.mark.asyncio
async def test_replacement_does_not_start_runtime(
    installed_app: FastAPI,
    runtime: SchedulerRuntime,
    manager: FakeManager,
) -> None:
    install_scheduler_runtime_lifespan(installed_app)

    install_scheduler_runtime_lifespan(
        installed_app,
        replace=True,
    )

    assert runtime.state == SchedulerLifecycleState.STOPPED
    assert manager.start_calls == 0


def test_separate_applications_have_independent_registrations(
    manager: FakeManager,
) -> None:
    first_app = FastAPI()
    second_app = FastAPI()

    first_runtime = SchedulerRuntime(
        manager,
        ScheduledTaskRegistry(),
    )
    second_runtime = SchedulerRuntime(
        manager,
        ScheduledTaskRegistry(),
    )

    install_scheduler_runtime(first_app, first_runtime)
    install_scheduler_runtime(second_app, second_runtime)

    first_lifespan = install_scheduler_runtime_lifespan(first_app)
    second_lifespan = install_scheduler_runtime_lifespan(second_app)

    assert first_lifespan is not second_lifespan

    remove_scheduler_runtime_lifespan(first_app)

    assert is_scheduler_runtime_lifespan_installed(first_app) is False
    assert is_scheduler_runtime_lifespan_installed(second_app) is True
