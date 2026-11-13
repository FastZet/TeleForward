
"""Tests for scheduler runtime lifespan integration."""

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
from app.services.scheduling.scheduler_runtime_lifespan_integration import (
    SCHEDULER_RUNTIME_LIFESPAN_STATE_KEY,
    SchedulerRuntimeLifespanIntegrationError,
    create_scheduler_runtime_lifespan_integration,
    get_scheduler_runtime_lifespan,
    get_scheduler_runtime_lifespan_optional,
    get_scheduler_runtime_lifespan_status,
    is_scheduler_runtime_lifespan_registered,
    register_scheduler_runtime_lifespan,
    remove_scheduler_runtime_lifespan,
)
from app.services.scheduling.tasks.task_registry import (
    ScheduledTaskRegistry,
)


class FakeManager:
    """Minimal scheduler manager for integration tests."""

    def __init__(self) -> None:
        self.start_calls = 0
        self.shutdown_calls = 0
        self.fail_start = False
        self.fail_shutdown = False

    async def start(self) -> None:
        self.start_calls += 1

        if self.fail_start:
            raise RuntimeError("Manager startup failed")

    async def shutdown(self) -> None:
        self.shutdown_calls += 1

        if self.fail_shutdown:
            raise RuntimeError("Manager shutdown failed")


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
def lifespan():
    return create_scheduler_runtime_lifespan_integration()


@pytest.fixture
def app(
    runtime: SchedulerRuntime,
    lifespan,
) -> FastAPI:
    application = FastAPI(lifespan=lifespan)
    install_scheduler_runtime(application, runtime)
    register_scheduler_runtime_lifespan(application, lifespan)
    return application


def test_create_lifespan_without_application() -> None:
    lifespan = create_scheduler_runtime_lifespan_integration()

    assert callable(lifespan)


def test_create_lifespan_rejects_invalid_callback() -> None:
    with pytest.raises(TypeError, match="before_start"):
        create_scheduler_runtime_lifespan_integration(
            before_start="invalid",  # type: ignore[arg-type]
        )


def test_create_lifespan_accepts_callbacks() -> None:
    callback = lambda app: None

    lifespan = create_scheduler_runtime_lifespan_integration(
        before_start=callback,
        after_start=callback,
        before_shutdown=callback,
        after_shutdown=callback,
    )

    assert callable(lifespan)


def test_register_lifespan_metadata(app: FastAPI, lifespan) -> None:
    assert (
        getattr(app.state, SCHEDULER_RUNTIME_LIFESPAN_STATE_KEY)
        is lifespan
    )


def test_register_rejects_invalid_application(lifespan) -> None:
    with pytest.raises(TypeError, match="FastAPI"):
        register_scheduler_runtime_lifespan(
            object(),  # type: ignore[arg-type]
            lifespan,
        )


def test_register_rejects_non_callable_lifespan(
    app: FastAPI,
) -> None:
    with pytest.raises(TypeError, match="callable"):
        register_scheduler_runtime_lifespan(
            app,
            object(),  # type: ignore[arg-type]
        )


def test_register_rejects_invalid_replace_option(
    app: FastAPI,
    lifespan,
) -> None:
    with pytest.raises(TypeError, match="boolean"):
        register_scheduler_runtime_lifespan(
            app,
            lifespan,
            replace=1,  # type: ignore[arg-type]
        )


def test_duplicate_registration_is_rejected(
    app: FastAPI,
    lifespan,
) -> None:
    with pytest.raises(
        SchedulerRuntimeLifespanIntegrationError,
        match="already registered",
    ):
        register_scheduler_runtime_lifespan(app, lifespan)


def test_replacement_is_allowed(
    app: FastAPI,
) -> None:
    original = get_scheduler_runtime_lifespan(app)

    replacement = create_scheduler_runtime_lifespan_integration()

    register_scheduler_runtime_lifespan(
        app,
        replacement,
        replace=True,
    )

    assert get_scheduler_runtime_lifespan(app) is replacement
    assert get_scheduler_runtime_lifespan(app) is not original


def test_get_lifespan(app: FastAPI, lifespan) -> None:
    assert get_scheduler_runtime_lifespan(app) is lifespan


def test_get_lifespan_rejects_missing_registration() -> None:
    app = FastAPI()

    with pytest.raises(
        SchedulerRuntimeLifespanIntegrationError,
        match="not registered",
    ):
        get_scheduler_runtime_lifespan(app)


def test_get_optional_lifespan_when_missing() -> None:
    assert get_scheduler_runtime_lifespan_optional(
        FastAPI()
    ) is None


def test_get_optional_lifespan_when_registered(
    app: FastAPI,
    lifespan,
) -> None:
    assert get_scheduler_runtime_lifespan_optional(app) is lifespan


def test_is_registered_when_missing() -> None:
    assert is_scheduler_runtime_lifespan_registered(
        FastAPI()
    ) is False


def test_is_registered_when_present(app: FastAPI) -> None:
    assert is_scheduler_runtime_lifespan_registered(app) is True


def test_status_reports_installed_runtime(app: FastAPI) -> None:
    assert get_scheduler_runtime_lifespan_status(app) == {
        "lifespan_registered": True,
        "runtime_installed": True,
        "ready_for_application_startup": True,
    }


def test_status_reports_missing_runtime(lifespan) -> None:
    app = FastAPI(lifespan=lifespan)
    register_scheduler_runtime_lifespan(app, lifespan)

    assert get_scheduler_runtime_lifespan_status(app) == {
        "lifespan_registered": True,
        "runtime_installed": False,
        "ready_for_application_startup": False,
    }


