import json
from decimal import Decimal

from sqlalchemy.orm import Session

from app.backtesting.engine import BacktestResult, Backtester
from app.core.config import Settings
from app.db.models import BacktestRun, BacktestTrade
from app.market.binance import BinanceMarketClient
from app.risk.manager import RiskLimits
from app.schemas import BacktestRequest


class BacktestService:
    def __init__(self, db: Session, settings: Settings):
        self.db = db
        self.settings = settings

    async def run(self, request: BacktestRequest) -> tuple[int, BacktestResult]:
        start_ms = int(request.start_time.timestamp() * 1000)
        end_ms = int(request.end_time.timestamp() * 1000)

        async with BinanceMarketClient(
            self.settings.binance_base_url,
            self.settings.binance_http_timeout_seconds,
        ) as market:
            frame = await market.historical_klines(
                request.symbol,
                request.timeframe,
                start_time_ms=start_ms,
                end_time_ms=end_ms,
                max_candles=request.max_candles,
            )

        backtester = Backtester(
            risk_limits=RiskLimits(
                risk_per_trade=self.settings.risk_per_trade,
                max_daily_loss=self.settings.max_daily_loss,
                max_drawdown=self.settings.max_drawdown,
                max_open_positions=1,
                max_consecutive_losses=self.settings.max_consecutive_losses,
                max_position_quote_fraction=self.settings.max_position_quote_fraction,
                stop_loss_pct=self.settings.stop_loss_pct,
                take_profit_r_multiple=self.settings.take_profit_r_multiple,
            ),
            buy_threshold=self.settings.buy_score_threshold,
            sell_threshold=self.settings.sell_score_threshold,
            rsi_period=self.settings.rsi_period,
            atr_period=self.settings.atr_period,
            fee_bps=self.settings.trading_fee_bps,
            slippage_bps=self.settings.slippage_bps,
            min_trades=self.settings.min_backtest_trades,
        )
        result = backtester.run(
            frame,
            symbol=request.symbol,
            timeframe=request.timeframe,
            initial_capital=request.initial_capital,
        )
        metrics = result.metrics

        parameters = {
            "buy_score_threshold": self.settings.buy_score_threshold,
            "sell_score_threshold": self.settings.sell_score_threshold,
            "risk_per_trade": self.settings.risk_per_trade,
            "max_daily_loss": self.settings.max_daily_loss,
            "max_drawdown": self.settings.max_drawdown,
            "stop_loss_pct": self.settings.stop_loss_pct,
            "take_profit_r_multiple": self.settings.take_profit_r_multiple,
            "trading_fee_bps": self.settings.trading_fee_bps,
            "slippage_bps": self.settings.slippage_bps,
        }

        run = BacktestRun(
            symbol=result.symbol,
            timeframe=result.timeframe,
            start_time=result.start_time,
            end_time=result.end_time,
            initial_capital=Decimal(str(metrics.initial_capital)),
            final_capital=Decimal(str(metrics.final_capital)),
            total_trades=metrics.total_trades,
            winning_trades=metrics.winning_trades,
            losing_trades=metrics.losing_trades,
            win_rate=Decimal(str(metrics.win_rate)),
            profit_factor=(
                Decimal(str(metrics.profit_factor))
                if metrics.profit_factor is not None
                else None
            ),
            max_drawdown=Decimal(str(metrics.max_drawdown)),
            return_pct=Decimal(str(metrics.return_pct)),
            expectancy_pct=Decimal(str(metrics.expectancy_pct)),
            sharpe_ratio=(
                Decimal(str(metrics.sharpe_ratio))
                if metrics.sharpe_ratio is not None
                else None
            ),
            statistically_sufficient=metrics.statistically_sufficient,
            parameters_json=json.dumps(parameters),
        )
        self.db.add(run)
        self.db.flush()

        self.db.add_all(
            [
                BacktestTrade(
                    backtest_run_id=run.id,
                    entry_time=trade.entry_time,
                    exit_time=trade.exit_time,
                    quantity=Decimal(str(trade.quantity)),
                    entry_price=Decimal(str(trade.entry_price)),
                    exit_price=Decimal(str(trade.exit_price)),
                    pnl_quote=Decimal(str(trade.pnl_quote)),
                    pnl_percent=Decimal(str(trade.pnl_percent)),
                    exit_reason=trade.exit_reason,
                    entry_score=trade.entry_score,
                )
                for trade in result.trades
            ]
        )
        self.db.commit()
        return int(run.id), result
