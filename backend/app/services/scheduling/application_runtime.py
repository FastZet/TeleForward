"""Production construction of the application scheduling runtime."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from sqlalchemy import text

from app.core.config import get_settings
from app.services.scheduling.cleanup import SchedulingCleanupService
from app.services.scheduling.history import ExecutionHistoryRepository
from app.services.scheduling.manager import SchedulingManager
from app.services.scheduling.persistence import SQLAlchemyJobRepository
from app.services.scheduling.scheduler import SchedulerService
from app.services.scheduling.scheduler_runtime import SchedulerRuntime
from app.services.scheduling.scheduler_runtime_integration import (
    install_scheduler_runtime,
)
from app.services.scheduling.sqlalchemy_job_store import SQLAlchemyJobStore
from app.services.scheduling.tasks.factory import ScheduledTaskFactory
from app.services.scheduling.tasks.task_registry import ScheduledTaskRegistry


async def _database_health_check(engine: Any) -> dict[str, str]:
    """Check that the configured application database accepts queries."""
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))
    return {"status": "healthy"}


def build_application_scheduler(app: FastAPI) -> SchedulerRuntime:
    """Create and install the scheduler using app-owned database resources.

    Only cleanup and database health tasks are registered here. Business
    operations remain absent until their real service implementations are
    supplied; persisted jobs for absent operations fail restoration instead
    of silently running a successful no-op.
    """
    session_factory = getattr(app.state, "database_session_factory", None)
    engine = getattr(app.state, "database_engine", None)

    if not callable(session_factory) or engine is None:
        raise RuntimeError(
            "Database resources must be initialised before scheduler setup"
        )

    settings = get_settings()
    history_repository = ExecutionHistoryRepository(session_factory)
    cleanup_service = SchedulingCleanupService(
        history_repository=history_repository
    )
    job_store = SQLAlchemyJobStore(session_factory)
    scheduler = SchedulerService(timezone_name=settings.timezone)
    manager = SchedulingManager(
        scheduler=scheduler,
        job_store=job_store,
    )
    registry = ScheduledTaskRegistry()

    task_factory = ScheduledTaskFactory(
        cleanup_service,
        backup_operation=None,
        session_maintenance_operation=None,
        telegram_sync_operation=None,
        notification_dispatch_operation=None,
        forwarding_operation=None,
        backfill_operation=None,
        health_checks={
            "database": lambda: _database_health_check(engine),
        },
        history_repository=history_repository,
    )

    runtime = SchedulerRuntime(manager, registry)
    runtime.register_tasks(task_factory.build())

    return install_scheduler_runtime(app, runtime, replace=True)
