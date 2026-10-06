import hashlib
import json
import logging
import time
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.brokers.base import Broker, ExecutionResult
from app.brokers.binance_spot import BinanceSpotBroker
from app.brokers.paper import PaperBroker
from app.core.config import Settings
from app.core.exceptions import (
    BinanceAPIError,
    MarketDataError,
    ProtectionStateError,
    RiskRejectedError,
)
from app.db.models import RiskEvent, Signal, Trade
from app.market.binance import BinanceMarketClient
from app.risk.manager import RiskLimits, RiskManager
from app.services.portfolio import PortfolioStateService
from app.services.runtime_state import RuntimeStateService
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
        self.runtime = RuntimeStateService(db)

    async def __aenter__(self) -> "TradingEngine":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def close(self) -> None:
        await self.market.close()
        await self.broker.close()

    def live_halt_status(self) -> dict | None:
        return self.runtime.live_halt()

    def clear_live_halt(self) -> None:
        self.runtime.clear_live_halt()
        self.db.commit()

    async def analyze(self, symbol: str, timeframe: str | None = None) -> StrategyDecision:
        interval = timeframe or self.settings.default_timeframe
        frame = await self.market.klines(
            symbol,
            interval,
            limit=self.settings.market_lookback_candles,
        )
        server_time_ms = await self.market.server_time_ms()
        closed = frame.loc[frame["close_time_ms"] < server_time_ms].copy()

        if len(closed) < 210:
            raise MarketDataError(
                f"Not enough closed candles for {symbol.upper()} {interval}: {len(closed)}"
            )

        _, decision = analyze_frame(
            closed,
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
        if decision.candle_close_time is not None:
            existing = self.db.execute(
                select(Signal).where(
                    Signal.symbol == symbol,
                    Signal.timeframe == timeframe,
                    Signal.candle_close_time == decision.candle_close_time,
                )
            ).scalars().first()
            if existing:
                return existing

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
            candle_open_time=decision.candle_open_time,
            candle_close_time=decision.candle_close_time,
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

    def _halt_live(
        self,
        *,
        reason: str,
        symbol: str | None,
        context: dict | None = None,
    ) -> None:
        if self.settings.trading_mode != "LIVE":
            return
        payload = self.runtime.halt_live(
            reason=reason,
            symbol=symbol,
            context=context,
        )
        self._risk_event(
            "LIVE_TRADING_HALTED",
            "CRITICAL",
            reason,
            symbol=symbol,
            context=payload,
        )

    def _symbol_lock_id(self, symbol: str, timeframe: str) -> int:
        raw = (
            f"{self.settings.trading_mode}:{symbol.upper()}:{timeframe}".encode()
        )
        digest = hashlib.blake2b(raw, digest_size=8).digest()
        return int.from_bytes(digest, byteorder="big", signed=True)

    def _acquire_symbol_lock(self, symbol: str, timeframe: str) -> bool:
        lock_id = self._symbol_lock_id(symbol, timeframe)
        return bool(
            self.db.execute(
                text("SELECT pg_try_advisory_xact_lock(:lock_id)"),
                {"lock_id": lock_id},
            ).scalar()
        )

    def _last_candle_key(self, symbol: str, timeframe: str) -> str:
        return (
            f"last_candle:{self.settings.trading_mode}:{symbol.upper()}:{timeframe}"
        )

    def _is_new_candle(
        self,
        symbol: str,
        timeframe: str,
        decision: StrategyDecision,
    ) -> bool:
        if decision.candle_close_time is None:
            return True
        key = self._last_candle_key(symbol, timeframe)
        current = decision.candle_close_time.isoformat()
        previous = self.runtime.get(key)
        return previous != current

    def _mark_candle_processed(
        self,
        symbol: str,
        timeframe: str,
        decision: StrategyDecision,
    ) -> None:
        if decision.candle_close_time is None:
            return
        self.runtime.set(
            self._last_candle_key(symbol, timeframe),
            decision.candle_close_time.isoformat(),
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
                equity += float(trade.quantity) * (
                    current - float(trade.entry_price)
                )
                equity -= float(trade.fees_quote or 0)
            return equity

        quote_balance = await self.broker.quote_balance(self.settings.quote_asset)
        equity = quote_balance
        for trade in open_trades:
            current = await self.market.ticker_price(trade.symbol)
            equity += float(trade.quantity) * current
        return equity

    async def _available_quote(self) -> float:
        if self.settings.trading_mode == "LIVE":
            return await self.broker.quote_balance(self.settings.quote_asset)

        cash = self.settings.paper_initial_capital + self.portfolio.realized_pnl("PAPER")
        for trade in self.portfolio.open_trades("PAPER"):
            cash -= float(trade.quantity) * float(trade.entry_price)
            cash -= float(trade.fees_quote or 0)
        return max(0.0, cash)

    async def _execute_market_safely(
        self,
        *,
        symbol: str,
        side: str,
        quantity: float,
        reference_price: float,
        client_order_id: str,
        trade: Trade | None = None,
    ) -> ExecutionResult:
        try:
            return await self.broker.execute_market(
                symbol=symbol,
                side=side,
                quantity=quantity,
                reference_price=reference_price,
                client_order_id=client_order_id,
            )
        except BinanceAPIError as exc:
            if self.settings.trading_mode == "LIVE" and exc.unknown_execution:
                if trade is not None:
                    trade.protection_status = "UNKNOWN"
                    trade.last_error = str(exc)
                self._halt_live(
                    reason=(
                        "Binance order execution state is unknown; "
                        "manual reconciliation required"
                    ),
                    symbol=symbol,
                    context={
                        "side": side,
                        "client_order_id": client_order_id,
                        "error": str(exc),
                        "trade_id": trade.id if trade else None,
                    },
                )
                self.db.commit()
            raise

    async def process_symbol(
        self,
        symbol: str,
        timeframe: str | None = None,
    ) -> dict:
        symbol = symbol.upper()
        interval = timeframe or self.settings.default_timeframe

        if symbol not in self.settings.symbols:
            raise ValueError(f"{symbol} is not in configured SYMBOLS_CSV")

        if not self._acquire_symbol_lock(symbol, interval):
            self.db.rollback()
            return {
                "action": "LOCKED",
                "symbol": symbol,
                "reason": "Another process is already handling this symbol/timeframe",
            }

        halt = self.runtime.live_halt()
        if self.settings.trading_mode == "LIVE" and halt:
            self.db.commit()
            return {
                "action": "HALTED",
                "symbol": symbol,
                "halt": halt,
            }

        decision = await self.analyze(symbol, interval)
        new_candle = self._is_new_candle(symbol, interval, decision)

        if new_candle:
            self._persist_signal(symbol, interval, decision)
            self._mark_candle_processed(symbol, interval, decision)

        open_trade = self._open_trade_for_symbol(symbol)
        if open_trade:
            result = await self._manage_open_trade(
                open_trade,
                decision,
                allow_strategy_exit=new_candle,
            )
            self.db.commit()
            return result

        if not new_candle:
            self.db.commit()
            return {
                "action": "NO_NEW_CANDLE",
                "symbol": symbol,
                "signal": decision.signal,
                "score": decision.score,
            }

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

        return await self._open_position(symbol, decision, equity)

    async def _open_position(
        self,
        symbol: str,
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

        candle_ms = (
            int(decision.candle_close_time.timestamp() * 1000)
            if decision.candle_close_time
            else int(time.time() * 1000)
        )
        available_quote = await self._available_quote()
        fee_buffer = 1 + (self.settings.trading_fee_bps / 10_000)
        max_affordable = (
            available_quote / (decision.price * fee_buffer)
            if decision.price > 0
            else 0.0
        )
        quantity = min(quantity, max_affordable)
        if quantity <= 0:
            raise RiskRejectedError("Insufficient available quote balance")

        mode_code = "L" if self.settings.trading_mode == "LIVE" else "P"
        client_order_id = f"BT{mode_code}{symbol}{candle_ms}"[:36]
        execution = await self._execute_market_safely(
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
            entry_time=datetime.now(UTC),
            fees_quote=Decimal(str(execution.fee_quote)),
            binance_order_id=execution.order_id,
            client_order_id=execution.client_order_id or client_order_id,
            protection_status=(
                "NOT_REQUIRED" if self.settings.trading_mode == "PAPER" else "PENDING"
            ),
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
                    client_order_id=f"OCO{trade.id}{candle_ms}"[:36],
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

                if exc.unknown_execution:
                    self._halt_live(
                        reason=(
                            "OCO protection state is unknown; manual reconciliation required"
                        ),
                        symbol=symbol,
                        context={"trade_id": trade.id, "error": str(exc)},
                    )
                else:
                    emergency = await self._execute_market_safely(
                        symbol=symbol,
                        side="SELL",
                        quantity=float(trade.quantity),
                        reference_price=decision.price,
                        client_order_id=f"EMG{trade.id}{candle_ms}"[:36],
                        trade=trade,
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
        *,
        allow_strategy_exit: bool,
    ) -> dict:
        current_price = await self.market.ticker_price(trade.symbol)

        if self.settings.trading_mode == "LIVE" and trade.protection_status == "UNKNOWN":
            return {
                "action": "MANUAL_RECONCILIATION",
                "trade_id": trade.id,
                "symbol": trade.symbol,
                "reason": trade.last_error or "Protection/order state is unknown",
            }

        if (
            self.settings.trading_mode == "LIVE"
            and trade.protection_order_list_id
            and trade.protection_status == "ACTIVE"
        ):
            try:
                fill = await self.broker.get_protection_fill(
                    symbol=trade.symbol,
                    order_list_id=trade.protection_order_list_id,
                )
            except ProtectionStateError as exc:
                trade.protection_status = "FAILED"
                trade.last_error = str(exc)
                self._halt_live(
                    reason="Exchange-side OCO protection is no longer safe",
                    symbol=trade.symbol,
                    context={"trade_id": trade.id, "error": str(exc)},
                )
                self.db.commit()
                return {
                    "action": "MANUAL_RECONCILIATION",
                    "trade_id": trade.id,
                    "symbol": trade.symbol,
                    "reason": str(exc),
                }

            if fill:
                self._finalize_trade(trade, fill, "EXCHANGE_PROTECTION")
                trade.protection_status = "FILLED"
                return {
                    "action": "CLOSED",
                    "trade_id": trade.id,
                    "reason": "EXCHANGE_PROTECTION",
                }

            if allow_strategy_exit and decision.signal == "SELL":
                try:
                    await self.broker.cancel_protection(
                        symbol=trade.symbol,
                        order_list_id=trade.protection_order_list_id,
                    )
                except BinanceAPIError as exc:
                    if exc.unknown_execution:
                        trade.protection_status = "UNKNOWN"
                        trade.last_error = str(exc)
                        self._halt_live(
                            reason=(
                                "OCO cancellation state is unknown; "
                                "manual reconciliation required"
                            ),
                            symbol=trade.symbol,
                            context={"trade_id": trade.id, "error": str(exc)},
                        )
                        self.db.commit()
                    raise

                trade.protection_status = "CANCELLED"
                execution = await self._execute_market_safely(
                    symbol=trade.symbol,
                    side="SELL",
                    quantity=float(trade.quantity),
                    reference_price=current_price,
                    client_order_id=f"EXIT{trade.id}{int(time.time())}"[:36],
                    trade=trade,
                )
                self._finalize_trade(trade, execution, "STRATEGY_EXIT")
                return {
                    "action": "CLOSED",
                    "trade_id": trade.id,
                    "reason": "STRATEGY_EXIT",
                }

            return {
                "action": "HOLD",
                "trade_id": trade.id,
                "symbol": trade.symbol,
                "score": decision.score,
                "current_price": current_price,
                "protection_status": trade.protection_status,
            }

        exit_reason: str | None = None
        if current_price <= float(trade.stop_loss):
            exit_reason = "STOP_LOSS"
        elif current_price >= float(trade.take_profit):
            exit_reason = "TAKE_PROFIT"
        elif allow_strategy_exit and decision.signal == "SELL":
            exit_reason = "STRATEGY_EXIT"

        if exit_reason is None:
            return {
                "action": "HOLD",
                "trade_id": trade.id,
                "symbol": trade.symbol,
                "score": decision.score,
                "current_price": current_price,
                "protection_status": trade.protection_status,
            }

        execution = await self._execute_market_safely(
            symbol=trade.symbol,
            side="SELL",
            quantity=float(trade.quantity),
            reference_price=current_price,
            client_order_id=f"EXIT{trade.id}{int(time.time())}"[:36],
            trade=trade,
        )
        self._finalize_trade(trade, execution, exit_reason)
        return {
            "action": "CLOSED",
            "trade_id": trade.id,
            "reason": exit_reason,
        }

    def _finalize_trade(
        self,
        trade: Trade,
        execution: ExecutionResult,
        exit_reason: str,
    ) -> None:
        entry_notional = float(trade.quantity) * float(trade.entry_price)
        gross_pnl = float(trade.quantity) * (
            execution.fill_price - float(trade.entry_price)
        )
        total_fees = float(trade.fees_quote or 0) + execution.fee_quote
        net_pnl = gross_pnl - total_fees
        pnl_percent = (
            net_pnl / entry_notional * 100 if entry_notional > 0 else 0.0
        )

        trade.status = "CLOSED"
        trade.exit_price = Decimal(str(execution.fill_price))
        trade.exit_time = datetime.now(UTC)
        trade.pnl_quote = Decimal(str(net_pnl))
        trade.pnl_percent = Decimal(str(pnl_percent))
        trade.fees_quote = Decimal(str(total_fees))
        trade.exit_reason = exit_reason
