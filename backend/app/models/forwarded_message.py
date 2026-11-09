
"""
TeleForward forwarded message database model.

Tracks delivery attempts and results for messages processed
by individual forwarding rules.
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
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, PrimaryKeyMixin, TimestampMixin


class DeliveryStatus(str, Enum):
    """Forwarded message delivery states."""

    PENDING = "pending"
    PROCESSING = "processing"
    SENT = "sent"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class ForwardedMessage(Base, PrimaryKeyMixin, TimestampMixin):
    """Tracks delivery of a source message to a destination chat."""

    __tablename__ = "forwarded_messages"

    __table_args__ = (
        UniqueConstraint(
            "forwarding_rule_id",
            "source_message_id",
            name="uq_forwarded_messages_rule_source",
        ),
        Index(
            "ix_forwarded_messages_status_created",
            "delivery_status",
            "created_at",
        ),
        Index(
            "ix_forwarded_messages_destination",
            "destination_chat_id",
            "destination_message_id",
        ),
    )

    forwarding_rule_id: Mapped[int] = mapped_column(
        ForeignKey(
            "forwarding_rules.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    source_message_id: Mapped[int] = mapped_column(
        ForeignKey(
            "messages.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    destination_chat_id: Mapped[int] = mapped_column(
        ForeignKey(
            "telegram_chats.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    destination_message_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )

    delivery_status: Mapped[DeliveryStatus] = mapped_column(
        SQLAlchemyEnum(
            DeliveryStatus,
            name="delivery_status",
            values_callable=lambda enum: [item.value for item in enum],
        ),
        default=DeliveryStatus.PENDING,
        nullable=False,
        index=True,
    )

    retry_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
    )

    last_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    source_edit_at_delivery: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    last_error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    def __repr__(self) -> str:
        return (
            f"<ForwardedMessage(id={self.id!r}, "
            f"forwarding_rule_id={self.forwarding_rule_id!r}, "
            f"source_message_id={self.source_message_id!r}, "
            f"delivery_status={self.delivery_status.value!r})>"
        )
