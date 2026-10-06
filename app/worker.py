import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import text

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.models import RuntimeState
from app.db.session import SessionLocal, engine
from app.services.trading_engine import TradingEngine

WORKER_LOCK_ID = 84201953
logger = logging.getLogger(__name__)


def _heartbeat(db) -> None:
    row = db.get(RuntimeState, "worker_heartbeat")
    value = datetime.now(timezone.utc).isoformat()
    if row:
        row.value = value
    else:
        db.add(RuntimeState(key="worker_heartbeat", value=value))
    db.commit()


async def run_forever() -> None:
    settings = get_settings()
    if settings.trading_mode == "LIVE" and not settings.live_is_armed:
        raise RuntimeError(
            "TRADING_MODE=LIVE but LIVE safety gates are not fully armed. Worker refused to start."
        )

    lock_connection = engine.connect()
    acquired = bool(
        lock_connection.execute(
            text("SELECT pg_try_advisory_lock(:lock_id)"),
            {"lock_id": WORKER_LOCK_ID},
        ).scalar()
    )
    if not acquired:
        lock_connection.close()
        raise RuntimeError("Another BotTrader worker already owns the PostgreSQL advisory lock")

    logger.info(
        "Worker started | mode=%s | symbols=%s | interval=%ss",
        settings.trading_mode,
        ",".join(settings.symbols),
        settings.worker_interval_seconds,
    )

    try:
        while True:
            db = SessionLocal()
            try:
                async with TradingEngine(db, settings) as trading:
                    for symbol in settings.symbols:
                        try:
                            result = await trading.process_symbol(symbol)
                            logger.info("%s -> %s", symbol, result)
                        except Exception:
                            db.rollback()
                            logger.exception("Trading tick failed for %s", symbol)
                _heartbeat(db)
            finally:
                db.close()

            await asyncio.sleep(settings.worker_interval_seconds)
    finally:
        try:
            lock_connection.execute(
                text("SELECT pg_advisory_unlock(:lock_id)"),
                {"lock_id": WORKER_LOCK_ID},
            )
        finally:
            lock_connection.close()


if __name__ == "__main__":
    configure_logging()
    asyncio.run(run_forever())
