from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import RuntimeState, Trade
from app.risk.manager import RiskSnapshot


class PortfolioStateService:
    def __init__(self, db: Session):
        self.db = db

    def _get_state(self, key: str) -> str | None:
        row = self.db.get(RuntimeState, key)
        return row.value if row else None

    def _set_state(self, key: str, value: str) -> None:
        row = self.db.get(RuntimeState, key)
        if row:
            row.value = value
        else:
            self.db.add(RuntimeState(key=key, value=value))
        self.db.flush()

    def realized_pnl(self, mode: str) -> float:
        rows = self.db.execute(
            select(Trade.pnl_quote).where(
                Trade.mode == mode,
                Trade.status == "CLOSED",
            )
        ).scalars()
        return sum(float(value or 0) for value in rows)

    def today_realized_pnl(self, mode: str) -> float:
        today = datetime.now(UTC).date()
        rows = self.db.execute(
            select(Trade).where(
                Trade.mode == mode,
                Trade.status == "CLOSED",
            )
        ).scalars()
        return sum(
            float(trade.pnl_quote or Decimal("0"))
            for trade in rows
            if trade.exit_time and trade.exit_time.date() == today
        )

    def open_trades(self, mode: str) -> list[Trade]:
        return list(
            self.db.execute(
                select(Trade).where(
                    Trade.mode == mode,
                    Trade.status == "OPEN",
                )
            ).scalars()
        )

    def consecutive_losses(self, mode: str) -> int:
        trades = list(
            self.db.execute(
                select(Trade)
                .where(Trade.mode == mode, Trade.status == "CLOSED")
                .order_by(Trade.exit_time.desc())
                .limit(50)
            ).scalars()
        )
        today = datetime.now(UTC).date()
        count = 0
        for trade in trades:
            if trade.exit_time is None or trade.exit_time.date() != today:
                break
            if float(trade.pnl_quote or 0) < 0:
                count += 1
            else:
                break
        return count

    def risk_snapshot(self, *, mode: str, equity: float) -> RiskSnapshot:
        today_key = f"day_start_equity:{mode}:{datetime.now(UTC).date().isoformat()}"
        peak_key = f"peak_equity:{mode}"

        day_start_raw = self._get_state(today_key)
        if day_start_raw is None:
            self._set_state(today_key, str(equity))
            day_start_equity = equity
        else:
            day_start_equity = float(day_start_raw)

        peak_raw = self._get_state(peak_key)
        peak_equity = max(float(peak_raw) if peak_raw else equity, equity)
        self._set_state(peak_key, str(peak_equity))

        return RiskSnapshot(
            equity=equity,
            day_start_equity=day_start_equity,
            peak_equity=peak_equity,
            open_positions=len(self.open_trades(mode)),
            consecutive_losses=self.consecutive_losses(mode),
        )
