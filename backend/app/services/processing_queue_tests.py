"""Persistence and lease tests for ProcessingQueueService."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database.base import Base
from app.models.processing_queue import (
    ProcessingQueue,
    QueueJobStatus,
    QueueJobType,
)
from app.services.processing_queue import (
    ProcessingQueueService,
    QueueLeaseError,
)
from app.services.processing_queue_worker import ProcessingQueueWorker

QueueScenario = Callable[[ProcessingQueueService], Awaitable[None]]


async def _run_scenario(
    database_url: str,
    scenario: QueueScenario,
    *,
    queue_options: dict | None = None,
) -> None:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(
                lambda sync_connection: Base.metadata.create_all(
                    bind=sync_connection,
                    tables=[ProcessingQueue.__table__],
                )
            )
        session_factory = async_sessionmaker(
            engine,
            expire_on_commit=False,
        )
        async with session_factory() as session:
            await scenario(
                ProcessingQueueService(session, **(queue_options or {}))
            )
    finally:
        await engine.dispose()


async def _run_worker_scenario(
    handler: Callable,
    *,
    job_type: QueueJobType = QueueJobType.PROCESS_MESSAGE,
    lease_duration: timedelta = timedelta(minutes=2),
    heartbeat_interval: float = 30.0,
) -> tuple[QueueJobStatus, int, str | None]:
    engine = create_async_engine(_database_url())
    try:
        async with engine.begin() as connection:
            await connection.run_sync(
                lambda sync_connection: Base.metadata.create_all(
                    bind=sync_connection,
                    tables=[ProcessingQueue.__table__],
                )
            )
        session_factory = async_sessionmaker(
            engine,
            expire_on_commit=False,
        )
        async with session_factory() as session:
            queue = ProcessingQueueService(session)
            queued, _ = await queue.enqueue(
                job_type,
                {"message_id": 42},
            )
            job_id = queued.id
            await session.commit()

        worker = ProcessingQueueWorker(
            session_factory,
            worker_id="worker-test",
            handlers={job_type: handler},
            lease_duration=lease_duration,
            heartbeat_interval=heartbeat_interval,
        )
        assert await worker.run_once() is True

        async with session_factory() as session:
            job = await session.get(ProcessingQueue, job_id)
            assert job is not None
            return job.status, job.attempts, job.last_error
    finally:
        await engine.dispose()


def _database_url() -> str:
    return "sqlite+aiosqlite:///:memory:"


def test_enqueue_deduplicates_retries():
    async def scenario(queue: ProcessingQueueService) -> None:
        first, inserted_first = await queue.enqueue(
            QueueJobType.PROCESS_MESSAGE,
            {"message_id": 42},
            deduplication_key="message:42",
        )
        second, inserted_second = await queue.enqueue(
            QueueJobType.PROCESS_MESSAGE,
            {"message_id": 99},
            deduplication_key="message:42",
        )

        assert inserted_first is True
        assert inserted_second is False
        assert second.id == first.id
        assert second.payload == {"message_id": 42}

    asyncio.run(_run_scenario(_database_url(), scenario))


def test_claim_complete_and_reject_non_owner():
    now = datetime(2026, 11, 17, tzinfo=timezone.utc)

    async def scenario(queue: ProcessingQueueService) -> None:
        queued, _ = await queue.enqueue(
            QueueJobType.FORWARD_MESSAGE,
            {"source": 1},
            available_at=now,
        )
        claimed = await queue.claim_one("worker-a", now=now)
        assert claimed is not None
        assert claimed.id == queued.id
        assert claimed.status is QueueJobStatus.PROCESSING
        assert claimed.attempts == 1
        assert await queue.claim_one("worker-b", now=now) is None

        with pytest.raises(QueueLeaseError):
            await queue.complete(claimed.id, "worker-b", now=now)

        completed = await queue.complete(claimed.id, "worker-a", now=now)
        assert completed.status is QueueJobStatus.COMPLETED
        assert completed.locked_by is None

    asyncio.run(_run_scenario(_database_url(), scenario))


def test_failure_retries_then_moves_to_dead_letter():
    now = datetime(2026, 11, 17, tzinfo=timezone.utc)

    async def scenario(queue: ProcessingQueueService) -> None:
        await queue.enqueue(
            QueueJobType.PROCESS_MESSAGE,
            {"message_id": 7},
            max_attempts=2,
            available_at=now,
        )

        first_attempt = await queue.claim_one("worker", now=now)
        assert first_attempt is not None
        retried = await queue.fail(
            first_attempt.id,
            "worker",
            "temporary",
            now=now,
        )
        assert retried.status is QueueJobStatus.PENDING
        retry_at = retried.available_at
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=timezone.utc)
        assert retry_at == now + timedelta(seconds=2)

        second_attempt = await queue.claim_one(
            "worker",
            now=now + timedelta(seconds=2),
        )
        assert second_attempt is not None
        dead_letter = await queue.fail(
            second_attempt.id,
            "worker",
            "permanent",
            now=now + timedelta(seconds=2),
        )
        assert dead_letter.status is QueueJobStatus.DEAD_LETTER
        completed_at = dead_letter.completed_at
        if completed_at is not None and completed_at.tzinfo is None:
            completed_at = completed_at.replace(tzinfo=timezone.utc)
        assert completed_at == now + timedelta(seconds=2)

    asyncio.run(
        _run_scenario(
            _database_url(),
            scenario,
            queue_options={
                "base_retry_delay": timedelta(seconds=2),
                "max_retry_delay": timedelta(seconds=5),
            },
        )
    )


def test_expired_lease_can_be_reclaimed_by_another_worker():
    now = datetime(2026, 11, 17, tzinfo=timezone.utc)

    async def scenario(queue: ProcessingQueueService) -> None:
        await queue.enqueue(
            QueueJobType.PROCESS_MESSAGE,
            {"message_id": 8},
            available_at=now,
        )
        first = await queue.claim_one(
            "worker-a",
            lease_duration=timedelta(seconds=10),
            now=now,
        )
        assert first is not None

        reclaimed = await queue.claim_one(
            "worker-b",
            now=now + timedelta(seconds=11),
        )
        assert reclaimed is not None
        assert reclaimed.id == first.id
        assert reclaimed.locked_by == "worker-b"
        assert reclaimed.attempts == 2

        with pytest.raises(QueueLeaseError):
            await queue.complete(first.id, "worker-a", now=now)

    asyncio.run(_run_scenario(_database_url(), scenario))


def test_release_worker_makes_lease_immediately_available():
    now = datetime(2026, 11, 17, tzinfo=timezone.utc)

    async def scenario(queue: ProcessingQueueService) -> None:
        await queue.enqueue(
            QueueJobType.PROCESS_MESSAGE,
            {"message_id": 9},
            available_at=now,
        )
        claimed = await queue.claim_one("worker-a", now=now)
        assert claimed is not None

        assert await queue.release_worker("worker-a", now=now) == 1
        next_claim = await queue.claim_one("worker-b", now=now)
        assert next_claim is not None
        assert next_claim.id == claimed.id

    asyncio.run(_run_scenario(_database_url(), scenario))


def test_worker_dispatches_job_and_renews_long_running_lease():
    received: list[int] = []

    async def handler(job) -> None:
        received.append(job.payload["message_id"])
        await asyncio.sleep(0.06)

    result = asyncio.run(
        _run_worker_scenario(
            handler,
            lease_duration=timedelta(seconds=0.2),
            heartbeat_interval=0.03,
        )
    )

    assert received == [42]
    assert result == (QueueJobStatus.COMPLETED, 1, None)


def test_worker_records_failure_without_storing_exception_details():
    async def handler(_job) -> None:
        raise RuntimeError("sensitive error detail")

    result = asyncio.run(_run_worker_scenario(handler))

    assert result == (QueueJobStatus.PENDING, 1, "RuntimeError")

