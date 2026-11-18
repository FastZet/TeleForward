"""Create persistent scheduled execution history.

Revision ID: 20261118_0003
Revises: 20261116_0002
Create Date: 2026-11-18
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261118_0003"
down_revision: Union[str, Sequence[str], None] = "20261116_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "scheduled_execution_history",
        sa.Column("execution_id", sa.String(length=64), nullable=False),
        sa.Column("job_id", sa.String(length=128), nullable=False),
        sa.Column("task_name", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("error", sa.String(length=4000), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("execution_id"),
    )
    op.create_index(
        "ix_scheduled_execution_job_started",
        "scheduled_execution_history",
        ["job_id", "started_at"],
    )
    op.create_index(
        "ix_scheduled_execution_status_started",
        "scheduled_execution_history",
        ["status", "started_at"],
    )
    op.create_index(
        "ix_scheduled_execution_history_job_id",
        "scheduled_execution_history",
        ["job_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_scheduled_execution_history_job_id",
        table_name="scheduled_execution_history",
    )
    op.drop_index(
        "ix_scheduled_execution_status_started",
        table_name="scheduled_execution_history",
    )
    op.drop_index(
        "ix_scheduled_execution_job_started",
        table_name="scheduled_execution_history",
    )
    op.drop_table("scheduled_execution_history")
