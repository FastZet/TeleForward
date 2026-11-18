"""SQLAlchemy-backed job-store adapter for the scheduler manager."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.scheduling.job_store import (
    BaseJobStore,
    ScheduledJobDefinition,
)
from app.services.scheduling.persistence import SQLAlchemyJobRepository


class SQLAlchemyJobStore(BaseJobStore):
    """Adapt the database repository to the manager's job-store contract.

    The repository owns database sessions and transactions. This adapter
    supplies the strict add/update semantics and lifecycle expected by
    SchedulingManager.
    """

    def __init__(
        self,
        session_factory: Callable[[], AsyncSession],
    ) -> None:
        if not callable(session_factory):
            raise TypeError("session_factory must be callable")

        self._repository = SQLAlchemyJobRepository(session_factory)
        self._mutation_lock = asyncio.Lock()

    async def add(self, definition: ScheduledJobDefinition) -> None:
        """Insert a new definition, rejecting an existing identifier."""
        if not isinstance(definition, ScheduledJobDefinition):
            raise TypeError(
                "definition must be a ScheduledJobDefinition"
            )

        async with self._mutation_lock:
            if await self._repository.get(definition.job_id) is not None:
                raise ValueError(
                    f"Scheduled job already exists: {definition.job_id}"
                )

            await self._repository.save(definition)

    async def get(
        self,
        job_id: str,
    ) -> ScheduledJobDefinition | None:
        return await self._repository.get(job_id)

    async def list_all(
        self,
        *,
        enabled_only: bool = False,
    ) -> list[ScheduledJobDefinition]:
        return await self._repository.list_all(
            enabled_only=enabled_only
        )

    async def update(self, definition: ScheduledJobDefinition) -> None:
        """Replace an existing definition, rejecting unknown identifiers."""
        if not isinstance(definition, ScheduledJobDefinition):
            raise TypeError(
                "definition must be a ScheduledJobDefinition"
            )

        async with self._mutation_lock:
            if await self._repository.get(definition.job_id) is None:
                raise KeyError(
                    f"Scheduled job does not exist: {definition.job_id}"
                )

            await self._repository.save(definition)

    async def delete(self, job_id: str) -> bool:
        async with self._mutation_lock:
            return await self._repository.delete(job_id)

    async def close(self) -> None:
        """The app owns the shared engine and session factory."""
