"""universe snapshots and backtest run status

Revision ID: a1c4e0b7d2f3
Revises: 5d1f7294de8f
Create Date: 2026-10-18 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1c4e0b7d2f3"
down_revision: str | Sequence[str] | None = "5d1f7294de8f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONType = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "universe_snapshots",
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("code", sa.String(length=16), nullable=False),
        sa.Column(
            "market",
            sa.Enum(
                "KOSPI", "KOSDAQ", name="market", native_enum=False, length=8, validate_strings=True
            ),
            nullable=False,
        ),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("market_cap", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["code"], ["instruments.code"], name=op.f("fk_universe_snapshots_code_instruments")
        ),
        sa.PrimaryKeyConstraint("as_of", "code", name=op.f("pk_universe_snapshots")),
    )
    op.create_index("ix_universe_snapshots_as_of", "universe_snapshots", ["as_of"], unique=False)

    op.add_column("backtest_runs", sa.Column("name", sa.String(length=80), nullable=True))
    op.add_column(
        "backtest_runs",
        sa.Column("status", sa.String(length=10), server_default="done", nullable=False),
    )
    op.add_column(
        "backtest_runs", sa.Column("progress", sa.Float(), server_default="1", nullable=False)
    )
    op.add_column("backtest_runs", sa.Column("error", sa.Text(), nullable=True))
    op.add_column(
        "backtest_runs", sa.Column("detail", JSONType, nullable=False, server_default="{}")
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("backtest_runs", "detail")
    op.drop_column("backtest_runs", "error")
    op.drop_column("backtest_runs", "progress")
    op.drop_column("backtest_runs", "status")
    op.drop_column("backtest_runs", "name")
    op.drop_index("ix_universe_snapshots_as_of", table_name="universe_snapshots")
    op.drop_table("universe_snapshots")
