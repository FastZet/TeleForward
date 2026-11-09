
"""
TeleForward message filter database model.

Stores filtering conditions associated with forwarding rules.
"""

from enum import Enum

from sqlalchemy import (
    Boolean,
    Enum as SQLAlchemyEnum,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, PrimaryKeyMixin, TimestampMixin


class FilterType(str, Enum):
    """Supported message filter categories."""

    KEYWORD = "keyword"
    REGEX = "regex"
    SENDER = "sender"
    MEDIA_TYPE = "media_type"
    MESSAGE_TYPE = "message_type"
    HAS_LINK = "has_link"
    HAS_TEXT = "has_text"
    HAS_MEDIA = "has_media"


class FilterOperator(str, Enum):
    """Logical operators used to combine filter conditions."""

    INCLUDE = "include"
    EXCLUDE = "exclude"


class FilterMatchMode(str, Enum):
    """How multiple values within a filter are evaluated."""

    ANY = "any"
    ALL = "all"


class FilterRule(Base, PrimaryKeyMixin, TimestampMixin):
    """A message filtering condition for a forwarding rule."""

    __tablename__ = "filter_rules"

    forwarding_rule_id: Mapped[int] = mapped_column(
        ForeignKey(
            "forwarding_rules.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    filter_type: Mapped[FilterType] = mapped_column(
        SQLAlchemyEnum(
            FilterType,
            name="filter_type",
            values_callable=lambda enum: [item.value for item in enum],
        ),
        nullable=False,
        index=True,
    )

    operator: Mapped[FilterOperator] = mapped_column(
        SQLAlchemyEnum(
            FilterOperator,
            name="filter_operator",
            values_callable=lambda enum: [item.value for item in enum],
        ),
        default=FilterOperator.INCLUDE,
        nullable=False,
    )

    match_mode: Mapped[FilterMatchMode] = mapped_column(
        SQLAlchemyEnum(
            FilterMatchMode,
            name="filter_match_mode",
            values_callable=lambda enum: [item.value for item in enum],
        ),
        default=FilterMatchMode.ANY,
        nullable=False,
    )

    values: Mapped[list] = mapped_column(
        JSON,
        default=list,
        nullable=False,
    )

    case_sensitive: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
        nullable=False,
    )

    is_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default="true",
        nullable=False,
        index=True,
    )

    priority: Mapped[int] = mapped_column(
        Integer,
        default=100,
        server_default="100",
        nullable=False,
    )

    def __repr__(self) -> str:
        return (
            f"<FilterRule(id={self.id!r}, "
            f"name={self.name!r}, "
            f"filter_type={self.filter_type.value!r}, "
            f"operator={self.operator.value!r})>"
        )
