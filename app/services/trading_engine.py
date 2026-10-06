import json
import logging
import time
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.brokers.base import Broker, ExecutionResult
from app.brokers.binance_spot import BinanceSpotBroker
from app.brokers.paper import PaperBroker
from app.core.config import Settings
from app.core.exceptions import BinanceAPIError, RiskRejectedError
from app.db.models import RiskEvent, Signal, Trade
from app.market.binance import BinanceMarketClient
from app.risk.manager import RiskLimits, RiskManager
from app.services.portfolio import PortfolioStateService
from app.strategy.scoring import StrategyDecision, analyze_frame

logger = logging.getLogger(__name__)


class TradingEngine:
    def __init__(self, db: Session, settings: Settings):
        self.db = db
        self.settings = settings
        self.market = BinanceMarketClient(
            settings.binance_base_url,
            settings.binance_http_timeout_seconds,
        )
        self.broker: Broker
        if settings.trading_mode == "LIVE":
            self.broker = BinanceSpotBroker(settings)
        else:
            self.broker = PaperBroker(
                fee_bps=settings.trading_fee_bps,
                slippage_bps=settings.slippage_bps,
            )

        self.risk = RiskManager(
            RiskLimits(
                risk_per_trade=settings.risk_per_trade,
                max_daily_loss=settings.max_daily_loss,
                max_drawdown=settings.max_drawdown,
                max_open_positions=settings.max_open_positions,
                max_consecutive_losses=settings.max_consecutive_losses,
                max_position_quote_fraction=settings.max_position_quote_fraction,
                stop_loss_pct=settings.stop_loss_pct,
                take_profit_r_multiple=settings.take_profit_r_multiple,
            )
        )
        self.portfolio = PortfolioStateService(db)

    async def __aenter__(self) -> "TradingEngine":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def close(self) -> None:
        await self.market.close()
        await self.broker.close()

    async def analyze(self, symbol: str, timeframe: str | None = None) -> StrategyDecision:
        interval = timeframe or self.settings.default_timeframe
        frame = await self.market.klines(
            symbol,
            interval,
            limit=self.settings.market_lookback_candles,
        )
        _, decision = analyze_frame(
            frame,
            buy_threshold=self.settings.buy_score_threshold,
            sell_threshold=self.settings.sell_score_threshold,
            rsi_period=self.settings.rsi_period,
            atr_period=self.settings.atr_period,
        )
        return decision

    def _persist_signal(
        self,
        symbol: str,
        timeframe: str,
        decision: StrategyDecision,
    ) -> Signal:
        signal = Signal(
            symbol=symbol,
            timeframe=timeframe,
            signal=decision.signal,
            score=decision.score,
            price=Decimal(str(decision.price)),
            ema20=Decimal(str(decision.ema20)),
            ema50=Decimal(str(decision.ema50)),
            ema200=Decimal(str(decision.ema200)),
            rsi=Decimal(str(decision.rsi)),
            macd=Decimal(str(decision.macd)),
            macd_signal=Decimal(str(decision.macd_signal)),
            atr=Decimal(str(decision.atr)),
            volume_ratio=Decimal(str(decision.volume_ratio)),
            reasons_json=json.dumps(decision.reasons, ensure_ascii=False),
        )
        self.db.add(signal)
        self.db.flush()
        return signal

    def _risk_event(
        self,
        event_type: str,
        severity: str,
        message: str,
        *,
        symbol: str | None = None,
        context: dict | None = None,
    ) -> None:
        self.db.add(
            RiskEvent(
                event_type=event_type,
                severity=severity,
                symbol=symbol,
                message=message,
                context_json=json.dumps(context or {}, ensure_ascii=False),
            )
        )

    def _open_trade_for_symbol(self, symbol: str) -> Trade | None:
        return self.db.execute(
            select(Trade).where(
                Trade.symbol == symbol,
                Trade.mode == self.settings.trading_mode,
                Trade.status == "OPEN",
            )
        ).scalars().first()

    async def _equity(self) -> float:
        mode = self.settings.trading_mode
        open_trades = self.portfolio.open_trades(mode)

        if mode == "PAPER":
            equity = self.settings.paper_initial_capital + self.portfolio.realized_pnl(mode)
            for trade in open_trades:
                current = await self.market.ticker_price(trade.symbol)
                equity += float(trade.quantity) * (current - float(trade.entry_price))
            return equity

        quote_balance = await self.broker.quote_balance("USDT")
        equity = quote_balance
        for trade in open_trades:
            current = await self.market.ticker_price(trade.symbol)
            equity += float(trade.quantity) * current
        return equity

    async def process_symbol(
        self,
        symbol: str,
        timeframe: str | None = None,
    ) -> dict:
        symbol = symbol.upper()
        interval = timeframe or self.settings.default_timeframe

        if symbol not in self.settings.symbols:
            raise ValueError(f"{symbol} is not in configured SYMBOLS_CSV")

        decision = await self.analyze(symbol, interval)
        self._persist_signal(symbol, interval, decision)

        open_trade = self._open_trade_for_symbol(symbol)
        if open_trade:
            result = await self._manage_open_trade(open_trade, decision)
            self.db.commit()
            return result

        if decision.signal != "BUY":
            self.db.commit()
            return {
                "action": "NO_ENTRY",
                "symbol": symbol,
                "signal": decision.signal,
                "score": decision.score,
            }

        equity = await self._equity()
        snapshot = self.portfolio.risk_snapshot(
            mode=self.settings.trading_mode,
            equity=equity,
        )
        risk_decision = self.risk.can_open(snapshot)
        if not risk_decision.allowed:
            message = "; ".join(risk_decision.reasons)
            self._risk_event(
                "ENTRY_BLOCKED",
                "WARNING",
                message,
                symbol=symbol,
                context={"equity": equity, "score": decision.score},
            )
            self.db.commit()
            return {
                "action": "RISK_BLOCK",
                "symbol": symbol,
                "score": decision.score,
                "reasons": risk_decision.reasons,
            }

        return await self._open_position(symbol, interval, decision, equity)

    async def _open_position(
        self,
        symbol: str,
        timeframe: str,
        decision: StrategyDecision,
        equity: float,
    ) -> dict:
        stop_loss, take_profit = self.risk.build_levels(
            decision.price,
            decision.atr,
        )
        quantity = self.risk.calculate_position_size(
            equity=equity,
            entry_price=decision.price,
            stop_loss=stop_loss,
        )
        if quantity <= 0:
            raise RiskRejectedError("Calculated position size is zero")

        client_order_id = f"BT{int(time.time() * 1000)}{symbol}"[:36]
        execution = await self.broker.execute_market(
            symbol=symbol,
            side="BUY",
            quantity=quantity,
            reference_price=decision.price,
            client_order_id=client_order_id,
        )

        stop_loss, take_profit = self.risk.build_levels(
            execution.fill_price,
            decision.atr,
        )

        trade = Trade(
            symbol=symbol,
            mode=self.settings.trading_mode,
            status="OPEN",
            side="LONG",
            quantity=Decimal(str(execution.quantity)),
            entry_price=Decimal(str(execution.fill_price)),
            stop_loss=Decimal(str(stop_loss)),
            take_profit=Decimal(str(take_profit)),
            entry_score=decision.score,
            entry_time=datetime.now(timezone.utc),
            fees_quote=Decimal(str(execution.fee_quote)),
            binance_order_id=execution.order_id,
            client_order_id=execution.client_order_id or client_order_id,
            protection_status="NOT_REQUIRED" if self.settings.trading_mode == "PAPER" else "PENDING",
        )
        self.db.add(trade)
        self.db.flush()

        if self.settings.trading_mode == "LIVE":
            try:
                oco_id = await self.broker.place_oco_protection(
                    symbol=symbol,
                    quantity=execution.quantity,
                    take_profit=take_profit,
                    stop_loss=stop_loss,
                    client_order_id=f"OCO{trade.id}{int(time.time())}"[:36],
                )
                trade.protection_order_list_id = oco_id
                trade.protection_status = "ACTIVE"
            except BinanceAPIError as exc:
                trade.protection_status = "UNKNOWN" if exc.unknown_execution else "FAILED"
                trade.last_error = str(exc)
                self._risk_event(
                    "PROTECTION_FAILED",
                    "CRITICAL",
                    str(exc),
                    symbol=symbol,
                    context={"trade_id": trade.id},
                )

                if not exc.unknown_execution:
                    emergency = await self.broker.execute_market(
                        symbol=symbol,
                        side="SELL",
                        quantity=float(trade.quantity),
                        reference_price=decision.price,
                        client_order_id=f"EMG{int(time.time() * 1000)}"[:36],
                    )
                    self._finalize_trade(trade, emergency, "PROTECTION_FAILED")
                    trade.protection_status = "FAILED_CLOSED"

        self.db.commit()
        return {
            "action": "OPENED" if trade.status == "OPEN" else "EMERGENCY_CLOSED",
            "trade_id": trade.id,
            "symbol": symbol,
            "quantity": float(trade.quantity),
            "entry_price": float(trade.entry_price),
            "stop_loss": float(trade.stop_loss),
            "take_profit": float(trade.take_profit),
            "score": decision.score,
            "protection_status": trade.protection_status,
        }

    async def _manage_open_trade(
        self,
        trade: Trade,
        decision: StrategyDecision,
    ) -> dict:
        current_price = decision.price

        if (
            self.settings.trading_mode == "LIVE"
            and trade.protection_order_list_id
            and trade.protection_status == "ACTIVE"
        ):
            fill = await self.broker.get_protection_fill(
                symbol=trade.symbol,
                order_list_id=trade.protection_order_list_id,
            )
            if fill:
                self._finalize_trade(trade, fill, "EXCHANGE_PROTECTION")
                trade.protection_status = "FILLED"
                return {"action": "CLOSED", "trade_id": trade.id, "reason": "EXCHANGE_PROTECTION"}

            if decision.signal == "SELL":
                await self.broker.cancel_protection(
                    symbol=trade.symbol,
                    order_list_id=trade.protection_order_list_id,
                )
                trade.protection_status = "CANCELLED"
                execution = await self.broker.execute_market(
                    symbol=trade.symbol,
                    side="SELL",
                    quantity=float(trade.quantity),
                    reference_price=current_price,
                    client_order_id=f"EXIT{int(time.time() * 1000)}"[:36],
                )
                self._finalize_trade(trade, execution, "STRATEGY_EXIT")
                return {"action": "CLOSED", "trade_id": trade.id, "reason": "STRATEGY_EXIT"}

            return {
                "action": "HOLD",
                "trade_id": trade.id,
                "symbol": trade.symbol,
                "score": decision.score,
                "protection_status": trade.protection_status,
            }

        exit_reason: str | None = None
        if current_price <= float(trade.stop_loss):
            exit_reason = "STOP_LOSS"
        elif current_price >= float(trade.take_profit):
            exit_reason = "TAKE_PROFIT"
        elif decision.signal == "SELL":
            exit_reason = "STRATEGY_EXIT"

        if exit_reason is None:
            return {
                "action": "HOLD",
                "trade_id": trade.id,
                "symbol": trade.symbol,
                "score": decision.score,
                "protection_status": trade.protection_status,
            }

        execution = await self.broker.execute_market(
            symbol=trade.symbol,
            side="SELL",
            quantity=float(trade.quantity),
            reference_price=current_price,
            client_order_id=f"EXIT{int(time.time() * 1000)}"[:36],
        )
        self._finalize_trade(trade, execution, exit_reason)
        return {"action": "CLOSED", "trade_id": trade.id, "reason": exit_reason}

    def _finalize_trade(
        self,
        trade: Trade,
        execution: ExecutionResult,
        exit_reason: str,
    ) -> None:
        entry_notional = float(trade.quantity) * float(trade.entry_price)
        gross_pnl = float(trade.quantity) * (execution.fill_price - float(trade.entry_price))
        total_fees = float(trade.fees_quote or 0) + execution.fee_quote
        net_pnl = gross_pnl - total_fees
        pnl_percent = (net_pnl / entry_notional * 100) if entry_notional > 0 else 0.0

        trade.status = "CLOSED"
        trade.exit_price = Decimal(str(execution.fill_price))
        trade.exit_time = datetime.now(timezone.utc)
        trade.pnl_quote = Decimal(str(net_pnl))
        trade.pnl_percent = Decimal(str(pnl_percent))
        trade.fees_quote = Decimal(str(total_fees))
        trade.exit_reason = exit_reason
