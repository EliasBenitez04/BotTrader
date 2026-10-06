from dataclasses import asdict, dataclass
from datetime import datetime
from math import sqrt

import numpy as np
import pandas as pd

from app.risk.manager import RiskLimits, RiskManager, RiskSnapshot
from app.strategy.indicators import enrich_indicators
from app.strategy.scoring import score_row


@dataclass(frozen=True)
class BacktestTradeResult:
    entry_time: datetime
    exit_time: datetime
    quantity: float
    entry_price: float
    exit_price: float
    pnl_quote: float
    pnl_percent: float
    exit_reason: str
    entry_score: int


@dataclass(frozen=True)
class BacktestMetrics:
    initial_capital: float
    final_capital: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    profit_factor: float | None
    max_drawdown: float
    return_pct: float
    expectancy_pct: float
    sharpe_ratio: float | None
    statistically_sufficient: bool


@dataclass(frozen=True)
class BacktestResult:
    symbol: str
    timeframe: str
    start_time: datetime
    end_time: datetime
    metrics: BacktestMetrics
    trades: list[BacktestTradeResult]

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat(),
            "metrics": asdict(self.metrics),
            "trades": [
                {
                    **asdict(trade),
                    "entry_time": trade.entry_time.isoformat(),
                    "exit_time": trade.exit_time.isoformat(),
                }
                for trade in self.trades
            ],
        }


