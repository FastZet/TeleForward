
"""
TeleForward message database model.

Stores source Telegram message metadata and processing information.
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
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, PrimaryKeyMixin, TimestampMixin


class MessageType(str, Enum):
    """Telegram message content categories."""

    TEXT = "text"
    PHOTO = "photo"
    VIDEO = "video"
    DOCUMENT = "document"
    AUDIO = "audio"
    VOICE = "voice"
    VIDEO_NOTE = "video_note"
    ANIMATION = "animation"
    STICKER = "sticker"
    POLL = "poll"
    CONTACT = "contact"
    LOCATION = "location"
    SERVICE = "service"
    OTHER = "other"


class MessageProcessingStatus(str, Enum):
    """Processing states for tracked messages."""

    PENDING = "pending"
    PROCESSING = "processing"
    PROCESSED = "processed"
    FILTERED = "filtered"
    FAILED = "failed"
    DELETED = "deleted"


class Message(Base, PrimaryKeyMixin, TimestampMixin):
    """A Telegram message tracked by TeleForward."""

    __tablename__ = "messages"

    __table_args__ = (
        UniqueConstraint(
            "telegram_account_id",
            "source_chat_id",
            "telegram_message_id",
            name="uq_messages_account_source_message",
        ),
        Index(
            "ix_messages_source_date",
            "source_chat_id",
            "telegram_date",
        ),
        Index(
            "ix_messages_processing_status",
            "processing_status",
            "created_at",
        ),
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

    telegram_message_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )

    telegram_grouped_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
        index=True,
    )

    sender_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
        index=True,
    )

    message_type: Mapped[MessageType] = mapped_column(
        SQLAlchemyEnum(
            MessageType,
            name="message_type",
            values_callable=lambda enum: [item.value for item in enum],
        ),
        default=MessageType.OTHER,
        nullable=False,
        index=True,
    )

    text: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    caption: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    media_metadata: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
    )

    telegram_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )

    edited_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    processing_status: Mapped[MessageProcessingStatus] = mapped_column(
        SQLAlchemyEnum(
            MessageProcessingStatus,
            name="message_processing_status",
            values_callable=lambda enum: [item.value for item in enum],
        ),
        default=MessageProcessingStatus.PENDING,
        nullable=False,
        index=True,
    )

    content_hash: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        index=True,
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
            f"<Message(id={self.id!r}, "
            f"telegram_message_id={self.telegram_message_id!r}, "
            f"message_type={self.message_type.value!r}, "
            f"processing_status={self.processing_status.value!r})>"
        )
