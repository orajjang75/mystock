"""job runs

Revision ID: b7d2f9a1c3e5
Revises: a1c4e0b7d2f3
Create Date: 2026-10-19 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7d2f9a1c3e5"
down_revision: str | Sequence[str] | None = "a1c4e0b7d2f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONType = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "job_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job", sa.String(length=10), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("outcome", sa.String(length=10), nullable=False),
        sa.Column("detail", JSONType, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_job_runs")),
    )
    op.create_index(
        "ix_job_runs_job_scheduled_for", "job_runs", ["job", "scheduled_for"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_job_runs_job_scheduled_for", table_name="job_runs")
    op.drop_table("job_runs")
