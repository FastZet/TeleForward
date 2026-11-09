
"""
TeleForward historical message backfill database model.

Tracks backfill jobs, progress, pagination cursors and recovery state.
"""

from datetime import datetime
from enum import Enum

from sqlalchemy import (
    BigInteger,
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


class BackfillStatus(str, Enum):
    """Historical backfill job states."""

    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class BackfillJob(Base, PrimaryKeyMixin, TimestampMixin):
    """A historical Telegram message retrieval job."""

    __tablename__ = "backfill_jobs"

    __table_args__ = (
        Index(
            "ix_backfill_jobs_status_created",
            "status",
            "created_at",
        ),
    )

    name: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
    )

    forwarding_rule_id: Mapped[int] = mapped_column(
        ForeignKey(
            "forwarding_rules.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    telegram_account_id: Mapped[int] = mapped_column(
        ForeignKey(
            "telegram_accounts.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    source_chat_id: Mapped[int] = mapped_column(
        ForeignKey(
            "telegram_chats.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    status: Mapped[BackfillStatus] = mapped_column(
        SQLAlchemyEnum(
            BackfillStatus,
            name="backfill_status",
            values_callable=lambda enum: [item.value for item in enum],
        ),
        default=BackfillStatus.PENDING,
        nullable=False,
        index=True,
    )

    start_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    end_date: Mapped[datetime | None] = mapped_column(
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

    last_processed_message_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )

    total_messages: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
    )

    processed_messages: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
    )

    forwarded_messages: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
    )

    skipped_messages: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
    )

    failed_messages: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
    )

    cursor_data: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
    )

    options: Mapped[dict] = mapped_column(
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

    last_error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    def __repr__(self) -> str:
        return (
            f"<BackfillJob(id={self.id!r}, "
            f"name={self.name!r}, "
            f"status={self.status.value!r}, "
            f"processed_messages={self.processed_messages!r})>"
        )
