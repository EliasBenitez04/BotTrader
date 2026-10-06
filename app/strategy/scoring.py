from dataclasses import dataclass
from math import isfinite

import pandas as pd

from app.strategy.indicators import enrich_indicators


@dataclass(frozen=True)
class StrategyDecision:
    signal: str
    score: int
    reasons: list[str]
    price: float
    ema20: float
    ema50: float
    ema200: float
    rsi: float
    macd: float
    macd_signal: float
    atr: float
    atr_pct: float
    volume_ratio: float


def _number(value: object, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if isfinite(number) else default


def score_row(
    row: pd.Series,
    *,
    buy_threshold: int = 75,
    sell_threshold: int = 35,
) -> StrategyDecision:
    price = _number(row.get("close"))
    ema20 = _number(row.get("ema20"))
    ema50 = _number(row.get("ema50"))
    ema200 = _number(row.get("ema200"))
    rsi_value = _number(row.get("rsi"), 50.0)
    macd = _number(row.get("macd"))
    macd_signal = _number(row.get("macd_signal"))
    atr_value = _number(row.get("atr"))
    atr_pct = _number(row.get("atr_pct"), 99.0)
    volume_ratio = _number(row.get("volume_ratio"))

    score = 0
    reasons: list[str] = []

    if ema20 > ema50 > ema200 > 0:
        score += 25
        reasons.append("EMA20 > EMA50 > EMA200: tendencia alcista estructural (+25)")
    elif ema20 > ema50 > 0:
        score += 12
        reasons.append("EMA20 > EMA50: tendencia alcista parcial (+12)")
    else:
        reasons.append("Estructura EMA sin confirmación alcista (+0)")

    if 45 <= rsi_value <= 65:
        score += 15
        reasons.append("RSI en zona saludable 45-65 (+15)")
    elif 35 <= rsi_value < 45:
        score += 8
        reasons.append("RSI recuperable 35-45 (+8)")
    elif rsi_value > 75:
        reasons.append("RSI sobrecomprado >75 (+0)")
    else:
        reasons.append("RSI fuera de la zona objetivo (+0)")

    if macd > macd_signal:
        score += 20
        reasons.append("MACD sobre su señal (+20)")
    else:
        reasons.append("MACD sin confirmación (+0)")

    if volume_ratio >= 1.15:
        score += 15
        reasons.append("Volumen >= 115% de su media (+15)")
    elif volume_ratio >= 1.0:
        score += 8
        reasons.append("Volumen >= media (+8)")
    else:
        reasons.append("Volumen por debajo de su media (+0)")

    if price > ema20 > 0:
        score += 15
        reasons.append("Precio sobre EMA20 (+15)")
    else:
        reasons.append("Precio debajo de EMA20 (+0)")

    if 0 < atr_pct <= 2.5:
        score += 10
        reasons.append("Volatilidad ATR controlada <=2.5% (+10)")
    elif 0 < atr_pct <= 4.0:
        score += 5
        reasons.append("Volatilidad ATR moderada <=4% (+5)")
    else:
        reasons.append("Volatilidad ATR elevada o no disponible (+0)")

    score = min(max(score, 0), 100)

    if score >= buy_threshold:
        signal = "BUY"
    elif score <= sell_threshold:
        signal = "SELL"
    else:
        signal = "WAIT"

    return StrategyDecision(
        signal=signal,
        score=score,
        reasons=reasons,
        price=price,
        ema20=ema20,
        ema50=ema50,
        ema200=ema200,
        rsi=rsi_value,
        macd=macd,
        macd_signal=macd_signal,
        atr=atr_value,
        atr_pct=atr_pct,
        volume_ratio=volume_ratio,
    )


def analyze_frame(
    frame: pd.DataFrame,
    *,
    buy_threshold: int = 75,
    sell_threshold: int = 35,
    rsi_period: int = 14,
    atr_period: int = 14,
) -> tuple[pd.DataFrame, StrategyDecision]:
    if len(frame) < 210:
        raise ValueError("At least 210 candles are required for EMA200 warm-up")

    enriched = enrich_indicators(frame, rsi_period=rsi_period, atr_period=atr_period)
    decision = score_row(
        enriched.iloc[-1],
        buy_threshold=buy_threshold,
        sell_threshold=sell_threshold,
    )
    return enriched, decision
