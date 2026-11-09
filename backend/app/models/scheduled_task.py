
"""
TeleForward scheduled task database model.

Stores persistent scheduled operations and their execution state.
"""

from datetime import datetime
from enum import Enum

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SQLAlchemyEnum,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, PrimaryKeyMixin, TimestampMixin


class ScheduledTaskType(str, Enum):
    """Supported scheduled operation types."""

    FORWARD_MESSAGE = "forward_message"
    BACKFILL = "backfill"
    SYNC_EDITS = "sync_edits"
    SYNC_DELETIONS = "sync_deletions"
    CLEANUP = "cleanup"
    BACKUP = "backup"
    CUSTOM = "custom"


class ScheduledTaskStatus(str, Enum):
    """Scheduled task execution states."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"
    CANCELLED = "cancelled"


class ScheduledTask(Base, PrimaryKeyMixin, TimestampMixin):
    """A persistent scheduled operation."""

    __tablename__ = "scheduled_tasks"

    __table_args__ = (
        Index(
            "ix_scheduled_tasks_status_next_run",
            "status",
            "next_run_at",
        ),
    )

    name: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    task_type: Mapped[ScheduledTaskType] = mapped_column(
        SQLAlchemyEnum(
            ScheduledTaskType,
            name="scheduled_task_type",
            values_callable=lambda enum: [item.value for item in enum],
        ),
        nullable=False,
        index=True,
    )

    forwarding_rule_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "forwarding_rules.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )

    status: Mapped[ScheduledTaskStatus] = mapped_column(
        SQLAlchemyEnum(
            ScheduledTaskStatus,
            name="scheduled_task_status",
            values_callable=lambda enum: [item.value for item in enum],
        ),
        default=ScheduledTaskStatus.PENDING,
        nullable=False,
        index=True,
    )

    scheduled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )

    next_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    last_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    timezone: Mapped[str] = mapped_column(
        String(64),
        default="Asia/Kolkata",
        server_default="Asia/Kolkata",
        nullable=False,
    )

    is_recurring: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
        nullable=False,
    )

    recurrence_rule: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
    )

    task_payload: Mapped[dict] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
    )

    retry_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
    )

    max_retries: Mapped[int] = mapped_column(
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
            f"<ScheduledTask(id={self.id!r}, "
            f"name={self.name!r}, "
            f"task_type={self.task_type.value!r}, "
            f"status={self.status.value!r})>"
        )
