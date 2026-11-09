
"""
TeleForward forwarding rule database model.

Defines source-to-destination Telegram forwarding configurations.
"""

from datetime import datetime
from enum import Enum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum as SQLAlchemyEnum,
    ForeignKey,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, PrimaryKeyMixin, TimestampMixin


class ForwardingMode(str, Enum):
    """Supported message delivery modes."""

    FORWARD = "forward"
    COPY = "copy"


class ForwardingRule(Base, PrimaryKeyMixin, TimestampMixin):
    """A configurable Telegram message forwarding rule."""

    __tablename__ = "forwarding_rules"

    __table_args__ = (
        CheckConstraint(
            "source_chat_id != destination_chat_id",
            name="ck_forwarding_rules_different_chats",
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

    destination_chat_id: Mapped[int] = mapped_column(
        ForeignKey(
            "telegram_chats.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    mode: Mapped[ForwardingMode] = mapped_column(
        SQLAlchemyEnum(
            ForwardingMode,
            name="forwarding_mode",
            values_callable=lambda enum: [item.value for item in enum],
        ),
        default=ForwardingMode.FORWARD,
        nullable=False,
    )

    is_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default="true",
        nullable=False,
        index=True,
    )

    stop_on_error: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
        nullable=False,
    )

    preserve_grouped_media: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default="true",
        nullable=False,
    )

    settings: Mapped[dict] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
    )

    last_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    last_error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    def __repr__(self) -> str:
        return (
            f"<ForwardingRule(id={self.id!r}, "
            f"name={self.name!r}, "
            f"source_chat_id={self.source_chat_id!r}, "
            f"destination_chat_id={self.destination_chat_id!r}, "
            f"is_enabled={self.is_enabled!r})>"
        )