class Backtester:
    def __init__(
        self,
        *,
        risk_limits: RiskLimits,
        buy_threshold: int,
        sell_threshold: int,
        rsi_period: int,
        atr_period: int,
        fee_bps: float,
        slippage_bps: float,
        min_trades: int,
    ):
        self.risk = RiskManager(risk_limits)
        self.buy_threshold = buy_threshold
        self.sell_threshold = sell_threshold
        self.rsi_period = rsi_period
        self.atr_period = atr_period
        self.fee_rate = fee_bps / 10_000
        self.slippage_rate = slippage_bps / 10_000
        self.min_trades = min_trades

    def run(
        self,
        frame: pd.DataFrame,
        *,
        symbol: str,
        timeframe: str,
        initial_capital: float,
    ) -> BacktestResult:
        if initial_capital <= 0:
            raise ValueError("initial_capital must be positive")
        if len(frame) < 250:
            raise ValueError("Backtest requires at least 250 candles")

        data = enrich_indicators(
            frame,
            rsi_period=self.rsi_period,
            atr_period=self.atr_period,
        ).reset_index(drop=True)

        cash = float(initial_capital)
        peak_equity = cash
        day_start_equity = cash
        current_day = None
        consecutive_losses = 0
        trades: list[BacktestTradeResult] = []
        equity_curve: list[float] = [cash]
        position: dict | None = None

        for index in range(210, len(data)):
            row = data.iloc[index]
            timestamp = pd.Timestamp(row["open_time"]).to_pydatetime()
            day = timestamp.date()

            mark_price = float(row["close"])
            current_equity = cash
            if position:
                current_equity += position["quantity"] * mark_price

            if current_day != day:
                current_day = day
                day_start_equity = current_equity

            peak_equity = max(peak_equity, current_equity)
            decision = score_row(
                row,
                buy_threshold=self.buy_threshold,
                sell_threshold=self.sell_threshold,
            )

            if position:
                exit_price: float | None = None
                exit_reason: str | None = None

                stop_hit = float(row["low"]) <= position["stop_loss"]
                target_hit = float(row["high"]) >= position["take_profit"]

                if stop_hit:
                    exit_price = position["stop_loss"] * (1 - self.slippage_rate)
                    exit_reason = "STOP_LOSS"
                elif target_hit:
                    exit_price = position["take_profit"] * (1 - self.slippage_rate)
                    exit_reason = "TAKE_PROFIT"
                elif decision.signal == "SELL":
                    exit_price = mark_price * (1 - self.slippage_rate)
                    exit_reason = "STRATEGY_EXIT"

                if exit_price is not None and exit_reason is not None:
                    gross_exit = position["quantity"] * exit_price
                    exit_fee = gross_exit * self.fee_rate
                    cash += gross_exit - exit_fee

                    pnl_quote = (
                        gross_exit
                        - exit_fee
                        - position["entry_notional"]
                        - position["entry_fee"]
                    )
                    pnl_percent = (
                        pnl_quote / position["entry_notional"] * 100
                        if position["entry_notional"] > 0
                        else 0.0
                    )
                    trade = BacktestTradeResult(
                        entry_time=position["entry_time"],
                        exit_time=timestamp,
                        quantity=position["quantity"],
                        entry_price=position["entry_price"],
                        exit_price=exit_price,
                        pnl_quote=pnl_quote,
                        pnl_percent=pnl_percent,
                        exit_reason=exit_reason,
                        entry_score=position["entry_score"],
                    )
                    trades.append(trade)
                    consecutive_losses = consecutive_losses + 1 if pnl_quote < 0 else 0
                    position = None
                    current_equity = cash

            if position is None and decision.signal == "BUY":
                snapshot = RiskSnapshot(
                    equity=current_equity,
                    day_start_equity=day_start_equity,
                    peak_equity=peak_equity,
                    open_positions=0,
                    consecutive_losses=consecutive_losses,
                )
                risk_decision = self.risk.can_open(snapshot)

                if risk_decision.allowed:
                    reference_entry = mark_price * (1 + self.slippage_rate)
                    stop_loss, take_profit = self.risk.build_levels(
                        reference_entry,
                        decision.atr,
                    )
                    quantity = self.risk.calculate_position_size(
                        equity=current_equity,
                        entry_price=reference_entry,
                        stop_loss=stop_loss,
                    )
                    max_affordable = cash / (
                        reference_entry * (1 + self.fee_rate)
                    )
                    quantity = min(quantity, max_affordable)

                    if quantity > 0:
                        entry_notional = quantity * reference_entry
                        entry_fee = entry_notional * self.fee_rate
                        cash -= entry_notional + entry_fee
                        position = {
                            "entry_time": timestamp,
                            "entry_price": reference_entry,
                            "entry_notional": entry_notional,
                            "entry_fee": entry_fee,
                            "quantity": quantity,
                            "stop_loss": stop_loss,
                            "take_profit": take_profit,
                            "entry_score": decision.score,
                        }

            current_equity = cash
            if position:
                current_equity += position["quantity"] * mark_price
            equity_curve.append(current_equity)

        if position:
            row = data.iloc[-1]
            timestamp = pd.Timestamp(row["close_time"]).to_pydatetime()
            exit_price = float(row["close"]) * (1 - self.slippage_rate)
            gross_exit = position["quantity"] * exit_price
            exit_fee = gross_exit * self.fee_rate
            cash += gross_exit - exit_fee
            pnl_quote = (
                gross_exit - exit_fee - position["entry_notional"] - position["entry_fee"]
            )
            pnl_percent = pnl_quote / position["entry_notional"] * 100
            trades.append(
                BacktestTradeResult(
                    entry_time=position["entry_time"],
                    exit_time=timestamp,
                    quantity=position["quantity"],
                    entry_price=position["entry_price"],
                    exit_price=exit_price,
                    pnl_quote=pnl_quote,
                    pnl_percent=pnl_percent,
                    exit_reason="END_OF_DATA",
                    entry_score=position["entry_score"],
                )
            )
            equity_curve.append(cash)

        metrics = self._metrics(initial_capital, cash, trades, equity_curve)
        start_time = pd.Timestamp(data.iloc[210]["open_time"]).to_pydatetime()
        end_time = pd.Timestamp(data.iloc[-1]["close_time"]).to_pydatetime()

        return BacktestResult(
            symbol=symbol.upper(),
            timeframe=timeframe,
            start_time=start_time,
            end_time=end_time,
            metrics=metrics,
            trades=trades,
        )

    def _metrics(
        self,
        initial_capital: float,
        final_capital: float,
        trades: list[BacktestTradeResult],
        equity_curve: list[float],
    ) -> BacktestMetrics:
        wins = [trade for trade in trades if trade.pnl_quote > 0]
        losses = [trade for trade in trades if trade.pnl_quote < 0]
        total = len(trades)

        gross_profit = sum(trade.pnl_quote for trade in wins)
        gross_loss = abs(sum(trade.pnl_quote for trade in losses))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else (
            None if gross_profit == 0 else float("inf")
        )

        curve = np.asarray(equity_curve, dtype=float)
        peaks = np.maximum.accumulate(curve)
        drawdowns = np.where(peaks > 0, (peaks - curve) / peaks * 100, 0)
        max_drawdown = float(drawdowns.max()) if len(drawdowns) else 0.0

        returns = np.asarray([trade.pnl_percent for trade in trades], dtype=float)
        sharpe = None
        if len(returns) >= 2 and float(np.std(returns, ddof=1)) > 0:
            sharpe = float(
                np.mean(returns) / np.std(returns, ddof=1) * sqrt(len(returns))
            )

        return BacktestMetrics(
            initial_capital=initial_capital,
            final_capital=final_capital,
            total_trades=total,
            winning_trades=len(wins),
            losing_trades=len(losses),
            win_rate=(len(wins) / total * 100) if total else 0.0,
            profit_factor=profit_factor,
            max_drawdown=max_drawdown,
            return_pct=(final_capital / initial_capital - 1) * 100,
            expectancy_pct=float(np.mean(returns)) if len(returns) else 0.0,
            sharpe_ratio=sharpe,
            statistically_sufficient=total >= self.min_trades,
        )
