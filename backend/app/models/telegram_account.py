
"""
TeleForward Telegram account database model.

Stores Telegram account metadata and encrypted session references.
Telegram session contents must never be stored as plaintext.
"""

from datetime import datetime
from enum import Enum

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SQLAlchemyEnum,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, PrimaryKeyMixin, TimestampMixin


class TelegramAccountStatus(str, Enum):
    """Connection and authentication states for Telegram accounts."""

    PENDING = "pending"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    REQUIRES_AUTH = "requires_auth"
    REQUIRES_2FA = "requires_2fa"
    ERROR = "error"
    DISABLED = "disabled"


class TelegramAccount(Base, PrimaryKeyMixin, TimestampMixin):
    """A Telegram user account connected to TeleForward."""

    __tablename__ = "telegram_accounts"

    __table_args__ = (
        UniqueConstraint(
            "phone_number",
            name="uq_telegram_accounts_phone_number",
        ),
    )

    name: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
    )

    phone_number: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        index=True,
    )

    telegram_user_id: Mapped[int | None] = mapped_column(
        Integer,
        unique=True,
        index=True,
        nullable=True,
    )

    telegram_username: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        index=True,
    )

    first_name: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )

    last_name: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )

    session_data_encrypted: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    status: Mapped[TelegramAccountStatus] = mapped_column(
        SQLAlchemyEnum(
            TelegramAccountStatus,
            name="telegram_account_status",
            values_callable=lambda enum: [item.value for item in enum],
        ),
        default=TelegramAccountStatus.PENDING,
        nullable=False,
        index=True,
    )

    is_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default="true",
        nullable=False,
    )

    is_primary: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
        nullable=False,
    )

    last_connected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    last_authenticated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    last_error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    def __repr__(self) -> str:
        return (
            f"<TelegramAccount(id={self.id!r}, "
            f"name={self.name!r}, "
            f"phone_number={self.phone_number!r}, "
            f"status={self.status.value!r})>"
        )
