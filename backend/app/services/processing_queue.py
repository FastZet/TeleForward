"""Transactional access to TeleForward's persistent work queue."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, case, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.processing_queue import (
    ProcessingQueue,
    QueueJobStatus,
    QueueJobType,
)


class QueueLeaseError(RuntimeError):
    """Raised when a worker changes a job it does not currently own."""


class ProcessingQueueService:
    """Enqueue, lease, retry, and complete durable background work.

    The caller owns the ``AsyncSession`` transaction. In particular, a
    worker must commit each lease/state transition before doing external
    work so another process cannot claim the same job.
    """

    def __init__(
        self,
        session: AsyncSession,
        *,
        base_retry_delay: timedelta = timedelta(seconds=5),
        max_retry_delay: timedelta = timedelta(hours=1),
    ) -> None:
        if base_retry_delay <= timedelta(0):
            raise ValueError("base_retry_delay must be positive")
        if max_retry_delay < base_retry_delay:
            raise ValueError("max_retry_delay must be >= base_retry_delay")
        self._session = session
        self._base_retry_delay = base_retry_delay
        self._max_retry_delay = max_retry_delay

    async def enqueue(
        self,
        job_type: QueueJobType,
        payload: dict[str, Any],
        *,
        deduplication_key: str | None = None,
        forwarding_rule_id: int | None = None,
        message_id: int | None = None,
        backfill_job_id: int | None = None,
        priority: int = 100,
        available_at: datetime | None = None,
        max_attempts: int = 3,
    ) -> tuple[ProcessingQueue, bool]:
        """Insert a job, returning ``(job, inserted)``.

        A duplicate idempotency key returns the original row. SQLite and
        PostgreSQL conflict handling makes this safe under concurrent
        enqueue calls; no callback is run inside the database transaction.
        """
        if not isinstance(job_type, QueueJobType):
            raise TypeError("job_type must be a QueueJobType")
        if not isinstance(payload, dict):
            raise TypeError("payload must be a dictionary")
        if priority < 0:
            raise ValueError("priority cannot be negative")
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        if deduplication_key is not None and not deduplication_key.strip():
            raise ValueError("deduplication_key cannot be blank")
        if deduplication_key is not None:
            deduplication_key = deduplication_key.strip()

        now = datetime.now(timezone.utc)
        scheduled_at = available_at or now
        if scheduled_at.tzinfo is None:
            raise ValueError("available_at must be timezone-aware")

        values = {
            "job_type": job_type,
            "status": QueueJobStatus.PENDING,
            "priority": priority,
            "payload": payload,
            "deduplication_key": deduplication_key,
            "forwarding_rule_id": forwarding_rule_id,
            "message_id": message_id,
            "backfill_job_id": backfill_job_id,
            "available_at": scheduled_at,
            "attempts": 0,
            "max_attempts": max_attempts,
        }

        dialect_name = self._session.bind.dialect.name  # type: ignore[union-attr]
        if dialect_name == "sqlite":
            statement = sqlite_insert(ProcessingQueue).values(**values)
        elif dialect_name == "postgresql":
            statement = pg_insert(ProcessingQueue).values(**values)
        else:
            raise RuntimeError(
                f"Persistent queue does not support database dialect {dialect_name!r}"
            )

        statement = statement.on_conflict_do_nothing(
            index_elements=[ProcessingQueue.deduplication_key]
        ).returning(ProcessingQueue.id)
        inserted_id = (await self._session.execute(statement)).scalar_one_or_none()
        inserted = inserted_id is not None

        if inserted:
            job = await self._session.get(ProcessingQueue, inserted_id)
        else:
            job = await self._session.scalar(
                select(ProcessingQueue).where(
                    ProcessingQueue.deduplication_key == deduplication_key
                )
            )

        if job is None:
            raise RuntimeError("Queue insert completed without a readable job")
        return job, inserted

    async def claim_one(
        self,
        worker_id: str,
        *,
        lease_duration: timedelta = timedelta(minutes=2),
        job_types: set[QueueJobType] | None = None,
        now: datetime | None = None,
    ) -> ProcessingQueue | None:
        """Atomically lease the highest-priority available job."""
        worker_id = worker_id.strip()
        if not worker_id:
            raise ValueError("worker_id cannot be blank")
        if len(worker_id) > 128:
            raise ValueError("worker_id cannot exceed 128 characters")
        if lease_duration <= timedelta(0):
            raise ValueError("lease_duration must be positive")

        current_time = now or datetime.now(timezone.utc)
        if current_time.tzinfo is None:
            raise ValueError("now must be timezone-aware")

        await self._dead_letter_expired_jobs(current_time)

        available = or_(
            and_(
                ProcessingQueue.status == QueueJobStatus.PENDING,
                ProcessingQueue.available_at <= current_time,
            ),
            and_(
                ProcessingQueue.status == QueueJobStatus.PROCESSING,
                ProcessingQueue.locked_until <= current_time,
            ),
        )
        candidates = select(ProcessingQueue.id).where(
            available,
            ProcessingQueue.attempts < ProcessingQueue.max_attempts,
        )
        if job_types is not None:
            if not job_types:
                return None
            candidates = candidates.where(ProcessingQueue.job_type.in_(job_types))
        candidates = candidates.order_by(
            ProcessingQueue.priority.asc(),
            ProcessingQueue.created_at.asc(),
            ProcessingQueue.id.asc(),
        ).limit(1)
        if self._session.bind.dialect.name == "postgresql":  # type: ignore[union-attr]
            candidates = candidates.with_for_update(skip_locked=True)

        candidate_id = (await self._session.execute(candidates)).scalar_one_or_none()
        if candidate_id is None:
            return None

        claim = (
            update(ProcessingQueue)
            .where(
                ProcessingQueue.id == candidate_id,
                available,
                ProcessingQueue.attempts < ProcessingQueue.max_attempts,
            )
            .values(
                status=QueueJobStatus.PROCESSING,
                locked_by=worker_id,
                locked_until=current_time + lease_duration,
                started_at=current_time,
                attempts=ProcessingQueue.attempts + 1,
            )
            .returning(ProcessingQueue.id)
        )
        claimed_id = (await self._session.execute(claim)).scalar_one_or_none()
        if claimed_id is None:
            return None
        return await self._session.get(ProcessingQueue, claimed_id)

    async def complete(
        self,
        job_id: int,
        worker_id: str,
        *,
        now: datetime | None = None,
    ) -> ProcessingQueue:
        """Mark a leased job completed and clear its worker lease."""
        current_time = now or datetime.now(timezone.utc)
        self._validate_aware(current_time, "now")
        job = await self._owned_job(job_id, worker_id, current_time)
        job.status = QueueJobStatus.COMPLETED
        job.completed_at = current_time
        job.locked_by = None
        job.locked_until = None
        job.last_error = None
        await self._session.flush()
        return job

    async def fail(
        self,
        job_id: int,
        worker_id: str,
        error: str,
        *,
        now: datetime | None = None,
    ) -> ProcessingQueue:
        """Retry a failed job with capped exponential backoff."""
        if not error or not error.strip():
            raise ValueError("error must be a non-empty string")
        current_time = now or datetime.now(timezone.utc)
        self._validate_aware(current_time, "now")
        job = await self._owned_job(job_id, worker_id, current_time)
        job.last_error = error.strip()
        job.locked_by = None
        job.locked_until = None
        if job.attempts >= job.max_attempts:
            job.status = QueueJobStatus.DEAD_LETTER
            job.completed_at = current_time
        else:
            job.status = QueueJobStatus.PENDING
            delay = self._base_retry_delay * (
                2 ** min(max(job.attempts - 1, 0), 30)
            )
            job.available_at = current_time + min(delay, self._max_retry_delay)
        await self._session.flush()
        return job

    async def release_worker(
        self,
        worker_id: str,
        *,
        now: datetime | None = None,
    ) -> int:
        """Return a worker's unfinished leases to the durable queue."""
        if not worker_id or not worker_id.strip():
            raise ValueError("worker_id cannot be blank")
        current_time = now or datetime.now(timezone.utc)
        expired = await self._session.execute(
            update(ProcessingQueue)
            .where(
                ProcessingQueue.status == QueueJobStatus.PROCESSING,
                ProcessingQueue.locked_by == worker_id,
            )
            .values(
                status=case(
                    (
                        ProcessingQueue.attempts >= ProcessingQueue.max_attempts,
                        QueueJobStatus.DEAD_LETTER,
                    ),
                    else_=QueueJobStatus.PENDING,
                ),
                available_at=current_time,
                locked_by=None,
                locked_until=None,
                completed_at=case(
                    (
                        ProcessingQueue.attempts >= ProcessingQueue.max_attempts,
                        current_time,
                    ),
                    else_=None,
                ),
            )
            .returning(ProcessingQueue.id)
        )
        return len(expired.scalars().all())

    async def _owned_job(
        self,
        job_id: int,
        worker_id: str,
        now: datetime,
    ) -> ProcessingQueue:
        job = await self._session.scalar(
            select(ProcessingQueue)
            .where(
                ProcessingQueue.id == job_id,
                ProcessingQueue.status == QueueJobStatus.PROCESSING,
                ProcessingQueue.locked_by == worker_id,
                ProcessingQueue.locked_until > now,
            )
            .with_for_update()
        )
        if job is None:
            raise QueueLeaseError(
                "Queue job is not processing under a current worker lease"
            )
        return job

    @staticmethod
    def _validate_aware(value: datetime, name: str) -> None:
        if value.tzinfo is None:
            raise ValueError(f"{name} must be timezone-aware")

    async def _dead_letter_expired_jobs(self, now: datetime) -> None:
        """Close expired leases whose retry budget has been exhausted."""
        await self._session.execute(
            update(ProcessingQueue)
            .where(
                ProcessingQueue.status == QueueJobStatus.PROCESSING,
                ProcessingQueue.locked_until <= now,
                ProcessingQueue.attempts >= ProcessingQueue.max_attempts,
            )
            .values(
                status=QueueJobStatus.DEAD_LETTER,
                completed_at=now,
                locked_by=None,
                locked_until=None,
                last_error=func.coalesce(
                    ProcessingQueue.last_error,
                    "Worker lease expired after the final attempt",
                ),
            )
        )

