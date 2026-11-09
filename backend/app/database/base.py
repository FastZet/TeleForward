
"""
TeleForward SQLAlchemy declarative base and reusable mixins.

Provides:
- DeclarativeBase with consistent metadata naming conventions.
- Integer primary-key mixin.
- UTC timestamp mixin.
"""

from datetime import datetime, timezone
from typing import Annotated

from sqlalchemy import (
    DateTime,
    MetaData,
    func,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
)


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


class Base(DeclarativeBase):
    """Base class for all TeleForward ORM models."""

    metadata = MetaData(
        naming_convention=NAMING_CONVENTION,
    )


class PrimaryKeyMixin:
    """Reusable auto-incrementing integer primary key."""

    id: Mapped[int] = mapped_column(
        primary_key=True,
        autoincrement=True,
    )


class TimestampMixin:
    """
    Reusable creation and modification timestamps.

    Database-side defaults provide timestamps even when records
    are inserted outside normal ORM application workflows.
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
