from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)

from app.db.base import Base


class MarketCandle(Base):
    __tablename__ = "market_candles"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False)
    timeframe = Column(String(10), nullable=False)
    open_time = Column(DateTime(timezone=True), nullable=False)
    close_time = Column(DateTime(timezone=True), nullable=False)
    open = Column(Numeric(24, 8), nullable=False)
    high = Column(Numeric(24, 8), nullable=False)
    low = Column(Numeric(24, 8), nullable=False)
    close = Column(Numeric(24, 8), nullable=False)
    volume = Column(Numeric(32, 12), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("symbol", "timeframe", "open_time", name="uq_candle_symbol_tf_open"),
        Index("ix_candle_symbol_tf_time", "symbol", "timeframe", "open_time"),
    )


class Signal(Base):
    __tablename__ = "signals"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False, index=True)
    timeframe = Column(String(10), nullable=False)
    signal = Column(String(10), nullable=False)
    score = Column(Integer, nullable=False)
    price = Column(Numeric(24, 8), nullable=False)
    ema20 = Column(Numeric(24, 8))
    ema50 = Column(Numeric(24, 8))
    ema200 = Column(Numeric(24, 8))
    rsi = Column(Numeric(12, 6))
    macd = Column(Numeric(24, 10))
    macd_signal = Column(Numeric(24, 10))
    atr = Column(Numeric(24, 10))
    volume_ratio = Column(Numeric(16, 8))
    reasons_json = Column(Text, nullable=False, default="[]")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (Index("ix_signal_symbol_created", "symbol", "created_at"),)


class Trade(Base):
    __tablename__ = "trades"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False, index=True)
    mode = Column(String(10), nullable=False)
    status = Column(String(10), nullable=False, index=True)
    side = Column(String(10), nullable=False, default="LONG")
    quantity = Column(Numeric(28, 12), nullable=False)
    entry_price = Column(Numeric(24, 8), nullable=False)
    exit_price = Column(Numeric(24, 8))
    stop_loss = Column(Numeric(24, 8), nullable=False)
    take_profit = Column(Numeric(24, 8), nullable=False)
    entry_score = Column(Integer, nullable=False)
    entry_time = Column(DateTime(timezone=True), nullable=False)
    exit_time = Column(DateTime(timezone=True))
    pnl_quote = Column(Numeric(24, 8))
    pnl_percent = Column(Numeric(16, 8))
    fees_quote = Column(Numeric(24, 8), nullable=False, default=0)
    exit_reason = Column(String(40))
    binance_order_id = Column(String(64))
    client_order_id = Column(String(64), unique=True)
    protection_order_list_id = Column(String(64))
    protection_status = Column(String(24), nullable=False, default="NOT_REQUIRED")
    last_error = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        Index("ix_trade_mode_status", "mode", "status"),
        Index("ix_trade_symbol_status", "symbol", "status"),
        Index("ix_trade_entry_time", "entry_time"),
    )


class BacktestRun(Base):
    __tablename__ = "backtest_runs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False, index=True)
    timeframe = Column(String(10), nullable=False)
    start_time = Column(DateTime(timezone=True), nullable=False)
    end_time = Column(DateTime(timezone=True), nullable=False)
    initial_capital = Column(Numeric(24, 8), nullable=False)
    final_capital = Column(Numeric(24, 8), nullable=False)
    total_trades = Column(Integer, nullable=False)
    winning_trades = Column(Integer, nullable=False)
    losing_trades = Column(Integer, nullable=False)
    win_rate = Column(Numeric(16, 8), nullable=False)
    profit_factor = Column(Numeric(24, 8))
    max_drawdown = Column(Numeric(16, 8), nullable=False)
    return_pct = Column(Numeric(16, 8), nullable=False)
    expectancy_pct = Column(Numeric(16, 8), nullable=False)
    sharpe_ratio = Column(Numeric(16, 8))
    statistically_sufficient = Column(Boolean, nullable=False, default=False)
    parameters_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class BacktestTrade(Base):
    __tablename__ = "backtest_trades"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    backtest_run_id = Column(
        BigInteger,
        ForeignKey("backtest_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    entry_time = Column(DateTime(timezone=True), nullable=False)
    exit_time = Column(DateTime(timezone=True), nullable=False)
    quantity = Column(Numeric(28, 12), nullable=False)
    entry_price = Column(Numeric(24, 8), nullable=False)
    exit_price = Column(Numeric(24, 8), nullable=False)
    pnl_quote = Column(Numeric(24, 8), nullable=False)
    pnl_percent = Column(Numeric(16, 8), nullable=False)
    exit_reason = Column(String(40), nullable=False)
    entry_score = Column(Integer, nullable=False)


class RiskEvent(Base):
    __tablename__ = "risk_events"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    event_type = Column(String(40), nullable=False, index=True)
    severity = Column(String(10), nullable=False)
    symbol = Column(String(20))
    message = Column(Text, nullable=False)
    context_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class RuntimeState(Base):
    __tablename__ = "runtime_state"

    key = Column(String(80), primary_key=True)
    value = Column(Text, nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
