from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class ExecutionResult:
    symbol: str
    side: str
    quantity: float
    fill_price: float
    quote_quantity: float
    fee_quote: float
    order_id: str | None = None
    client_order_id: str | None = None


class Broker(ABC):
    @abstractmethod
    async def execute_market(
        self,
        *,
        symbol: str,
        side: str,
        quantity: float,
        reference_price: float,
        client_order_id: str,
    ) -> ExecutionResult:
        raise NotImplementedError

    async def quote_balance(self, quote_asset: str) -> float:
        raise NotImplementedError

    async def place_oco_protection(
        self,
        *,
        symbol: str,
        quantity: float,
        take_profit: float,
        stop_loss: float,
        client_order_id: str,
    ) -> str | None:
        return None

    async def get_protection_fill(
        self,
        *,
        symbol: str,
        order_list_id: str,
    ) -> ExecutionResult | None:
        return None

    async def cancel_protection(self, *, symbol: str, order_list_id: str) -> None:
        return None

    async def close(self) -> None:
        return None
