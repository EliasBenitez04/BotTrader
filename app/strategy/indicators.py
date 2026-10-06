import numpy as np
import pandas as pd

REQUIRED_COLUMNS = {"open", "high", "low", "close", "volume"}


def _validate_frame(frame: pd.DataFrame) -> None:
    missing = REQUIRED_COLUMNS.difference(frame.columns)
    if missing:
        raise ValueError(f"Missing candle columns: {sorted(missing)}")
    if frame.empty:
        raise ValueError("Candle frame is empty")


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False, min_periods=period).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gains = delta.clip(lower=0)
    losses = -delta.clip(upper=0)

    avg_gain = gains.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = losses.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    output = 100 - (100 / (1 + rs))
    return output.fillna(100.0).where(avg_gain.notna())


def atr(frame: pd.DataFrame, period: int = 14) -> pd.Series:
    previous_close = frame["close"].shift(1)
    true_range = pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - previous_close).abs(),
            (frame["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return true_range.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def enrich_indicators(
    frame: pd.DataFrame,
    *,
    rsi_period: int = 14,
    atr_period: int = 14,
) -> pd.DataFrame:
    _validate_frame(frame)
    result = frame.copy()

    result["ema20"] = ema(result["close"], 20)
    result["ema50"] = ema(result["close"], 50)
    result["ema200"] = ema(result["close"], 200)

    result["rsi"] = rsi(result["close"], rsi_period)

    ema12 = ema(result["close"], 12)
    ema26 = ema(result["close"], 26)
    result["macd"] = ema12 - ema26
    result["macd_signal"] = ema(result["macd"], 9)
    result["macd_histogram"] = result["macd"] - result["macd_signal"]

    result["atr"] = atr(result, atr_period)
    result["atr_pct"] = (result["atr"] / result["close"]) * 100

    volume_sma20 = result["volume"].rolling(20, min_periods=20).mean()
    result["volume_ratio"] = result["volume"] / volume_sma20.replace(0, np.nan)

    return result
