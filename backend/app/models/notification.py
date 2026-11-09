
"""
TeleForward notification database models.

Stores user-facing notifications and tracks delivery through
supported notification channels.
"""

from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SQLAlchemyEnum,
    ForeignKey,
    Index,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, PrimaryKeyMixin


class NotificationCategory(str, Enum):
    """Notification categories."""

    SYSTEM = "system"
    SECURITY = "security"
    TELEGRAM = "telegram"
    FORWARDING = "forwarding"
    SCHEDULING = "scheduling"
    BACKFILL = "backfill"
    BACKUP = "backup"
    ACCOUNT = "account"


class NotificationSeverity(str, Enum):
    """Notification severity levels."""

    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class NotificationChannel(str, Enum):
    """Supported notification delivery channels."""

    IN_APP = "in_app"
    EMAIL = "email"
    WEBHOOK = "webhook"


class NotificationDeliveryStatus(str, Enum):
    """Status of an individual notification delivery."""

    PENDING = "pending"
    PROCESSING = "processing"
    DELIVERED = "delivered"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Notification(Base, PrimaryKeyMixin):
    """A persistent notification associated with a user."""

    __tablename__ = "notifications"

    __table_args__ = (
        Index(
            "ix_notifications_user_created",
            "user_id",
            "created_at",
        ),
        Index(
            "ix_notifications_user_unread",
            "user_id",
            "is_read",
        ),
        Index(
            "ix_notifications_category_created",
            "category",
            "created_at",
        ),
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey(
            "users.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    category: Mapped[NotificationCategory] = mapped_column(
        SQLAlchemyEnum(
            NotificationCategory,
            name="notification_category",
            values_callable=lambda enum: [item.value for item in enum],
        ),
        nullable=False,
        default=NotificationCategory.SYSTEM,
    )

    severity: Mapped[NotificationSeverity] = mapped_column(
        SQLAlchemyEnum(
            NotificationSeverity,
            name="notification_severity",
            values_callable=lambda enum: [item.value for item in enum],
        ),
        nullable=False,
        default=NotificationSeverity.INFO,
    )

    title: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )

    message: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    is_read: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )

    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    action_url: Mapped[str | None] = mapped_column(
        String(512),
        nullable=True,
    )

    event_metadata: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
    )

    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )

    def mark_as_read(self) -> None:
        """Mark this notification as read."""
        if not self.is_read:
            self.is_read = True
            self.read_at = datetime.now(timezone.utc)

    def __repr__(self) -> str:
        return (
            f"<Notification(id={self.id!r}, "
            f"user_id={self.user_id!r}, "
            f"category={self.category.value!r}, "
            f"severity={self.severity.value!r}, "
            f"is_read={self.is_read!r})>"
        )


class NotificationDelivery(Base, PrimaryKeyMixin):
    """Tracks delivery of a notification through an external channel."""

    __tablename__ = "notification_deliveries"

    __table_args__ = (
        UniqueConstraint(
            "notification_id",
            "channel",
            name="uq_notification_delivery_channel",
        ),
        Index(
            "ix_notification_deliveries_status",
            "status",
            "created_at",
        ),
    )

    notification_id: Mapped[int] = mapped_column(
        ForeignKey(
            "notifications.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    channel: Mapped[NotificationChannel] = mapped_column(
        SQLAlchemyEnum(
            NotificationChannel,
            name="notification_channel",
            values_callable=lambda enum: [item.value for item in enum],
        ),
        nullable=False,
    )

    status: Mapped[NotificationDeliveryStatus] = mapped_column(
        SQLAlchemyEnum(
            NotificationDeliveryStatus,
            name="notification_delivery_status",
            values_callable=lambda enum: [item.value for item in enum],
        ),
        nullable=False,
        default=NotificationDeliveryStatus.PENDING,
        server_default=NotificationDeliveryStatus.PENDING.value,
    )

    destination: Mapped[str | None] = mapped_column(
        String(512),
        nullable=True,
    )

    attempts: Mapped[int] = mapped_column(
        nullable=False,
        default=0,
        server_default="0",
    )

    last_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    last_error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    def __repr__(self) -> str:
        return (
            f"<NotificationDelivery(id={self.id!r}, "
            f"notification_id={self.notification_id!r}, "
            f"channel={self.channel.value!r}, "
            f"status={self.status.value!r})>"
        )
