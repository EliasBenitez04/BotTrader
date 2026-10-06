"""Initial BotTrader schema compatible with PostgreSQL 9.5.

Revision ID: 0001_initial
Revises:
"""

from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "market_candles",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column("timeframe", sa.String(length=10), nullable=False),
        sa.Column("open_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("close_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open", sa.Numeric(24, 8), nullable=False),
        sa.Column("high", sa.Numeric(24, 8), nullable=False),
        sa.Column("low", sa.Numeric(24, 8), nullable=False),
        sa.Column("close", sa.Numeric(24, 8), nullable=False),
        sa.Column("volume", sa.Numeric(32, 12), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("symbol", "timeframe", "open_time", name="uq_candle_symbol_tf_open"),
    )
    op.create_index("ix_candle_symbol_tf_time", "market_candles", ["symbol", "timeframe", "open_time"])

    op.create_table(
        "signals",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column("timeframe", sa.String(length=10), nullable=False),
        sa.Column("signal", sa.String(length=10), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("price", sa.Numeric(24, 8), nullable=False),
        sa.Column("ema20", sa.Numeric(24, 8)),
        sa.Column("ema50", sa.Numeric(24, 8)),
        sa.Column("ema200", sa.Numeric(24, 8)),
        sa.Column("rsi", sa.Numeric(12, 6)),
        sa.Column("macd", sa.Numeric(24, 10)),
        sa.Column("macd_signal", sa.Numeric(24, 10)),
        sa.Column("atr", sa.Numeric(24, 10)),
        sa.Column("volume_ratio", sa.Numeric(16, 8)),
        sa.Column("reasons_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_signals_symbol", "signals", ["symbol"])
    op.create_index("ix_signal_symbol_created", "signals", ["symbol", "created_at"])

    op.create_table(
        "trades",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column("mode", sa.String(length=10), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("side", sa.String(length=10), nullable=False, server_default="LONG"),
        sa.Column("quantity", sa.Numeric(28, 12), nullable=False),
        sa.Column("entry_price", sa.Numeric(24, 8), nullable=False),
        sa.Column("exit_price", sa.Numeric(24, 8)),
        sa.Column("stop_loss", sa.Numeric(24, 8), nullable=False),
        sa.Column("take_profit", sa.Numeric(24, 8), nullable=False),
        sa.Column("entry_score", sa.Integer(), nullable=False),
        sa.Column("entry_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("exit_time", sa.DateTime(timezone=True)),
        sa.Column("pnl_quote", sa.Numeric(24, 8)),
        sa.Column("pnl_percent", sa.Numeric(16, 8)),
        sa.Column("fees_quote", sa.Numeric(24, 8), nullable=False, server_default="0"),
        sa.Column("exit_reason", sa.String(length=40)),
        sa.Column("binance_order_id", sa.String(length=64)),
        sa.Column("client_order_id", sa.String(length=64), unique=True),
        sa.Column("protection_order_list_id", sa.String(length=64)),
        sa.Column("protection_status", sa.String(length=24), nullable=False, server_default="NOT_REQUIRED"),
        sa.Column("last_error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_trades_symbol", "trades", ["symbol"])
    op.create_index("ix_trades_status", "trades", ["status"])
    op.create_index("ix_trade_mode_status", "trades", ["mode", "status"])
    op.create_index("ix_trade_symbol_status", "trades", ["symbol", "status"])
    op.create_index("ix_trade_entry_time", "trades", ["entry_time"])
    op.create_index(
        "uq_open_trade_per_symbol_mode",
        "trades",
        ["symbol", "mode"],
        unique=True,
        postgresql_where=sa.text("status = 'OPEN'"),
    )

    op.create_table(
        "backtest_runs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column("timeframe", sa.String(length=10), nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("initial_capital", sa.Numeric(24, 8), nullable=False),
        sa.Column("final_capital", sa.Numeric(24, 8), nullable=False),
        sa.Column("total_trades", sa.Integer(), nullable=False),
        sa.Column("winning_trades", sa.Integer(), nullable=False),
        sa.Column("losing_trades", sa.Integer(), nullable=False),
        sa.Column("win_rate", sa.Numeric(16, 8), nullable=False),
        sa.Column("profit_factor", sa.Numeric(24, 8)),
        sa.Column("max_drawdown", sa.Numeric(16, 8), nullable=False),
        sa.Column("return_pct", sa.Numeric(16, 8), nullable=False),
        sa.Column("expectancy_pct", sa.Numeric(16, 8), nullable=False),
        sa.Column("sharpe_ratio", sa.Numeric(16, 8)),
        sa.Column("statistically_sufficient", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("parameters_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_backtest_runs_symbol", "backtest_runs", ["symbol"])

    op.create_table(
        "backtest_trades",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "backtest_run_id",
            sa.BigInteger(),
            sa.ForeignKey("backtest_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("entry_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("exit_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("quantity", sa.Numeric(28, 12), nullable=False),
        sa.Column("entry_price", sa.Numeric(24, 8), nullable=False),
        sa.Column("exit_price", sa.Numeric(24, 8), nullable=False),
        sa.Column("pnl_quote", sa.Numeric(24, 8), nullable=False),
        sa.Column("pnl_percent", sa.Numeric(16, 8), nullable=False),
        sa.Column("exit_reason", sa.String(length=40), nullable=False),
        sa.Column("entry_score", sa.Integer(), nullable=False),
    )
    op.create_index("ix_backtest_trades_backtest_run_id", "backtest_trades", ["backtest_run_id"])

    op.create_table(
        "risk_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("severity", sa.String(length=10), nullable=False),
        sa.Column("symbol", sa.String(length=20)),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("context_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_risk_events_event_type", "risk_events", ["event_type"])

    op.create_table(
        "runtime_state",
        sa.Column("key", sa.String(length=80), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )


def downgrade() -> None:
    op.drop_table("runtime_state")
    op.drop_index("ix_risk_events_event_type", table_name="risk_events")
    op.drop_table("risk_events")
    op.drop_index("ix_backtest_trades_backtest_run_id", table_name="backtest_trades")
    op.drop_table("backtest_trades")
    op.drop_index("ix_backtest_runs_symbol", table_name="backtest_runs")
    op.drop_table("backtest_runs")
    op.drop_index("uq_open_trade_per_symbol_mode", table_name="trades")
    op.drop_index("ix_trade_entry_time", table_name="trades")
    op.drop_index("ix_trade_symbol_status", table_name="trades")
    op.drop_index("ix_trade_mode_status", table_name="trades")
    op.drop_index("ix_trades_status", table_name="trades")
    op.drop_index("ix_trades_symbol", table_name="trades")
    op.drop_table("trades")
    op.drop_index("ix_signal_symbol_created", table_name="signals")
    op.drop_index("ix_signals_symbol", table_name="signals")
    op.drop_table("signals")
    op.drop_index("ix_candle_symbol_tf_time", table_name="market_candles")
    op.drop_table("market_candles")
