import numpy as np
import pandas as pd

from app.backtesting.engine import Backtester
from app.risk.manager import RiskLimits


def make_market(size: int = 700) -> pd.DataFrame:
    x = np.arange(size, dtype=float)
    close = 100 + x * 0.05 + np.sin(x / 10) * 1.2
    time = pd.date_range("2026-01-01", periods=size, freq="5min", tz="UTC")
    return pd.DataFrame(
        {
            "open": close - 0.05,
            "high": close + 0.8,
            "low": close - 0.8,
            "close": close,
            "volume": 1000 + 120 * (1 + np.sin(x / 7)),
            "open_time": time,
            "close_time": time + pd.Timedelta(minutes=5),
        }
    )


def test_backtest_produces_finite_core_metrics() -> None:
    engine = Backtester(
        risk_limits=RiskLimits(),
        buy_threshold=70,
        sell_threshold=30,
        rsi_period=14,
        atr_period=14,
        fee_bps=10,
        slippage_bps=5,
        min_trades=1,
    )
    result = engine.run(
        make_market(),
        symbol="BTCUSDT",
        timeframe="5m",
        initial_capital=1000,
    )
    assert result.metrics.final_capital > 0
    assert result.metrics.max_drawdown >= 0
    assert 0 <= result.metrics.win_rate <= 100
