import json
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import BacktestRun, RiskEvent, Signal, Trade
from app.services.portfolio import PortfolioStateService


class DashboardService:
    def __init__(self, db: Session, settings: Settings):
        self.db = db
        self.settings = settings
        self.portfolio = PortfolioStateService(db)

    def summary(self) -> dict:
        mode = self.settings.trading_mode
        all_closed = list(
            self.db.execute(
                select(Trade)
                .where(Trade.mode == mode, Trade.status == "CLOSED")
                .order_by(Trade.exit_time.desc())
            ).scalars()
        )
        open_trades = self.portfolio.open_trades(mode)
        wins = [trade for trade in all_closed if float(trade.pnl_quote or 0) > 0]
        realized = sum(float(trade.pnl_quote or Decimal("0")) for trade in all_closed)

        latest_signals: list[dict] = []
        for symbol in self.settings.symbols:
            signal = self.db.execute(
                select(Signal)
                .where(Signal.symbol == symbol)
                .order_by(Signal.created_at.desc())
                .limit(1)
            ).scalars().first()
            if signal:
                latest_signals.append(
                    {
                        "symbol": signal.symbol,
                        "timeframe": signal.timeframe,
                        "signal": signal.signal,
                        "score": signal.score,
                        "price": float(signal.price),
                        "rsi": float(signal.rsi or 0),
                        "created_at": signal.created_at.isoformat(),
                    }
                )

        latest_backtest = self.db.execute(
            select(BacktestRun).order_by(BacktestRun.created_at.desc()).limit(1)
        ).scalars().first()

        risk_events = list(
            self.db.execute(
                select(RiskEvent).order_by(RiskEvent.created_at.desc()).limit(10)
            ).scalars()
        )

        return {
            "mode": mode,
            "live_armed": self.settings.live_is_armed,
            "binance_testnet": self.settings.binance_use_testnet,
            "paper_initial_capital": self.settings.paper_initial_capital,
            "realized_pnl": realized,
            "paper_equity_realized": (
                self.settings.paper_initial_capital + realized if mode == "PAPER" else None
            ),
            "closed_trades": len(all_closed),
            "winning_trades": len(wins),
            "win_rate": (len(wins) / len(all_closed) * 100) if all_closed else 0.0,
            "open_trades": [
                {
                    "id": trade.id,
                    "symbol": trade.symbol,
                    "quantity": float(trade.quantity),
                    "entry_price": float(trade.entry_price),
                    "stop_loss": float(trade.stop_loss),
                    "take_profit": float(trade.take_profit),
                    "protection_status": trade.protection_status,
                    "entry_time": trade.entry_time.isoformat(),
                }
                for trade in open_trades
            ],
            "signals": latest_signals,
            "latest_backtest": (
                {
                    "id": latest_backtest.id,
                    "symbol": latest_backtest.symbol,
                    "timeframe": latest_backtest.timeframe,
                    "total_trades": latest_backtest.total_trades,
                    "win_rate": float(latest_backtest.win_rate),
                    "profit_factor": (
                        float(latest_backtest.profit_factor)
                        if latest_backtest.profit_factor is not None
                        else None
                    ),
                    "max_drawdown": float(latest_backtest.max_drawdown),
                    "return_pct": float(latest_backtest.return_pct),
                    "statistically_sufficient": latest_backtest.statistically_sufficient,
                }
                if latest_backtest
                else None
            ),
            "risk_events": [
                {
                    "type": event.event_type,
                    "severity": event.severity,
                    "symbol": event.symbol,
                    "message": event.message,
                    "context": json.loads(event.context_json or "{}"),
                    "created_at": event.created_at.isoformat(),
                }
                for event in risk_events
            ],
        }
