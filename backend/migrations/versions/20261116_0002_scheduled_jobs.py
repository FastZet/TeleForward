"""Add persistent scheduler job definitions.

Revision ID: 20261116_0002
Revises: 20261109_0001
Create Date: 2026-11-16
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261116_0002"
down_revision: Union[str, Sequence[str], None] = "20261109_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "scheduled_jobs",
        sa.Column("job_id", sa.String(length=128), nullable=False),
        sa.Column("task_name", sa.String(length=128), nullable=False),
        sa.Column("job_type", sa.String(length=32), nullable=False),
        sa.Column("trigger_config", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("job_id"),
    )
    op.create_index(
        "ix_scheduled_jobs_task_name",
        "scheduled_jobs",
        ["task_name"],
    )
    op.create_index(
        "ix_scheduled_jobs_enabled",
        "scheduled_jobs",
        ["enabled"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_scheduled_jobs_enabled",
        table_name="scheduled_jobs",
    )
    op.drop_index(
        "ix_scheduled_jobs_task_name",
        table_name="scheduled_jobs",
    )
    op.drop_table("scheduled_jobs")
