"""Asynchronous execution locks for TeleForward scheduling."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _LockEntry:
    """Internal lock entry with reference tracking."""

    lock: asyncio.Lock
    references: int = 0


class JobLockManager:
    """Manage per-job asynchronous execution locks.

    Locks are scoped to the current Python process and event loop.
    They do not provide distributed locking across multiple workers
    or application instances.
    """

    def __init__(self) -> None:
        self._locks: dict[str, _LockEntry] = {}
        self._guard = asyncio.Lock()

    @property
    def active_lock_count(self) -> int:
        """Return the number of currently registered job locks."""

        return len(self._locks)

    async def acquire(
        self,
        job_id: str,
        *,
        timeout_seconds: float | None = None,
    ) -> asyncio.Lock:
        """Acquire a lock for a job.

        The caller is responsible for releasing the returned lock.
        Prefer the `locked()` context manager for automatic cleanup.
        """

        self._validate_job_id(job_id)

        if timeout_seconds is not None:
            if (
                isinstance(timeout_seconds, bool)
                or not isinstance(timeout_seconds, (int, float))
                or timeout_seconds <= 0
            ):
                raise ValueError(
                    "timeout_seconds must be positive or None"
                )

        entry = await self._get_or_create_entry(job_id)

        try:
            if timeout_seconds is None:
                await entry.lock.acquire()
            else:
                await asyncio.wait_for(
                    entry.lock.acquire(),
                    timeout=float(timeout_seconds),
                )

            return entry.lock

        except BaseException:
            await self._release_reference(job_id, entry)
            raise

    async def release(
        self,
        job_id: str,
    ) -> None:
        """Release a previously acquired job lock."""

        self._validate_job_id(job_id)

        async with self._guard:
            entry = self._locks.get(job_id)

            if entry is None:
                raise RuntimeError(
                    f"No lock exists for job: {job_id}"
                )

            if not entry.lock.locked():
                raise RuntimeError(
                    f"Job lock is not acquired: {job_id}"
                )

            entry.lock.release()
            entry.references -= 1

            if entry.references == 0:
                self._locks.pop(job_id, None)

    @asynccontextmanager
    async def locked(
        self,
        job_id: str,
        *,
        timeout_seconds: float | None = None,
    ) -> AsyncIterator[None]:
        """Acquire and automatically release a job lock."""

        lock = await self.acquire(
            job_id,
            timeout_seconds=timeout_seconds,
        )

        try:
            yield
        finally:
            await self.release(job_id)

    async def is_locked(self, job_id: str) -> bool:
        """Check whether a job currently holds an execution lock."""

        self._validate_job_id(job_id)

        async with self._guard:
            entry = self._locks.get(job_id)
            return entry.lock.locked() if entry else False

    async def clear(self) -> None:
        """Remove all idle locks.

        Acquired locks are retained to avoid invalidating active
        execution references.
        """

        async with self._guard:
            idle_job_ids = [
                job_id
                for job_id, entry in self._locks.items()
                if not entry.lock.locked()
            ]

            for job_id in idle_job_ids:
                self._locks.pop(job_id, None)

    async def _get_or_create_entry(
        self,
        job_id: str,
    ) -> _LockEntry:
        """Get or create a lock entry and register a reference."""

        async with self._guard:
            entry = self._locks.get(job_id)

            if entry is None:
                entry = _LockEntry(lock=asyncio.Lock())
                self._locks[job_id] = entry

            entry.references += 1
            return entry

    async def _release_reference(
        self,
        job_id: str,
        entry: _LockEntry,
    ) -> None:
        """Release a reference when acquisition fails or is cancelled."""

        async with self._guard:
            current = self._locks.get(job_id)

            if current is not entry:
                return

            entry.references -= 1

            if entry.references <= 0 and not entry.lock.locked():
                self._locks.pop(job_id, None)

    @staticmethod
    def _validate_job_id(job_id: str) -> None:
        if not isinstance(job_id, str) or not job_id.strip():
            raise ValueError("job_id cannot be empty")
