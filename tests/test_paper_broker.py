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
