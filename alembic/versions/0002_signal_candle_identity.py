"""Add candle identity to strategy signals.

Revision ID: 0002_signal_candle_identity
Revises: 0001_initial
"""

from alembic import op
import sqlalchemy as sa

revision = "0002_signal_candle_identity"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "signals",
        sa.Column("candle_open_time", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "signals",
        sa.Column("candle_close_time", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "uq_signal_symbol_tf_candle",
        "signals",
        ["symbol", "timeframe", "candle_close_time"],
        unique=True,
        postgresql_where=sa.text("candle_close_time IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_signal_symbol_tf_candle", table_name="signals")
    op.drop_column("signals", "candle_close_time")
    op.drop_column("signals", "candle_open_time")
