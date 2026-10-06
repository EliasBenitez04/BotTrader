import asyncio

from app.brokers.paper import PaperBroker


def test_paper_buy_applies_slippage_and_fee() -> None:
    async def run():
        broker = PaperBroker(fee_bps=10, slippage_bps=5)
        return await broker.execute_market(
            symbol="BTCUSDT",
            side="BUY",
            quantity=1,
            reference_price=100,
            client_order_id="test",
        )

    result = asyncio.run(run())
    assert result.fill_price > 100
    assert result.fee_quote > 0


def test_oco_quantity_uses_regular_lot_size() -> None:
    from app.brokers.binance_spot import BinanceSpotBroker
    from app.core.config import Settings

    async def run():
        broker = BinanceSpotBroker(Settings())

        async def fake_symbol_info(_: str):
            return {
                "status": "TRADING",
                "baseAsset": "BTC",
                "quoteAsset": "USDT",
                "filters": [
                    {
                        "filterType": "LOT_SIZE",
                        "minQty": "0.1",
                        "maxQty": "1000",
                        "stepSize": "0.1",
                    },
                    {
                        "filterType": "MARKET_LOT_SIZE",
                        "minQty": "1",
                        "maxQty": "1000",
                        "stepSize": "1",
                    },
                ],
            }

        broker._symbol_info = fake_symbol_info
        try:
            market_qty, _ = await broker.normalize_quantity(
                symbol="BTCUSDT",
                quantity=1.27,
                reference_price=100,
            )
            oco_qty, _ = await broker.normalize_quantity(
                symbol="BTCUSDT",
                quantity=1.27,
                reference_price=100,
                market_order=False,
            )
            return market_qty, oco_qty
        finally:
            await broker.close()

    market_qty, oco_qty = asyncio.run(run())
    assert market_qty == 1.0
    assert oco_qty == 1.2