def test_remove_registration(app: FastAPI, lifespan) -> None:
    removed = remove_scheduler_runtime_lifespan(app)

    assert removed is lifespan
    assert not is_scheduler_runtime_lifespan_registered(app)


def test_remove_does_not_change_fastapi_lifespan(
    app: FastAPI,
    lifespan,
) -> None:
    remove_scheduler_runtime_lifespan(app)

    # Registration metadata is separate from FastAPI's
    # constructor-configured lifespan.
    assert app.router.lifespan_context is lifespan


def test_remove_rejects_missing_registration() -> None:
    with pytest.raises(
        SchedulerRuntimeLifespanIntegrationError,
        match="not registered",
    ):
        remove_scheduler_runtime_lifespan(FastAPI())


@pytest.mark.asyncio
async def test_lifespan_starts_and_stops_runtime(
    app: FastAPI,
    runtime: SchedulerRuntime,
    manager: FakeManager,
) -> None:
    async with app.router.lifespan_context(app):
        assert runtime.state == SchedulerLifecycleState.RUNNING
        assert runtime.is_running is True

    assert runtime.state == SchedulerLifecycleState.STOPPED
    assert manager.start_calls == 1
    assert manager.shutdown_calls == 1


@pytest.mark.asyncio
async def test_lifespan_executes_callbacks_in_order(
    runtime: SchedulerRuntime,
) -> None:
    events: list[str] = []

    def callback(name: str):
        def record(app: FastAPI) -> None:
            events.append(name)

        return record

    lifespan = create_scheduler_runtime_lifespan_integration(
        before_start=callback("before_start"),
        after_start=callback("after_start"),
        before_shutdown=callback("before_shutdown"),
        after_shutdown=callback("after_shutdown"),
    )

    app = FastAPI(lifespan=lifespan)
    install_scheduler_runtime(app, runtime)

    async with app.router.lifespan_context(app):
        events.append("application_running")

    assert events == [
        "before_start",
        "after_start",
        "application_running",
        "before_shutdown",
        "after_shutdown",
    ]


@pytest.mark.asyncio
async def test_lifespan_preserves_application_exception(
    app: FastAPI,
    runtime: SchedulerRuntime,
) -> None:
    with pytest.raises(RuntimeError, match="Application failed"):
        async with app.router.lifespan_context(app):
            raise RuntimeError("Application failed")

    assert runtime.state == SchedulerLifecycleState.STOPPED


@pytest.mark.asyncio
async def test_lifespan_start_failure(
    app: FastAPI,
    runtime: SchedulerRuntime,
    manager: FakeManager,
) -> None:
    manager.fail_start = True

    with pytest.raises(Exception):
        async with app.router.lifespan_context(app):
            pass

    assert runtime.state == SchedulerLifecycleState.STOPPED
    assert manager.start_calls == 1
    assert manager.shutdown_calls == 1


@pytest.mark.asyncio
async def test_lifespan_shutdown_failure(
    app: FastAPI,
    runtime: SchedulerRuntime,
    manager: FakeManager,
) -> None:
    manager.fail_shutdown = True

    with pytest.raises(Exception):
        async with app.router.lifespan_context(app):
            pass

    assert runtime.state == SchedulerLifecycleState.FAILED
    assert manager.start_calls == 1
    assert manager.shutdown_calls == 1


@pytest.mark.asyncio
async def test_registration_does_not_start_runtime(
    app: FastAPI,
    runtime: SchedulerRuntime,
    manager: FakeManager,
) -> None:
    assert runtime.state == SchedulerLifecycleState.STOPPED
    assert manager.start_calls == 0
    assert manager.shutdown_calls == 0


@pytest.mark.asyncio
async def test_removing_metadata_does_not_stop_runtime(
    app: FastAPI,
    runtime: SchedulerRuntime,
    manager: FakeManager,
) -> None:
    await runtime.start()

    remove_scheduler_runtime_lifespan(app)

    assert runtime.state == SchedulerLifecycleState.RUNNING
    assert manager.shutdown_calls == 0

    await runtime.shutdown()


@pytest.mark.asyncio
async def test_separate_applications_have_independent_lifespans(
    manager: FakeManager,
) -> None:
    first_runtime = SchedulerRuntime(
        manager,
        ScheduledTaskRegistry(),
    )
    second_runtime = SchedulerRuntime(
        manager,
        ScheduledTaskRegistry(),
    )

    first_lifespan = create_scheduler_runtime_lifespan_integration()
    second_lifespan = create_scheduler_runtime_lifespan_integration()

    first_app = FastAPI(lifespan=first_lifespan)
    second_app = FastAPI(lifespan=second_lifespan)

    install_scheduler_runtime(first_app, first_runtime)
    install_scheduler_runtime(second_app, second_runtime)

    register_scheduler_runtime_lifespan(first_app, first_lifespan)
    register_scheduler_runtime_lifespan(second_app, second_lifespan)

    assert get_scheduler_runtime_lifespan(first_app) is first_lifespan
    assert get_scheduler_runtime_lifespan(second_app) is second_lifespan

    async with first_app.router.lifespan_context(first_app):
        assert first_runtime.is_running
        assert not second_runtime.is_running

    assert first_runtime.state == SchedulerLifecycleState.STOPPED
    assert second_runtime.state == SchedulerLifecycleState.STOPPED
