
"""
TeleForward persistent processing queue database model.

Stores background jobs, execution state, retry information
and worker leases for reliable job processing.
"""

from datetime import datetime
from enum import Enum

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum as SQLAlchemyEnum,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, PrimaryKeyMixin, TimestampMixin


class QueueJobType(str, Enum):
    """Supported background job categories."""

    PROCESS_MESSAGE = "process_message"
    FORWARD_MESSAGE = "forward_message"
    SYNC_EDIT = "sync_edit"
    SYNC_DELETE = "sync_delete"
    BACKFILL = "backfill"
    CLEANUP = "cleanup"
    BACKUP = "backup"
    CUSTOM = "custom"


class QueueJobStatus(str, Enum):
    """Persistent queue job execution states."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    DEAD_LETTER = "dead_letter"


class ProcessingQueue(Base, PrimaryKeyMixin, TimestampMixin):
    """A persistent background-processing job."""

    __tablename__ = "processing_queue"

    __table_args__ = (
        CheckConstraint(
            "priority >= 0",
            name="ck_processing_queue_priority_nonnegative",
        ),
        CheckConstraint(
            "attempts >= 0",
            name="ck_processing_queue_attempts_nonnegative",
        ),
        CheckConstraint(
            "max_attempts >= 1",
            name="ck_processing_queue_max_attempts_positive",
        ),
        UniqueConstraint(
            "deduplication_key",
            name="uq_processing_queue_deduplication_key",
        ),
        Index(
            "ix_processing_queue_pending",
            "status",
            "priority",
            "available_at",
        ),
        Index(
            "ix_processing_queue_lease",
            "status",
            "locked_until",
        ),
    )

    job_type: Mapped[QueueJobType] = mapped_column(
        SQLAlchemyEnum(
            QueueJobType,
            name="queue_job_type",
            values_callable=lambda enum: [item.value for item in enum],
        ),
        nullable=False,
        index=True,
    )

    status: Mapped[QueueJobStatus] = mapped_column(
        SQLAlchemyEnum(
            QueueJobStatus,
            name="queue_job_status",
            values_callable=lambda enum: [item.value for item in enum],
        ),
        default=QueueJobStatus.PENDING,
        nullable=False,
        index=True,
    )

    priority: Mapped[int] = mapped_column(
        Integer,
        default=100,
        server_default="100",
        nullable=False,
    )

    payload: Mapped[dict] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
    )

    deduplication_key: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    forwarding_rule_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "forwarding_rules.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )

    message_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "messages.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )

    backfill_job_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "backfill_jobs.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )

    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )

    locked_by: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )

    locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    attempts: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
    )

    max_attempts: Mapped[int] = mapped_column(
        Integer,
        default=3,
        server_default="3",
        nullable=False,
    )

    last_error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    def __repr__(self) -> str:
        return (
            f"<ProcessingQueue(id={self.id!r}, "
            f"job_type={self.job_type.value!r}, "
            f"status={self.status.value!r}, "
            f"priority={self.priority!r})>"
        )
