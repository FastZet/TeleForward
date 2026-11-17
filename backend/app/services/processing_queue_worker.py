"""Async worker that leases and dispatches persistent queue jobs."""

from __future__ import annotations

import asyncio
import copy
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import timedelta
from types import MappingProxyType
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.processing_queue import ProcessingQueue, QueueJobType
from app.services.processing_queue import (
    ProcessingQueueService,
    QueueLeaseError,
)

logger = logging.getLogger(__name__)

QueueJobHandler = Callable[["QueueJobEnvelope"], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class QueueJobEnvelope:
    """Immutable snapshot passed to a job handler."""

    id: int
    job_type: QueueJobType
    payload: Mapping[str, Any]
    forwarding_rule_id: int | None
    message_id: int | None
    backfill_job_id: int | None
    attempt: int

    @classmethod
    def from_model(cls, job: ProcessingQueue) -> "QueueJobEnvelope":
        """Copy a claimed row so handlers do not retain a session-bound ORM object."""
        return cls(
            id=job.id,
            job_type=job.job_type,
            payload=MappingProxyType(copy.deepcopy(job.payload)),
            forwarding_rule_id=job.forwarding_rule_id,
            message_id=job.message_id,
            backfill_job_id=job.backfill_job_id,
            attempt=job.attempts,
        )


class ProcessingQueueWorker:
    """Consume supported jobs with committed leases and renewable ownership.

    Delivery is at least once: if the process stops after a handler performs
    its external side effect but before completion is recorded, the job can
    run again after its lease expires. Handlers must therefore be idempotent.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        worker_id: str,
        handlers: Mapping[QueueJobType, QueueJobHandler],
        poll_interval: float = 1.0,
        lease_duration: timedelta = timedelta(minutes=2),
        heartbeat_interval: float = 30.0,
    ) -> None:
        if not callable(session_factory):
            raise TypeError("session_factory must be callable")
        worker_id = worker_id.strip()
        if not worker_id or len(worker_id) > 128:
            raise ValueError("worker_id must contain 1 to 128 characters")
        if not isinstance(handlers, Mapping) or not handlers:
            raise ValueError("handlers must contain at least one job handler")
        if any(not isinstance(kind, QueueJobType) for kind in handlers):
            raise TypeError("handler keys must be QueueJobType values")
        if any(not callable(handler) for handler in handlers.values()):
            raise TypeError("every queue job handler must be callable")
        if poll_interval <= 0:
            raise ValueError("poll_interval must be positive")
        if lease_duration <= timedelta(0):
            raise ValueError("lease_duration must be positive")
        if heartbeat_interval <= 0:
            raise ValueError("heartbeat_interval must be positive")
        if timedelta(seconds=heartbeat_interval) >= lease_duration:
            raise ValueError("heartbeat_interval must be shorter than the lease")

        self._session_factory = session_factory
        self._worker_id = worker_id
        self._handlers = dict(handlers)
        self._job_types = set(handlers)
        self._poll_interval = poll_interval
        self._lease_duration = lease_duration
        self._heartbeat_interval = heartbeat_interval
        self._stop_event = asyncio.Event()

    async def run_once(self) -> bool:
        """Process one available job; return false when none are available."""
        async with self._session_factory() as session:
            queue = ProcessingQueueService(session)
            job = await queue.claim_one(
                self._worker_id,
                lease_duration=self._lease_duration,
                job_types=self._job_types,
            )
            await session.commit()

        if job is None:
            return False

        envelope = QueueJobEnvelope.from_model(job)
        handler = self._handlers[envelope.job_type]

        try:
            await self._run_with_heartbeat(envelope, handler)
        except asyncio.CancelledError:
            raise
        except QueueLeaseError:
            logger.warning(
                "Queue job lease was lost while running: job_id=%s worker_id=%s",
                envelope.id,
                self._worker_id,
            )
            return True
        except Exception as exc:
            logger.exception(
                "Queue job handler failed: job_id=%s type=%s attempt=%s",
                envelope.id,
                envelope.job_type.value,
                envelope.attempt,
            )
            await self._record_failure(envelope, exc)
            return True

        try:
            async with self._session_factory() as session:
                queue = ProcessingQueueService(session)
                await queue.complete(envelope.id, self._worker_id)
                await session.commit()
        except QueueLeaseError:
            logger.warning(
                "Queue job completed after its lease was lost: job_id=%s worker_id=%s",
                envelope.id,
                self._worker_id,
            )
        return True

    async def run(self) -> None:
        """Poll until stopped, releasing outstanding leases on shutdown."""
        self._stop_event.clear()
        try:
            while not self._stop_event.is_set():
                processed = await self.run_once()
                if not processed:
                    try:
                        await asyncio.wait_for(
                            self._stop_event.wait(),
                            timeout=self._poll_interval,
                        )
                    except asyncio.TimeoutError:
                        pass
        finally:
            await self._release_leases()

    def stop(self) -> None:
        """Request a graceful stop after the active job finishes."""
        self._stop_event.set()

    async def _run_with_heartbeat(
        self,
        job: QueueJobEnvelope,
        handler: QueueJobHandler,
    ) -> None:
        task = asyncio.create_task(
            handler(job),
            name=f"processing-queue-job-{job.id}",
        )
        try:
            while not task.done():
                done, _pending = await asyncio.wait(
                    {task},
                    timeout=self._heartbeat_interval,
                )
                if done:
                    break
                await self._renew_lease(job.id)
            await task
        except BaseException:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            raise

    async def _renew_lease(self, job_id: int) -> None:
        async with self._session_factory() as session:
            queue = ProcessingQueueService(session)
            await queue.extend_lease(
                job_id,
                self._worker_id,
                lease_duration=self._lease_duration,
            )
            await session.commit()

    async def _record_failure(
        self,
        job: QueueJobEnvelope,
        error: Exception,
    ) -> None:
        # Persist the exception type only; third-party error text can contain
        # credentials, message contents, or other sensitive Telegram data.
        safe_error = type(error).__name__
        try:
            async with self._session_factory() as session:
                queue = ProcessingQueueService(session)
                await queue.fail(job.id, self._worker_id, safe_error)
                await session.commit()
        except QueueLeaseError:
            logger.warning(
                "Could not record failed queue job because its lease was lost: "
                "job_id=%s worker_id=%s",
                job.id,
                self._worker_id,
            )

    async def _release_leases(self) -> None:
        async with self._session_factory() as session:
            queue = ProcessingQueueService(session)
            await queue.release_worker(self._worker_id)
            await session.commit()

