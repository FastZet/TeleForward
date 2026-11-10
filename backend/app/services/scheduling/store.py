"""SQLAlchemy-backed job store for TeleForward scheduling."""

from __future__ import annotations

import copy
import logging
from typing import Any, Callable, Mapping

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.scheduling.job_store import (
    BaseJobStore,
    ScheduledJobDefinition,
    ScheduledJobType,
)
from app.services.scheduling.persistence import (
    ScheduledJobPersistenceError,
    ScheduledJobRecord,
)
from app.services.scheduling.serialization import (
    to_json_compatible,
)

logger = logging.getLogger(__name__)

_STORE_METADATA_KEY = "__teleforward_store_internal__"


class SQLAlchemyJobStore(BaseJobStore):
    """Persistent implementation of BaseJobStore.

    Each operation uses its own asynchronous database session.
    The caller supplies the session factory.
    """

    def __init__(
        self,
        session_factory: Callable[[], AsyncSession],
    ) -> None:
        if not callable(session_factory):
            raise TypeError("session_factory must be callable")

        self._session_factory = session_factory
        self._closed = False

    async def add(
        self,
        definition: ScheduledJobDefinition,
    ) -> None:
        """Insert a new scheduled job.

        Raises:
            TypeError: If the definition has an invalid type.
            ValueError: If the job ID already exists.
        """

        self._ensure_open()
        self._validate_definition(definition)

        try:
            async with self._session_factory() as session:
                async with session.begin():
                    existing = await session.get(
                        ScheduledJobRecord,
                        definition.job_id,
                    )

                    if existing is not None:
                        raise ValueError(
                            f"Scheduled job already exists: "
                            f"{definition.job_id}"
                        )

                    session.add(
                        self._to_record(definition)
                    )

                    await session.flush()

        except IntegrityError as exc:
            raise ValueError(
                f"Scheduled job already exists: {definition.job_id}"
            ) from exc

        except SQLAlchemyError as exc:
            logger.exception(
                "Failed to add scheduled job %s",
                definition.job_id,
            )
            raise ScheduledJobPersistenceError(
                f"Could not add scheduled job {definition.job_id}"
            ) from exc

    async def get(
        self,
        job_id: str,
    ) -> ScheduledJobDefinition | None:
        """Retrieve a scheduled job by ID."""

        self._ensure_open()
        self._validate_job_id(job_id)

        try:
            async with self._session_factory() as session:
                record = await session.get(
                    ScheduledJobRecord,
                    job_id,
                )

                if record is None:
                    return None

                return self._to_definition(record)

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
        """List scheduled jobs ordered by job ID."""

        self._ensure_open()

        if not isinstance(enabled_only, bool):
            raise TypeError("enabled_only must be a boolean")

        statement = select(ScheduledJobRecord).order_by(
            ScheduledJobRecord.job_id
        )

        if enabled_only:
            statement = statement.where(
                ScheduledJobRecord.enabled.is_(True)
            )

        try:
            async with self._session_factory() as session:
                result = await session.scalars(statement)
                records = result.all()

                return [
                    self._to_definition(record)
                    for record in records
                ]

        except SQLAlchemyError as exc:
            logger.exception("Failed to list scheduled jobs")
            raise ScheduledJobPersistenceError(
                "Could not list scheduled jobs"
            ) from exc

    async def update(
        self,
        definition: ScheduledJobDefinition,
    ) -> None:
        """Update an existing scheduled job.

        Raises:
            TypeError: If the definition has an invalid type.
            KeyError: If the job does not exist.
        """

        self._ensure_open()
        self._validate_definition(definition)

        try:
            async with self._session_factory() as session:
                async with session.begin():
                    record = await session.get(
                        ScheduledJobRecord,
                        definition.job_id,
                    )

                    if record is None:
                        raise KeyError(
                            f"Scheduled job does not exist: "
                            f"{definition.job_id}"
                        )

                    self._update_record(
                        record,
                        definition,
                    )

                    await session.flush()

        except SQLAlchemyError as exc:
            logger.exception(
                "Failed to update scheduled job %s",
                definition.job_id,
            )
            raise ScheduledJobPersistenceError(
                f"Could not update scheduled job {definition.job_id}"
            ) from exc

    async def delete(
        self,
        job_id: str,
    ) -> bool:
        """Delete a scheduled job.

        Returns False when the job does not exist.
        """

        self._ensure_open()
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

    async def close(self) -> None:
        """Close the store.

        Sessions are created and closed per operation, so the store
        does not own a persistent connection or engine to dispose.
        """

        self._closed = True

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("Scheduled job store is closed")

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

    @staticmethod
    def _encode_metadata(
        definition: ScheduledJobDefinition,
    ) -> dict[str, Any]:
        """Encode user metadata and preserve definition timestamps.

        File 214's initial database model does not have dedicated
        created_at and updated_at columns. Until a migration adds
        those columns, timestamps are stored in a reserved envelope.
        """

        metadata = copy.deepcopy(dict(definition.metadata))

        if _STORE_METADATA_KEY in metadata:
            raise ValueError(
                f"Metadata key {_STORE_METADATA_KEY!r} is reserved"
            )

        envelope = {
            "created_at": definition.created_at.isoformat(),
            "updated_at": definition.updated_at.isoformat(),
        }

        encoded = {
            _STORE_METADATA_KEY: envelope,
            "values": metadata,
        }

        result = to_json_compatible(encoded)

        if not isinstance(result, dict):
            raise TypeError("Encoded metadata must be a dictionary")

        return result

    @staticmethod
    def _decode_metadata(
        stored: Mapping[str, Any] | None,
    ) -> tuple[dict[str, Any], dict[str, str]]:
        """Separate user metadata from internal timestamp metadata."""

        if not stored:
            return {}, {}

        if not isinstance(stored, Mapping):
            raise ScheduledJobPersistenceError(
                "Persisted job metadata must be a mapping"
            )

        envelope = stored.get(_STORE_METADATA_KEY, {})
        values = stored.get("values", {})

        if not isinstance(envelope, Mapping):
            raise ScheduledJobPersistenceError(
                "Invalid internal job metadata envelope"
            )

        if not isinstance(values, Mapping):
            raise ScheduledJobPersistenceError(
                "Persisted user metadata must be a mapping"
            )

        timestamps: dict[str, str] = {}

        for name in ("created_at", "updated_at"):
            value = envelope.get(name)

            if value is not None:
                if not isinstance(value, str):
                    raise ScheduledJobPersistenceError(
                        f"Invalid persisted timestamp: {name}"
                    )
                timestamps[name] = value

        return copy.deepcopy(dict(values)), timestamps

    @classmethod
    def _to_record(
        cls,
        definition: ScheduledJobDefinition,
    ) -> ScheduledJobRecord:
        """Convert a domain definition into a database record."""

        trigger_config = to_json_compatible(
            dict(definition.trigger_config)
        )

        if not isinstance(trigger_config, dict):
            raise TypeError("trigger_config must serialize to a dictionary")

        return ScheduledJobRecord(
            job_id=definition.job_id,
            task_name=definition.task_name,
            job_type=definition.trigger_type.value,
            trigger_config=trigger_config,
            enabled=definition.enabled,
            job_metadata=cls._encode_metadata(definition),
        )

    @classmethod
    def _update_record(
        cls,
        record: ScheduledJobRecord,
        definition: ScheduledJobDefinition,
    ) -> None:
        """Update the mutable database fields of a job record."""

        replacement = cls._to_record(definition)

        record.task_name = replacement.task_name
        record.job_type = replacement.job_type
        record.trigger_config = replacement.trigger_config
        record.enabled = replacement.enabled
        record.job_metadata = replacement.job_metadata

    @classmethod
    def _to_definition(
        cls,
        record: ScheduledJobRecord,
    ) -> ScheduledJobDefinition:
        """Convert a database record into a domain definition."""

        from datetime import datetime

        metadata, timestamps = cls._decode_metadata(
            record.job_metadata
        )

        try:
            created_at = datetime.fromisoformat(
                timestamps["created_at"]
            ) if "created_at" in timestamps else None

            updated_at = datetime.fromisoformat(
                timestamps["updated_at"]
            ) if "updated_at" in timestamps else None

            return ScheduledJobDefinition(
                job_id=record.job_id,
                task_name=record.task_name,
                trigger_type=ScheduledJobType(record.job_type),
                trigger_config=copy.deepcopy(
                    record.trigger_config or {}
                ),
                enabled=record.enabled,
                metadata=metadata,
                **(
                    {"created_at": created_at}
                    if created_at is not None
                    else {}
                ),
                **(
                    {"updated_at": updated_at}
                    if updated_at is not None
                    else {}
                ),
            )

        except (TypeError, ValueError, KeyError) as exc:
            raise ScheduledJobPersistenceError(
                f"Invalid persisted job definition: {record.job_id}"
            ) from exc
