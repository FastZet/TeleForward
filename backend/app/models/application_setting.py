
"""
TeleForward application settings database model.

Stores persistent, non-secret application configuration.
Sensitive credentials and cryptographic keys must be stored
separately using the application's encryption facilities.
"""

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Index,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, PrimaryKeyMixin, TimestampMixin


class ApplicationSetting(Base, PrimaryKeyMixin, TimestampMixin):
    """A persistent application configuration setting."""

    __tablename__ = "application_settings"

    __table_args__ = (
        Index(
            "ix_application_settings_category",
            "category",
        ),
    )

    key: Mapped[str] = mapped_column(
        String(150),
        unique=True,
        nullable=False,
        index=True,
    )

    value: Mapped[dict | list | str | int | float | bool | None] = (
        mapped_column(
            JSON,
            nullable=True,
        )
    )

    category: Mapped[str] = mapped_column(
        String(80),
        default="general",
        server_default="general",
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    is_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default="true",
        nullable=False,
    )

    is_public: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
        nullable=False,
    )

    updated_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "users.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )

    def __repr__(self) -> str:
        return (
            f"<ApplicationSetting(id={self.id!r}, "
            f"key={self.key!r}, "
            f"category={self.category!r})>"
        )
