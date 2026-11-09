
"""
TeleForward Telegram chat database model.

Stores Telegram chat metadata associated with connected accounts.
"""

from enum import Enum

from sqlalchemy import (
    BigInteger,
    Boolean,
    Enum as SQLAlchemyEnum,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, PrimaryKeyMixin, TimestampMixin


class TelegramChatType(str, Enum):
    """Supported Telegram chat types."""

    PRIVATE = "private"
    BOT = "bot"
    GROUP = "group"
    SUPERGROUP = "supergroup"
    CHANNEL = "channel"


class TelegramChat(Base, PrimaryKeyMixin, TimestampMixin):
    """A Telegram chat accessible through a connected account."""

    __tablename__ = "telegram_chats"

    __table_args__ = (
        UniqueConstraint(
            "telegram_account_id",
            "telegram_chat_id",
            name="uq_telegram_chats_account_chat",
        ),
        Index(
            "ix_telegram_chats_account_type",
            "telegram_account_id",
            "chat_type",
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

    telegram_chat_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )

    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    username: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        index=True,
    )

    chat_type: Mapped[TelegramChatType] = mapped_column(
        SQLAlchemyEnum(
            TelegramChatType,
            name="telegram_chat_type",
            values_callable=lambda enum: [item.value for item in enum],
        ),
        nullable=False,
        index=True,
    )

    is_accessible: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default="true",
        nullable=False,
    )

    is_archived: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
        nullable=False,
    )

    is_forum: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
        nullable=False,
    )

    def __repr__(self) -> str:
        return (
            f"<TelegramChat(id={self.id!r}, "
            f"telegram_chat_id={self.telegram_chat_id!r}, "
            f"title={self.title!r}, "
            f"chat_type={self.chat_type.value!r})>"
        )
