
"""
Initial TeleForward database schema.

Revision ID: 20261109_0001
Revises:
Create Date: 2026-11-09

This is the initial database baseline. It creates all registered
ORM tables. Subsequent schema changes must use explicit Alembic
migration operations.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.database.base import Base
import app.models  # noqa: F401 - register all ORM models


# Revision identifiers used by Alembic.
revision: str = "20261109_0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the initial application database schema."""
    bind = op.get_bind()

    Base.metadata.create_all(
        bind=bind,
        checkfirst=True,
    )


def downgrade() -> None:
    """
    Drop the initial application database schema.

    WARNING: This operation removes all application tables and
    permanently deletes their data.
    """
    bind = op.get_bind()

    Base.metadata.drop_all(
        bind=bind,
        checkfirst=True,
    )
