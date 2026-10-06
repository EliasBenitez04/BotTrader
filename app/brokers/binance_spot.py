import hashlib
import hmac
import time
from decimal import Decimal, ROUND_DOWN
from typing import Any
from urllib.parse import urlencode

import httpx

from app.brokers.base import Broker, ExecutionResult
from app.core.config import Settings
from app.core.exceptions import BinanceAPIError, LiveTradingNotArmedError


class BinanceSpotBroker(Broker):
    def __init__(self, settings: Settings):
        self.settings = settings
        self.base_url = settings.trade_base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=settings.binance_http_timeout_seconds,
            headers={"X-MBX-APIKEY": settings.binance_api_key},
        )
        self._clock_offset_ms = 0
        self._last_clock_sync = 0.0

    async def close(self) -> None:
        await self._client.aclose()

    def _ensure_armed(self) -> None:
        if not self.settings.live_is_armed:
            raise LiveTradingNotArmedError(
                "LIVE trading is not armed. PAPER remains the safe default."
            )

    async def _sync_clock(self) -> None:
        now = time.monotonic()
        if now - self._last_clock_sync < 300:
            return
        response = await self._client.get("/api/v3/time")
        if response.status_code >= 400:
            raise BinanceAPIError(
                f"Could not synchronize Binance clock: HTTP {response.status_code}"
            )
        server_time = int(response.json()["serverTime"])
        local_time = int(time.time() * 1000)
        self._clock_offset_ms = server_time - local_time
        self._last_clock_sync = now

    async def _signed_request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        self._ensure_armed()
        await self._sync_clock()

        payload = dict(params or {})
        payload["recvWindow"] = self.settings.binance_recv_window_ms
        payload["timestamp"] = int(time.time() * 1000) + self._clock_offset_ms

        query = urlencode(payload, doseq=True)
        signature = hmac.new(
            self.settings.binance_api_secret.encode("utf-8"),
            query.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        payload["signature"] = signature

        try:
            response = await self._client.request(method, path, params=payload)
        except httpx.HTTPError as exc:
            raise BinanceAPIError(f"Binance transport error: {exc}") from exc

        if response.status_code >= 500 and method.upper() in {"POST", "DELETE"}:
            raise BinanceAPIError(
                (
                    f"Binance HTTP {response.status_code}; execution state may be unknown. "
                    "The request is deliberately not retried."
                ),
                unknown_execution=True,
            )

        if response.status_code >= 400:
            raise BinanceAPIError(
                f"Binance HTTP {response.status_code}: {response.text[:500]}"
            )

        return response.json()

    async def _public_get(self, path: str, params: dict[str, Any]) -> Any:
        response = await self._client.get(path, params=params)
        if response.status_code >= 400:
            raise BinanceAPIError(
                f"Binance HTTP {response.status_code}: {response.text[:500]}"
            )
        return response.json()

    async def _symbol_info(self, symbol: str) -> dict[str, Any]:
        payload = await self._public_get(
            "/api/v3/exchangeInfo",
            {"symbol": symbol.upper()},
        )
        symbols = payload.get("symbols", [])
        if not symbols:
            raise BinanceAPIError(f"Symbol not found on Binance: {symbol}")
        info = symbols[0]
        if info.get("status") != "TRADING":
            raise BinanceAPIError(f"Symbol {symbol} is not in TRADING status")
        return info

    @staticmethod
    def _filter(info: dict[str, Any], filter_type: str) -> dict[str, Any] | None:
        for item in info.get("filters", []):
            if item.get("filterType") == filter_type:
                return item
        return None

    @staticmethod
    def _floor_to_step(value: float, step: str) -> Decimal:
        amount = Decimal(str(value))
        increment = Decimal(step)
        if increment <= 0:
            return amount
        units = (amount / increment).to_integral_value(rounding=ROUND_DOWN)
        return units * increment

    async def normalize_quantity(
        self,
        *,
        symbol: str,
        quantity: float,
        reference_price: float,
    ) -> tuple[float, dict[str, Any]]:
        info = await self._symbol_info(symbol)
        lot = self._filter(info, "MARKET_LOT_SIZE")
        if not lot or Decimal(str(lot.get("stepSize", "0"))) <= 0:
            lot = self._filter(info, "LOT_SIZE")
        if not lot:
            raise BinanceAPIError(f"No lot-size filter found for {symbol}")

        normalized = self._floor_to_step(quantity, lot["stepSize"])
        min_qty = Decimal(str(lot.get("minQty", "0")))
        max_qty = Decimal(str(lot.get("maxQty", "999999999")))

        if normalized < min_qty or normalized > max_qty:
            raise BinanceAPIError(
                f"Normalized quantity {normalized} violates quantity filters for {symbol}"
            )

        notional_filter = self._filter(info, "NOTIONAL") or self._filter(info, "MIN_NOTIONAL")
        if notional_filter:
            min_notional = Decimal(str(notional_filter.get("minNotional", "0")))
            notional = normalized * Decimal(str(reference_price))
            if notional < min_notional:
                raise BinanceAPIError(
                    f"Order notional {notional} is below minimum {min_notional} for {symbol}"
                )

        return float(normalized), info

    async def normalize_price(self, symbol: str, price: float) -> float:
        info = await self._symbol_info(symbol)
        price_filter = self._filter(info, "PRICE_FILTER")
        if not price_filter:
            return price
        return float(self._floor_to_step(price, price_filter["tickSize"]))

    async def execute_market(
        self,
        *,
        symbol: str,
        side: str,
        quantity: float,
        reference_price: float,
        client_order_id: str,
    ) -> ExecutionResult:
        normalized_qty, info = await self.normalize_quantity(
            symbol=symbol,
            quantity=quantity,
            reference_price=reference_price,
        )

        payload = await self._signed_request(
            "POST",
            "/api/v3/order",
            {
                "symbol": symbol.upper(),
                "side": side.upper(),
                "type": "MARKET",
                "quantity": format(Decimal(str(normalized_qty)), "f"),
                "newClientOrderId": client_order_id,
                "newOrderRespType": "FULL",
            },
        )

        executed_qty = float(payload.get("executedQty", 0))
        quote_qty = float(payload.get("cummulativeQuoteQty", 0))
        if executed_qty <= 0:
            raise BinanceAPIError(f"Binance returned zero executed quantity for {symbol}")

        fill_price = quote_qty / executed_qty if quote_qty > 0 else reference_price
        base_asset = str(info.get("baseAsset", ""))
        quote_asset = str(info.get("quoteAsset", ""))
        fee_quote = 0.0
        net_quantity = executed_qty

        for fill in payload.get("fills", []) or []:
            commission = float(fill.get("commission", 0) or 0)
            commission_asset = fill.get("commissionAsset")
            if side.upper() == "BUY" and commission_asset == base_asset:
                net_quantity -= commission
            elif commission_asset == quote_asset:
                fee_quote += commission

        if net_quantity <= 0:
            raise BinanceAPIError("Net executed base quantity is not positive")

        return ExecutionResult(
            symbol=symbol.upper(),
            side=side.upper(),
            quantity=net_quantity if side.upper() == "BUY" else executed_qty,
            fill_price=fill_price,
            quote_quantity=quote_qty,
            fee_quote=fee_quote,
            order_id=str(payload.get("orderId")) if payload.get("orderId") is not None else None,
            client_order_id=payload.get("clientOrderId") or client_order_id,
        )

    async def quote_balance(self, quote_asset: str) -> float:
        payload = await self._signed_request(
            "GET",
            "/api/v3/account",
            {"omitZeroBalances": "true"},
        )
        for balance in payload.get("balances", []):
            if balance.get("asset") == quote_asset:
                return float(balance.get("free", 0)) + float(balance.get("locked", 0))
        return 0.0

    async def place_oco_protection(
        self,
        *,
        symbol: str,
        quantity: float,
        take_profit: float,
        stop_loss: float,
        client_order_id: str,
    ) -> str:
        normalized_qty, _ = await self.normalize_quantity(
            symbol=symbol,
            quantity=quantity,
            reference_price=stop_loss,
        )
        tp = await self.normalize_price(symbol, take_profit)
        sl = await self.normalize_price(symbol, stop_loss)

        payload = await self._signed_request(
            "POST",
            "/api/v3/orderList/oco",
            {
                "symbol": symbol.upper(),
                "side": "SELL",
                "quantity": format(Decimal(str(normalized_qty)), "f"),
                "listClientOrderId": client_order_id,
                "aboveType": "LIMIT_MAKER",
                "abovePrice": format(Decimal(str(tp)), "f"),
                "belowType": "STOP_LOSS",
                "belowStopPrice": format(Decimal(str(sl)), "f"),
                "newOrderRespType": "RESULT",
            },
        )
        order_list_id = payload.get("orderListId")
        if order_list_id is None:
            raise BinanceAPIError("Binance OCO response did not include orderListId")
        return str(order_list_id)

    async def get_protection_fill(
        self,
        *,
        symbol: str,
        order_list_id: str,
    ) -> ExecutionResult | None:
        order_list = await self._signed_request(
            "GET",
            "/api/v3/orderList",
            {"orderListId": order_list_id},
        )
        if order_list.get("listOrderStatus") not in {"ALL_DONE", "REJECT"}:
            return None

        for order in order_list.get("orders", []):
            order_id = order.get("orderId")
            if order_id is None:
                continue
            detail = await self._signed_request(
                "GET",
                "/api/v3/order",
                {"symbol": symbol.upper(), "orderId": order_id},
            )
            if detail.get("status") != "FILLED":
                continue

            executed_qty = float(detail.get("executedQty", 0))
            quote_qty = float(detail.get("cummulativeQuoteQty", 0))
            if executed_qty <= 0:
                continue

            return ExecutionResult(
                symbol=symbol.upper(),
                side="SELL",
                quantity=executed_qty,
                fill_price=(quote_qty / executed_qty) if quote_qty > 0 else 0.0,
                quote_quantity=quote_qty,
                fee_quote=0.0,
                order_id=str(order_id),
                client_order_id=detail.get("clientOrderId"),
            )

        return None

    async def cancel_protection(self, *, symbol: str, order_list_id: str) -> None:
        await self._signed_request(
            "DELETE",
            "/api/v3/orderList",
            {"symbol": symbol.upper(), "orderListId": order_list_id},
        )
