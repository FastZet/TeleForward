"""Scheduling manager for TeleForward."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.services.scheduling.base import BaseScheduledTask
from app.services.scheduling.job_store import (
    BaseJobStore,
    ScheduledJobDefinition,
    ScheduledJobType,
)
from app.services.scheduling.scheduler import SchedulerService

logger = logging.getLogger(__name__)

_JOB_OPTION_KEYS = {
    "max_instances",
    "coalesce",
    "misfire_grace_time",
}

_INTERVAL_TRIGGER_KEYS = {
    "weeks",
    "days",
    "hours",
    "minutes",
    "seconds",
    "start_date",
    "end_date",
    "jitter",
}

_CRON_TRIGGER_KEYS = {"expression", "jitter"}
_DATE_TRIGGER_KEYS = {"run_date"}


class SchedulingManager:
    """Coordinate scheduled job definitions and scheduler execution.

    The job store is the source of truth for job definitions. APScheduler
    holds the active in-process schedule derived from those definitions.
    """

    def __init__(
        self,
        *,
        scheduler: SchedulerService,
        job_store: BaseJobStore,
    ) -> None:
        self._scheduler = scheduler
        self._job_store = job_store
        self._initialised = False

    @property
    def is_initialised(self) -> bool:
        """Return whether stored jobs have been restored."""

        return self._initialised

    def register_task(self, task: BaseScheduledTask) -> None:
        """Register a task implementation with the scheduler."""

        self._scheduler.register_task(task)

    async def create_job(
        self,
        definition: ScheduledJobDefinition,
    ) -> ScheduledJobDefinition:
        """Persist and schedule a new job definition."""

        if not isinstance(definition, ScheduledJobDefinition):
            raise TypeError(
                "definition must be a ScheduledJobDefinition"
            )

        if await self._job_store.get(definition.job_id) is not None:
            raise ValueError(
                f"Scheduled job already exists: {definition.job_id}"
            )

        self._ensure_task_registered(definition.task_name)

        await self._job_store.add(definition)

        try:
            if definition.enabled:
                self._schedule_definition(definition)
        except Exception:
            await self._job_store.delete(definition.job_id)
            raise

        logger.info(
            "Created scheduled job: id=%s task=%s enabled=%s",
            definition.job_id,
            definition.task_name,
            definition.enabled,
        )

        return definition

    async def update_job(
        self,
        definition: ScheduledJobDefinition,
    ) -> ScheduledJobDefinition:
        """Update an existing job definition and its active schedule."""

        if not isinstance(definition, ScheduledJobDefinition):
            raise TypeError(
                "definition must be a ScheduledJobDefinition"
            )

        existing = await self._job_store.get(definition.job_id)

        if existing is None:
            raise KeyError(
                f"Scheduled job does not exist: {definition.job_id}"
            )

        self._ensure_task_registered(definition.task_name)

        if definition.created_at != existing.created_at:
            raise ValueError(
                "created_at cannot be changed when updating a job"
            )

        if definition.updated_at < existing.updated_at:
            raise ValueError(
                "updated_at cannot move backwards"
            )

        # Preserve the existing active job until the new definition has
        # been persisted successfully.
        await self._job_store.update(definition)

        try:
            self._scheduler.remove_job(definition.job_id)

            if definition.enabled:
                self._schedule_definition(definition)

        except Exception:
            # Restore the previous definition and schedule where possible.
            await self._job_store.update(existing)

            try:
                self._scheduler.remove_job(existing.job_id)
            except Exception:
                pass

            if existing.enabled:
                self._schedule_definition(existing)

            raise

        logger.info(
            "Updated scheduled job: id=%s task=%s enabled=%s",
            definition.job_id,
            definition.task_name,
            definition.enabled,
        )

        return definition

    async def delete_job(self, job_id: str) -> bool:
        """Remove a scheduled job from the scheduler and store."""

        self._validate_job_id(job_id)

        existing = await self._job_store.get(job_id)

        if existing is None:
            return False

        try:
            self._scheduler.remove_job(job_id)
        except Exception as exc:
            # APScheduler raises when the job is not currently scheduled.
            if exc.__class__.__name__ != "JobLookupError":
                raise

        deleted = await self._job_store.delete(job_id)

        if deleted:
            logger.info("Deleted scheduled job: id=%s", job_id)

        return deleted

    async def enable_job(
        self,
        job_id: str,
    ) -> ScheduledJobDefinition:
        """Enable a stored job and add it to the scheduler."""

        definition = await self._get_required_job(job_id)

        if definition.enabled:
            return definition

        updated = self._replace_definition(
            definition,
            enabled=True,
        )

        await self._job_store.update(updated)

        try:
            self._schedule_definition(updated)
        except Exception:
            await self._job_store.update(definition)
            raise

        logger.info("Enabled scheduled job: id=%s", job_id)
        return updated

    async def disable_job(
        self,
        job_id: str,
    ) -> ScheduledJobDefinition:
        """Disable a stored job and remove it from the scheduler."""

        definition = await self._get_required_job(job_id)

        if not definition.enabled:
            return definition

        updated = self._replace_definition(
            definition,
            enabled=False,
        )

        await self._job_store.update(updated)

        try:
            self._scheduler.remove_job(job_id)
        except Exception as exc:
            if exc.__class__.__name__ != "JobLookupError":
                await self._job_store.update(definition)
                raise

        logger.info("Disabled scheduled job: id=%s", job_id)
        return updated

    async def get_job(
        self,
        job_id: str,
    ) -> ScheduledJobDefinition | None:
        """Retrieve a stored job definition."""

        self._validate_job_id(job_id)
        return await self._job_store.get(job_id)

    async def list_jobs(
        self,
        *,
        enabled_only: bool = False,
    ) -> list[ScheduledJobDefinition]:
        """List stored job definitions."""

        return await self._job_store.list_all(
            enabled_only=enabled_only,
        )

    async def restore_jobs(self) -> list[str]:
        """Restore enabled job definitions into APScheduler.

        Returns the identifiers of jobs that could not be restored.
        Restoration does not start the scheduler; call start() separately.
        """

        failures: list[str] = []
        definitions = await self._job_store.list_all(
            enabled_only=True,
        )

        for definition in definitions:
            try:
                self._ensure_task_registered(definition.task_name)
                self._schedule_definition(definition)

            except Exception:
                failures.append(definition.job_id)
                logger.exception(
                    "Could not restore scheduled job: id=%s task=%s",
                    definition.job_id,
                    definition.task_name,
                )

        self._initialised = not failures

        logger.info(
            "Scheduled job restoration finished: restored=%d failed=%d",
            len(definitions) - len(failures),
            len(failures),
        )

        return failures

    def start(self, *, paused: bool = False) -> None:
        """Start the underlying scheduler."""

        if not self._initialised:
            raise RuntimeError(
                "Scheduled jobs must be restored before starting"
            )

        self._scheduler.start(paused=paused)

    def pause(self) -> None:
        """Pause all scheduled jobs."""

        self._scheduler.pause()

    def resume(self) -> None:
        """Resume all scheduled jobs."""

        self._scheduler.resume()

    def shutdown(self, *, wait: bool = True) -> None:
        """Shut down the underlying scheduler."""

        self._scheduler.shutdown(wait=wait)

    async def close(self) -> None:
        """Shut down the scheduler and release store resources."""

        self.shutdown(wait=True)
        await self._job_store.close()

    def _schedule_definition(
        self,
        definition: ScheduledJobDefinition,
    ) -> None:
        """Convert a stored definition into an APScheduler job."""

        if not definition.enabled:
            return

        config = dict(definition.trigger_config)

        job_options = {
            key: config.pop(key)
            for key in tuple(config)
            if key in _JOB_OPTION_KEYS
        }

        job_options.setdefault("max_instances", 1)
        job_options.setdefault("coalesce", True)
        job_options.setdefault("misfire_grace_time", 60)

        if definition.trigger_type == ScheduledJobType.INTERVAL:
            self._reject_unknown_keys(
                config,
                _INTERVAL_TRIGGER_KEYS,
                definition.trigger_type,
            )

            self._scheduler.add_interval_job(
                task_name=definition.task_name,
                job_id=definition.job_id,
                **config,
                **job_options,
            )

        elif definition.trigger_type == ScheduledJobType.CRON:
            self._reject_unknown_keys(
                config,
                _CRON_TRIGGER_KEYS,
                definition.trigger_type,
            )

            expression = config.pop("expression")

            self._scheduler.add_cron_job(
                task_name=definition.task_name,
                job_id=definition.job_id,
                expression=expression,
                **config,
                **job_options,
            )

        elif definition.trigger_type == ScheduledJobType.DATE:
            self._reject_unknown_keys(
                config,
                _DATE_TRIGGER_KEYS,
                definition.trigger_type,
            )

            run_date = config["run_date"]

            if isinstance(run_date, str):
                run_date = datetime.fromisoformat(run_date)

            self._scheduler.add_date_job(
                task_name=definition.task_name,
                job_id=definition.job_id,
                run_date=run_date,
                misfire_grace_time=job_options["misfire_grace_time"],
            )

        else:
            raise ValueError(
                f"Unsupported trigger type: {definition.trigger_type}"
            )

    def _ensure_task_registered(self, task_name: str) -> None:
        if task_name not in self._scheduler.registered_tasks:
            raise KeyError(
                f"Task implementation is not registered: {task_name}"
            )

    async def _get_required_job(
        self,
        job_id: str,
    ) -> ScheduledJobDefinition:
        self._validate_job_id(job_id)

        definition = await self._job_store.get(job_id)

        if definition is None:
            raise KeyError(
                f"Scheduled job does not exist: {job_id}"
            )

        return definition

    @staticmethod
    def _validate_job_id(job_id: str) -> None:
        if not isinstance(job_id, str) or not job_id.strip():
            raise ValueError("job_id cannot be empty")

    @staticmethod
    def _reject_unknown_keys(
        config: dict[str, Any],
        allowed_keys: set[str],
        trigger_type: ScheduledJobType,
    ) -> None:
        unknown = set(config) - allowed_keys

        if unknown:
            raise ValueError(
                f"Unsupported {trigger_type.value} configuration keys: "
                f"{', '.join(sorted(unknown))}"
            )

    @staticmethod
    def _replace_definition(
        definition: ScheduledJobDefinition,
        *,
        enabled: bool,
    ) -> ScheduledJobDefinition:
        return ScheduledJobDefinition(
            job_id=definition.job_id,
            task_name=definition.task_name,
            trigger_type=definition.trigger_type,
            trigger_config=definition.trigger_config,
            enabled=enabled,
            metadata=definition.metadata,
            created_at=definition.created_at,
            updated_at=datetime.now(timezone.utc),
        )
