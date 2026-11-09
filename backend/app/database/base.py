
"""
TeleForward SQLAlchemy declarative base.

Defines shared ORM conventions and the declarative base
used by all application database models.
"""

from datetime import UTC, datetime

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


# ============================================================
# Database naming conventions
# ============================================================

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": (
        "fk_%(table_name)s_%(column_0_name)s_"
        "%(referred_table_name)s"
    ),
    "pk": "pk_%(table_name)s",
}


metadata = MetaData(
    naming_convention=NAMING_CONVENTION,
)


# ============================================================
# Declarative base
# ============================================================

class Base(DeclarativeBase):
    """
    Common declarative base for TeleForward ORM models.

    All database models should inherit from this class.
    """

    metadata = metadata


# ============================================================
# Common timestamp mixin
# ============================================================

class TimestampMixin:
    """
    Provides standard creation and update timestamps.

    Timestamps are stored in UTC.

    created_at:
        Set automatically when the record is inserted.

    updated_at:
        Set automatically when the record is inserted
        and whenever the record is updated.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


# ============================================================
# Common primary key mixin
# ============================================================

class PrimaryKeyMixin:
    """
    Provides an auto-incrementing integer primary key.

    Models can inherit this mixin when integer identifiers
    are appropriate for their database representation.
    """

    id: Mapped[int] = mapped_column(
        primary_key=True,
        autoincrement=True,
    )
