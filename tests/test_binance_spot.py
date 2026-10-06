import asyncio
import time

import pytest

from app.brokers.binance_spot import BinanceSpotBroker
from app.core.config import Settings
from app.core.exceptions import BinanceAPIError, ProtectionStateError


def live_settings() -> Settings:
    return Settings(
        trading_mode="LIVE",
        live_trading_enabled=True,
        live_confirmation="ENABLE_LIVE_SPOT",
        binance_api_key="key",
        binance_api_secret="secret",
    )


def test_timeout_error_is_marked_as_unknown_execution() -> None:
    class FakeResponse:
        status_code = 400
        text = '{"code":-1007,"msg":"Timeout waiting for response"}'

        @staticmethod
        def json():
            return {"code": -1007, "msg": "Timeout waiting for response"}

    class FakeClient:
        async def request(self, *_args, **_kwargs):
            return FakeResponse()

        async def aclose(self):
            return None

    async def run():
        broker = BinanceSpotBroker(live_settings())
        await broker._client.aclose()
        broker._client = FakeClient()
        broker._last_clock_sync = time.monotonic()

        with pytest.raises(BinanceAPIError) as error:
            await broker._signed_request(
                "POST",
                "/api/v3/order",
                {"symbol": "BTCUSDT"},
            )
        await broker.close()
        return error.value

    error = asyncio.run(run())
    assert error.unknown_execution is True


def test_quote_balance_uses_only_free_balance() -> None:
    async def run():
        broker = BinanceSpotBroker(live_settings())

        async def fake_signed_request(*_args, **_kwargs):
            return {
                "balances": [
                    {"asset": "USDT", "free": "100", "locked": "900"},
                ]
            }

        broker._signed_request = fake_signed_request
        try:
            return await broker.quote_balance("USDT")
        finally:
            await broker.close()

    assert asyncio.run(run()) == 100.0


def test_completed_oco_without_fill_raises_protection_error() -> None:
    async def run():
        broker = BinanceSpotBroker(live_settings())

        async def fake_signed_request(_method, path, params):
            if path == "/api/v3/orderList":
                return {
                    "listOrderStatus": "ALL_DONE",
                    "orders": [{"orderId": 1}],
                }
            assert params["orderId"] == 1
            return {
                "status": "CANCELED",
                "executedQty": "0",
                "cummulativeQuoteQty": "0",
            }

        broker._signed_request = fake_signed_request
        try:
            with pytest.raises(ProtectionStateError):
                await broker.get_protection_fill(
                    symbol="BTCUSDT",
                    order_list_id="123",
                )
        finally:
            await broker.close()

    asyncio.run(run())
