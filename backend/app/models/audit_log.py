
"""
TeleForward audit log database model.

Records security-sensitive and administrative application events.
"""

from datetime import datetime
from enum import Enum

from sqlalchemy import (
    DateTime,
    Enum as SQLAlchemyEnum,
    ForeignKey,
    Index,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, PrimaryKeyMixin


class AuditEventCategory(str, Enum):
    """Categories of auditable application events."""

    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    USER_MANAGEMENT = "user_management"
    TELEGRAM_ACCOUNT = "telegram_account"
    FORWARDING = "forwarding"
    CONFIGURATION = "configuration"
    SECURITY = "security"
    BACKUP = "backup"
    SYSTEM = "system"


class AuditLog(Base, PrimaryKeyMixin):
    """An immutable record of an application audit event."""

    __tablename__ = "audit_logs"

    __table_args__ = (
        Index(
            "ix_audit_logs_category_created",
            "category",
            "created_at",
        ),
        Index(
            "ix_audit_logs_user_created",
            "user_id",
            "created_at",
        ),
        Index(
            "ix_audit_logs_event_created",
            "event_type",
            "created_at",
        ),
    )

    user_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "users.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )

    category: Mapped[AuditEventCategory] = mapped_column(
        SQLAlchemyEnum(
            AuditEventCategory,
            name="audit_event_category",
            values_callable=lambda enum: [item.value for item in enum],
        ),
        nullable=False,
        index=True,
    )

    event_type: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
    )

    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    ip_address: Mapped[str | None] = mapped_column(
        String(45),
        nullable=True,
    )

    user_agent: Mapped[str | None] = mapped_column(
        String(512),
        nullable=True,
    )

    resource_type: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    resource_id: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )

    event_metadata: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
    )

    success: Mapped[bool] = mapped_column(
        nullable=False,
        default=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )

    def __repr__(self) -> str:
        return (
            f"<AuditLog(id={self.id!r}, "
            f"category={self.category.value!r}, "
            f"event_type={self.event_type!r}, "
            f"success={self.success!r})>"
        )
