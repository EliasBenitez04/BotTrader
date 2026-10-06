from app.brokers.base import Broker, ExecutionResult


class PaperBroker(Broker):
    def __init__(self, *, fee_bps: float, slippage_bps: float):
        self.fee_rate = fee_bps / 10_000
        self.slippage_rate = slippage_bps / 10_000

    async def execute_market(
        self,
        *,
        symbol: str,
        side: str,
        quantity: float,
        reference_price: float,
        client_order_id: str,
    ) -> ExecutionResult:
        if quantity <= 0 or reference_price <= 0:
            raise ValueError("quantity and reference_price must be positive")

        side = side.upper()
        if side not in {"BUY", "SELL"}:
            raise ValueError("side must be BUY or SELL")

        multiplier = 1 + self.slippage_rate if side == "BUY" else 1 - self.slippage_rate
        fill_price = reference_price * multiplier
        quote_quantity = quantity * fill_price
        fee_quote = quote_quantity * self.fee_rate

        return ExecutionResult(
            symbol=symbol.upper(),
            side=side,
            quantity=quantity,
            fill_price=fill_price,
            quote_quantity=quote_quantity,
            fee_quote=fee_quote,
            order_id=None,
            client_order_id=client_order_id,
        )
