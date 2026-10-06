from dataclasses import dataclass


@dataclass(frozen=True)
class RiskLimits:
    risk_per_trade: float = 0.01
    max_daily_loss: float = 0.03
    max_drawdown: float = 0.10
    max_open_positions: int = 3
    max_consecutive_losses: int = 3
    max_position_quote_fraction: float = 0.25
    stop_loss_pct: float = 0.01
    take_profit_r_multiple: float = 2.0


@dataclass(frozen=True)
class RiskSnapshot:
    equity: float
    day_start_equity: float
    peak_equity: float
    open_positions: int
    consecutive_losses: int


@dataclass(frozen=True)
class RiskDecision:
    allowed: bool
    reasons: list[str]


class RiskManager:
    def __init__(self, limits: RiskLimits):
        self.limits = limits

    def can_open(self, snapshot: RiskSnapshot) -> RiskDecision:
        reasons: list[str] = []

        if snapshot.equity <= 0:
            reasons.append("Equity is not positive")

        if snapshot.open_positions >= self.limits.max_open_positions:
            reasons.append("Maximum open positions reached")

        if snapshot.consecutive_losses >= self.limits.max_consecutive_losses:
            reasons.append("Maximum consecutive losses reached")

        if snapshot.day_start_equity > 0:
            daily_loss = max(
                0.0,
                (snapshot.day_start_equity - snapshot.equity) / snapshot.day_start_equity,
            )
            if daily_loss >= self.limits.max_daily_loss:
                reasons.append("Daily loss limit reached")

        if snapshot.peak_equity > 0:
            drawdown = max(
                0.0,
                (snapshot.peak_equity - snapshot.equity) / snapshot.peak_equity,
            )
            if drawdown >= self.limits.max_drawdown:
                reasons.append("Maximum drawdown limit reached")

        return RiskDecision(allowed=not reasons, reasons=reasons)

    def build_levels(
        self,
        entry_price: float,
        atr_value: float | None = None,
    ) -> tuple[float, float]:
        if entry_price <= 0:
            raise ValueError("entry_price must be positive")

        configured_distance = entry_price * self.limits.stop_loss_pct
        atr_distance = (atr_value or 0.0) * 1.5
        stop_distance = max(configured_distance, atr_distance)

        stop_loss = entry_price - stop_distance
        take_profit = entry_price + stop_distance * self.limits.take_profit_r_multiple

        if stop_loss <= 0:
            raise ValueError("Calculated stop loss is not positive")

        return stop_loss, take_profit

    def calculate_position_size(
        self,
        *,
        equity: float,
        entry_price: float,
        stop_loss: float,
    ) -> float:
        if equity <= 0 or entry_price <= 0 or stop_loss <= 0:
            return 0.0

        stop_distance = entry_price - stop_loss
        if stop_distance <= 0:
            return 0.0

        risk_budget = equity * self.limits.risk_per_trade
        quantity_by_risk = risk_budget / stop_distance

        max_quote = equity * self.limits.max_position_quote_fraction
        quantity_by_cap = max_quote / entry_price

        return max(0.0, min(quantity_by_risk, quantity_by_cap))
