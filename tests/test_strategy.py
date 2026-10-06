import numpy as np
import pandas as pd

from app.strategy.indicators import enrich_indicators
from app.strategy.scoring import analyze_frame


def make_frame(size: int = 320) -> pd.DataFrame:
    x = np.arange(size, dtype=float)
    close = 100 + x * 0.08 + np.sin(x / 8) * 0.4
    return pd.DataFrame(
        {
            "open": close - 0.1,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": 1000 + (x % 20) * 5,
            "open_time": pd.date_range("2026-01-01", periods=size, freq="5min", tz="UTC"),
            "close_time": pd.date_range("2026-01-01", periods=size, freq="5min", tz="UTC"),
        }
    )


def test_indicators_are_available_after_warmup() -> None:
    result = enrich_indicators(make_frame())
    last = result.iloc[-1]
    for name in ["ema20", "ema50", "ema200", "rsi", "macd", "macd_signal", "atr"]:
        assert pd.notna(last[name])


def test_score_is_bounded() -> None:
    _, decision = analyze_frame(make_frame())
    assert 0 <= decision.score <= 100
    assert decision.signal in {"BUY", "WAIT", "SELL"}
