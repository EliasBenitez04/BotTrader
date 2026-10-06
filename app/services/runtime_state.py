import json
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.db.models import RuntimeState

LIVE_HALT_KEY = "live_trading_halt"


class RuntimeStateService:
    def __init__(self, db: Session):
        self.db = db

    def get(self, key: str) -> str | None:
        row = self.db.get(RuntimeState, key)
        return row.value if row else None

    def set(self, key: str, value: str) -> None:
        row = self.db.get(RuntimeState, key)
        if row:
            row.value = value
        else:
            self.db.add(RuntimeState(key=key, value=value))
        self.db.flush()

    def delete(self, key: str) -> None:
        row = self.db.get(RuntimeState, key)
        if row:
            self.db.delete(row)
            self.db.flush()

    def live_halt(self) -> dict | None:
        raw = self.get(LIVE_HALT_KEY)
        if raw is None:
            return None
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"reason": raw}
        return payload if isinstance(payload, dict) else {"reason": str(payload)}

    def halt_live(
        self,
        *,
        reason: str,
        symbol: str | None = None,
        context: dict | None = None,
    ) -> dict:
        payload = {
            "reason": reason,
            "symbol": symbol,
            "context": context or {},
            "created_at": datetime.now(UTC).isoformat(),
        }
        self.set(LIVE_HALT_KEY, json.dumps(payload, ensure_ascii=False))
        return payload

    def clear_live_halt(self) -> None:
        self.delete(LIVE_HALT_KEY)
