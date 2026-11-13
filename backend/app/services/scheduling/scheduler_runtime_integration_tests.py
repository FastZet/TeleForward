
"""Tests for FastAPI scheduler runtime integration."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI

from app.services.scheduling.scheduler_lifecycle import (
    SchedulerLifecycleState,
)
from app.services.scheduling.scheduler_runtime import SchedulerRuntime
from app.services.scheduling.scheduler_runtime_integration import (
    SCHEDULER_RUNTIME_STATE_KEY,
    SchedulerRuntimeIntegrationError,
    get_scheduler_runtime,
    get_scheduler_runtime_optional,
    get_scheduler_runtime_state,
    get_scheduler_runtime_status,
    install_scheduler_runtime,
    is_scheduler_runtime_installed,
    is_scheduler_runtime_running,
    remove_scheduler_runtime,
    shutdown_scheduler_runtime,
    start_scheduler_runtime,
)
from app.services.scheduling.tasks.task_registry import (
    ScheduledTaskRegistry,
)


class FakeManager:
    """Minimal manager implementation for runtime integration tests."""

    def __init__(self) -> None:
        self.start_calls = 0
        self.shutdown_calls = 0
        self.start_error: Exception | None = None
        self.shutdown_error: Exception | None = None

    async def start(self) -> None:
        self.start_calls += 1

        if self.start_error is not None:
            raise self.start_error

    async def shutdown(self) -> None:
        self.shutdown_calls += 1

        if self.shutdown_error is not None:
            raise self.shutdown_error


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


def test_install_scheduler_runtime(
    app: FastAPI,
    runtime: SchedulerRuntime,
) -> None:
    result = install_scheduler_runtime(app, runtime)

    assert result is runtime
    assert app.state.scheduler_runtime is runtime


def test_install_returns_same_instance_when_already_installed(
    app: FastAPI,
    runtime: SchedulerRuntime,
) -> None:
    install_scheduler_runtime(app, runtime)

    result = install_scheduler_runtime(app, runtime)

    assert result is runtime
    assert get_scheduler_runtime(app) is runtime


def test_install_rejects_different_existing_runtime(
    app: FastAPI,
    runtime: SchedulerRuntime,
    manager: FakeManager,
) -> None:
    install_scheduler_runtime(app, runtime)

    replacement = SchedulerRuntime(
        manager,
        ScheduledTaskRegistry(),
    )

    with pytest.raises(
        SchedulerRuntimeIntegrationError,
        match="already installed",
    ):
        install_scheduler_runtime(app, replacement)


def test_install_allows_replacement_when_existing_runtime_is_stopped(
    app: FastAPI,
    runtime: SchedulerRuntime,
    manager: FakeManager,
) -> None:
    install_scheduler_runtime(app, runtime)

    replacement = SchedulerRuntime(
        manager,
        ScheduledTaskRegistry(),
    )

    result = install_scheduler_runtime(
        app,
        replacement,
        replace=True,
    )

    assert result is replacement
    assert get_scheduler_runtime(app) is replacement


@pytest.mark.asyncio
async def test_install_rejects_replacement_when_existing_runtime_is_running(
    app: FastAPI,
    runtime: SchedulerRuntime,
    manager: FakeManager,
) -> None:
    install_scheduler_runtime(app, runtime)
    await runtime.start()

    replacement = SchedulerRuntime(
        manager,
        ScheduledTaskRegistry(),
    )

    with pytest.raises(
        SchedulerRuntimeIntegrationError,
        match="not stopped",
    ):
        install_scheduler_runtime(
            app,
            replacement,
            replace=True,
        )


def test_install_rejects_invalid_application(
    runtime: SchedulerRuntime,
) -> None:
    with pytest.raises(TypeError, match="FastAPI"):
        install_scheduler_runtime(
            object(),  # type: ignore[arg-type]
            runtime,
        )


def test_install_rejects_invalid_runtime(
    app: FastAPI,
) -> None:
    with pytest.raises(TypeError, match="SchedulerRuntime"):
        install_scheduler_runtime(
            app,
            object(),  # type: ignore[arg-type]
        )


def test_install_rejects_non_boolean_replace(
    app: FastAPI,
    runtime: SchedulerRuntime,
) -> None:
    with pytest.raises(TypeError, match="boolean"):
        install_scheduler_runtime(
            app,
            runtime,
            replace=1,  # type: ignore[arg-type]
        )


def test_get_scheduler_runtime(
    app: FastAPI,
    runtime: SchedulerRuntime,
) -> None:
    install_scheduler_runtime(app, runtime)

    result = get_scheduler_runtime(app)

    assert result is runtime


def test_get_scheduler_runtime_rejects_missing_runtime(
    app: FastAPI,
) -> None:
    with pytest.raises(
        SchedulerRuntimeIntegrationError,
        match="not installed",
    ):
        get_scheduler_runtime(app)


def test_get_scheduler_runtime_optional_when_missing(
    app: FastAPI,
) -> None:
    assert get_scheduler_runtime_optional(app) is None


def test_get_scheduler_runtime_optional_when_installed(
    app: FastAPI,
    runtime: SchedulerRuntime,
) -> None:
    install_scheduler_runtime(app, runtime)

    assert get_scheduler_runtime_optional(app) is runtime


def test_optional_getter_rejects_invalid_stored_value(
    app: FastAPI,
) -> None:
    setattr(
        app.state,
        SCHEDULER_RUNTIME_STATE_KEY,
        object(),
    )

    with pytest.raises(
        SchedulerRuntimeIntegrationError,
        match="invalid type",
    ):
        get_scheduler_runtime_optional(app)


def test_is_scheduler_runtime_installed_when_missing(
    app: FastAPI,
) -> None:
    assert is_scheduler_runtime_installed(app) is False


def test_is_scheduler_runtime_installed_when_present(
    app: FastAPI,
    runtime: SchedulerRuntime,
) -> None:
    install_scheduler_runtime(app, runtime)

    assert is_scheduler_runtime_installed(app) is True


def test_initial_runtime_state(
    app: FastAPI,
    runtime: SchedulerRuntime,
) -> None:
    install_scheduler_runtime(app, runtime)

    assert get_scheduler_runtime_state(app) == (
        SchedulerLifecycleState.STOPPED
    )


def test_runtime_status(
    app: FastAPI,
    runtime: SchedulerRuntime,
) -> None:
    install_scheduler_runtime(app, runtime)

    status = get_scheduler_runtime_status(app)

    assert status["state"] == "stopped"
    assert status["is_running"] is False
    assert status["manager_started"] is False
    assert status["monitor_started"] is False
    assert status["registered_task_count"] == 0


@pytest.mark.asyncio
async def test_start_scheduler_runtime(
    app: FastAPI,
    runtime: SchedulerRuntime,
    manager: FakeManager,
) -> None:
    install_scheduler_runtime(app, runtime)

    result = await start_scheduler_runtime(app)

    assert result is runtime
    assert runtime.is_running is True
    assert manager.start_calls == 1


@pytest.mark.asyncio
async def test_start_scheduler_runtime_rejects_missing_runtime(
    app: FastAPI,
) -> None:
    with pytest.raises(SchedulerRuntimeIntegrationError):
        await start_scheduler_runtime(app)


@pytest.mark.asyncio
async def test_start_scheduler_runtime_wraps_startup_error(
    app: FastAPI,
    runtime: SchedulerRuntime,
    manager: FakeManager,
) -> None:
    install_scheduler_runtime(app, runtime)
    manager.start_error = RuntimeError("Manager startup failed")

    with pytest.raises(
        SchedulerRuntimeIntegrationError,
        match="Failed to start scheduler runtime",
    ) as error:
        await start_scheduler_runtime(app)

    assert isinstance(error.value.__cause__, Exception)
    assert runtime.state == SchedulerLifecycleState.FAILED


@pytest.mark.asyncio
async def test_shutdown_scheduler_runtime(
    app: FastAPI,
    runtime: SchedulerRuntime,
    manager: FakeManager,
) -> None:
    install_scheduler_runtime(app, runtime)

    await start_scheduler_runtime(app)

    result = await shutdown_scheduler_runtime(app)

    assert result is runtime
    assert runtime.state == SchedulerLifecycleState.STOPPED
    assert manager.shutdown_calls == 1


@pytest.mark.asyncio
async def test_shutdown_scheduler_runtime_wraps_error(
    app: FastAPI,
    runtime: SchedulerRuntime,
    manager: FakeManager,
) -> None:
    install_scheduler_runtime(app, runtime)

    await runtime.start()
    manager.shutdown_error = RuntimeError("Manager shutdown failed")

    with pytest.raises(
        SchedulerRuntimeIntegrationError,
        match="Failed to shut down scheduler runtime",
    ):
        await shutdown_scheduler_runtime(app)

    assert runtime.state == SchedulerLifecycleState.FAILED


@pytest.mark.asyncio
async def test_is_scheduler_runtime_running(
    app: FastAPI,
    runtime: SchedulerRuntime,
) -> None:
    assert is_scheduler_runtime_running(app) is False

    install_scheduler_runtime(app, runtime)

    assert is_scheduler_runtime_running(app) is False

    await start_scheduler_runtime(app)

    assert is_scheduler_runtime_running(app) is True

    await shutdown_scheduler_runtime(app)

    assert is_scheduler_runtime_running(app) is False


def test_remove_scheduler_runtime(
    app: FastAPI,
    runtime: SchedulerRuntime,
) -> None:
    install_scheduler_runtime(app, runtime)

    result = remove_scheduler_runtime(app)

    assert result is runtime
    assert get_scheduler_runtime_optional(app) is None


def test_remove_rejects_missing_runtime(
    app: FastAPI,
) -> None:
    with pytest.raises(SchedulerRuntimeIntegrationError):
        remove_scheduler_runtime(app)


def test_remove_rejects_non_stopped_runtime(
    app: FastAPI,
    runtime: SchedulerRuntime,
) -> None:
    install_scheduler_runtime(app, runtime)

    runtime._lifecycle._state = SchedulerLifecycleState.RUNNING

    with pytest.raises(
        SchedulerRuntimeIntegrationError,
        match="not stopped",
    ):
        remove_scheduler_runtime(app)


def test_remove_can_explicitly_allow_running_runtime(
    app: FastAPI,
    runtime: SchedulerRuntime,
) -> None:
    install_scheduler_runtime(app, runtime)

    runtime._lifecycle._state = SchedulerLifecycleState.RUNNING

    result = remove_scheduler_runtime(
        app,
        require_stopped=False,
    )

    assert result is runtime
    assert get_scheduler_runtime_optional(app) is None


def test_remove_rejects_non_boolean_option(
    app: FastAPI,
    runtime: SchedulerRuntime,
) -> None:
    install_scheduler_runtime(app, runtime)

    with pytest.raises(TypeError, match="boolean"):
        remove_scheduler_runtime(
            app,
            require_stopped=1,  # type: ignore[arg-type]
        )


def test_application_instances_have_independent_runtime_state(
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

    assert get_scheduler_runtime(first_app) is first_runtime
    assert get_scheduler_runtime(second_app) is second_runtime

    remove_scheduler_runtime(first_app)

    assert is_scheduler_runtime_installed(first_app) is False
    assert is_scheduler_runtime_installed(second_app) is True


def test_runtime_installation_does_not_start_runtime(
    app: FastAPI,
    runtime: SchedulerRuntime,
    manager: FakeManager,
) -> None:
    install_scheduler_runtime(app, runtime)

    assert runtime.state == SchedulerLifecycleState.STOPPED
    assert manager.start_calls == 0


def test_remove_rejects_invalid_application(
    runtime: SchedulerRuntime,
) -> None:
    with pytest.raises(TypeError, match="FastAPI"):
        remove_scheduler_runtime(
            object(),  # type: ignore[arg-type]
        )


def test_status_rejects_missing_runtime(
    app: FastAPI,
) -> None:
    with pytest.raises(SchedulerRuntimeIntegrationError):
        get_scheduler_runtime_status(app)


def test_runtime_state_rejects_missing_runtime(
    app: FastAPI,
) -> None:
    with pytest.raises(SchedulerRuntimeIntegrationError):
        get_scheduler_runtime_state(app)
