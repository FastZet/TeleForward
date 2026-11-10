"""Database persistence for TeleForward scheduled jobs."""

from __future__ import annotations

import logging
from typing import Any, Callable, Sequence

from sqlalchemy import Boolean, JSON, String, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.services.scheduling.job_store import (
    ScheduledJobDefinition,
    ScheduledJobType,
)

logger = logging.getLogger(__name__)


class ScheduledJobRecord(Base):
    """SQLAlchemy model for persisted scheduled job definitions."""

    __tablename__ = "scheduled_jobs"

    job_id: Mapped[str] = mapped_column(
        String(128),
        primary_key=True,
    )

    task_name: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        index=True,
    )

    job_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )

    trigger_config: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )

    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        index=True,
    )

    job_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSON,
        nullable=False,
        default=dict,
    )


class ScheduledJobPersistenceError(RuntimeError):
    """Raised when scheduled-job persistence fails."""


class SQLAlchemyJobRepository:
    """Persist scheduled job definitions using SQLAlchemy.

    The repository receives an asynchronous session factory.
    Transaction ownership remains inside this repository.
    """

    def __init__(
        self,
        session_factory: Callable[[], AsyncSession],
    ) -> None:
        if not callable(session_factory):
            raise TypeError("session_factory must be callable")

        self._session_factory = session_factory

    async def save(
        self,
        definition: ScheduledJobDefinition,
    ) -> ScheduledJobDefinition:
        """Insert or update a scheduled job definition."""

        self._validate_definition(definition)

        try:
            async with self._session_factory() as session:
                async with session.begin():
                    record = await session.get(
                        ScheduledJobRecord,
                        definition.job_id,
                    )

                    if record is None:
                        record = ScheduledJobRecord(
                            job_id=definition.job_id,
                            task_name=definition.task_name,
                            job_type=definition.job_type.value,
                            trigger_config=dict(
                                definition.trigger_config
                            ),
                            enabled=definition.enabled,
                            job_metadata=dict(definition.metadata),
                        )
                        session.add(record)
                    else:
                        record.task_name = definition.task_name
                        record.job_type = definition.job_type.value
                        record.trigger_config = dict(
                            definition.trigger_config
                        )
                        record.enabled = definition.enabled
                        record.job_metadata = dict(
                            definition.metadata
                        )

            return definition

        except SQLAlchemyError as exc:
            logger.exception(
                "Failed to persist scheduled job %s",
                definition.job_id,
            )
            raise ScheduledJobPersistenceError(
                f"Could not save scheduled job {definition.job_id}"
            ) from exc

    async def get(
        self,
        job_id: str,
    ) -> ScheduledJobDefinition | None:
        """Retrieve a scheduled job by its identifier."""

        self._validate_job_id(job_id)

        try:
            async with self._session_factory() as session:
                record = await session.get(
                    ScheduledJobRecord,
                    job_id,
                )

                return (
                    self._to_definition(record)
                    if record is not None
                    else None
                )

        except SQLAlchemyError as exc:
            logger.exception(
                "Failed to retrieve scheduled job %s",
                job_id,
            )
            raise ScheduledJobPersistenceError(
                f"Could not retrieve scheduled job {job_id}"
            ) from exc

    async def list_all(
        self,
        *,
        enabled_only: bool = False,
    ) -> list[ScheduledJobDefinition]:
        """Retrieve all scheduled job definitions."""

        try:
            statement = select(ScheduledJobRecord).order_by(
                ScheduledJobRecord.job_id
            )

            if enabled_only:
                statement = statement.where(
                    ScheduledJobRecord.enabled.is_(True)
                )

            async with self._session_factory() as session:
                result = await session.scalars(statement)
                records = result.all()

                return [
                    self._to_definition(record)
                    for record in records
                ]

        except SQLAlchemyError as exc:
            logger.exception(
                "Failed to list scheduled jobs"
            )
            raise ScheduledJobPersistenceError(
                "Could not list scheduled jobs"
            ) from exc

    async def delete(
        self,
        job_id: str,
    ) -> bool:
        """Delete a scheduled job definition.

        Returns True when a record was deleted, otherwise False.
        """

        self._validate_job_id(job_id)

        try:
            async with self._session_factory() as session:
                async with session.begin():
                    record = await session.get(
                        ScheduledJobRecord,
                        job_id,
                    )

                    if record is None:
                        return False

                    await session.delete(record)

                return True

        except SQLAlchemyError as exc:
            logger.exception(
                "Failed to delete scheduled job %s",
                job_id,
            )
            raise ScheduledJobPersistenceError(
                f"Could not delete scheduled job {job_id}"
            ) from exc

    async def set_enabled(
        self,
        job_id: str,
        enabled: bool,
    ) -> ScheduledJobDefinition | None:
        """Update a job's enabled state."""

        self._validate_job_id(job_id)

        if not isinstance(enabled, bool):
            raise TypeError("enabled must be a boolean")

        try:
            async with self._session_factory() as session:
                async with session.begin():
                    record = await session.get(
                        ScheduledJobRecord,
                        job_id,
                    )

                    if record is None:
                        return None

                    record.enabled = enabled
                    await session.flush()

                    return self._to_definition(record)

        except SQLAlchemyError as exc:
            logger.exception(
                "Failed to update enabled state for job %s",
                job_id,
            )
            raise ScheduledJobPersistenceError(
                f"Could not update scheduled job {job_id}"
            ) from exc

    @staticmethod
    def _to_definition(
        record: ScheduledJobRecord,
    ) -> ScheduledJobDefinition:
        """Convert a database record into a domain definition."""

        try:
            return ScheduledJobDefinition(
                job_id=record.job_id,
                task_name=record.task_name,
                job_type=ScheduledJobType(record.job_type),
                trigger_config=dict(record.trigger_config or {}),
                enabled=record.enabled,
                metadata=dict(record.job_metadata or {}),
            )

        except (TypeError, ValueError, KeyError) as exc:
            raise ScheduledJobPersistenceError(
                f"Invalid persisted job definition: {record.job_id}"
            ) from exc

    @staticmethod
    def _validate_definition(
        definition: ScheduledJobDefinition,
    ) -> None:
        if not isinstance(definition, ScheduledJobDefinition):
            raise TypeError(
                "definition must be a ScheduledJobDefinition"
            )

    @staticmethod
    def _validate_job_id(job_id: str) -> None:
        if not isinstance(job_id, str) or not job_id.strip():
            raise ValueError("job_id cannot be empty")
