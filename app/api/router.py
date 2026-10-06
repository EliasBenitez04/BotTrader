from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.api.deps import require_admin_token
from app.core.config import get_settings
from app.db.models import BacktestRun
from app.db.session import get_db
from app.market.binance import SUPPORTED_INTERVALS
from app.schemas import BacktestRequest, HaltClearRequest, TickRequest
from app.services.backtest_service import BacktestService
from app.services.dashboard import DashboardService
from app.services.runtime_state import RuntimeStateService
from app.services.trading_engine import TradingEngine

router = APIRouter(prefix="/api/v1")
DbDep = Annotated[Session, Depends(get_db)]
AdminDep = Annotated[None, Depends(require_admin_token)]


@router.get("/health")
async def health(db: DbDep) -> dict:
    db.execute(text("SELECT 1"))
    settings = get_settings()
    halt = RuntimeStateService(db).live_halt()
    return {
        "status": "ok",
        "database": "ok",
        "trading_mode": settings.trading_mode,
        "live_armed": settings.live_is_armed,
        "live_halt": halt,
        "binance_testnet": settings.binance_use_testnet,
    }


@router.get("/market/analyze/{symbol}")
async def analyze_market(
    symbol: str,
    db: DbDep,
    timeframe: str = Query(default="5m"),
) -> dict:
    settings = get_settings()
    symbol = symbol.upper()
    if timeframe not in SUPPORTED_INTERVALS:
        raise HTTPException(status_code=422, detail="Unsupported timeframe")
    if symbol not in settings.symbols:
        raise HTTPException(status_code=422, detail=f"{symbol} is not configured")

    async with TradingEngine(db, settings) as engine:
        decision = await engine.analyze(symbol, timeframe)

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "signal": decision.signal,
        "score": decision.score,
        "price": decision.price,
        "candle_open_time": decision.candle_open_time,
        "candle_close_time": decision.candle_close_time,
        "indicators": {
            "ema20": decision.ema20,
            "ema50": decision.ema50,
            "ema200": decision.ema200,
            "rsi": decision.rsi,
            "macd": decision.macd,
            "macd_signal": decision.macd_signal,
            "atr": decision.atr,
            "atr_pct": decision.atr_pct,
            "volume_ratio": decision.volume_ratio,
        },
        "reasons": decision.reasons,
    }


@router.post("/backtests")
async def run_backtest(
    request: BacktestRequest,
    db: DbDep,
    _: AdminDep,
) -> dict:
    settings = get_settings()
    if request.symbol not in settings.symbols:
        raise HTTPException(status_code=422, detail=f"{request.symbol} is not configured")
    if request.end_time <= request.start_time:
        raise HTTPException(status_code=422, detail="end_time must be after start_time")

    service = BacktestService(db, settings)
    run_id, result = await service.run(request)
    payload = result.to_dict()
    return {
        "run_id": run_id,
        "symbol": payload["symbol"],
        "timeframe": payload["timeframe"],
        "start_time": payload["start_time"],
        "end_time": payload["end_time"],
        "metrics": payload["metrics"],
        "trade_count": len(payload["trades"]),
    }


@router.get("/backtests")
def list_backtests(
    db: DbDep,
    limit: int = Query(default=20, ge=1, le=100),
) -> list[dict]:
    rows = list(
        db.execute(
            select(BacktestRun).order_by(BacktestRun.created_at.desc()).limit(limit)
        ).scalars()
    )
    return [
        {
            "id": row.id,
            "symbol": row.symbol,
            "timeframe": row.timeframe,
            "start_time": row.start_time,
            "end_time": row.end_time,
            "total_trades": row.total_trades,
            "win_rate": float(row.win_rate),
            "profit_factor": (
                float(row.profit_factor) if row.profit_factor is not None else None
            ),
            "max_drawdown": float(row.max_drawdown),
            "return_pct": float(row.return_pct),
            "expectancy_pct": float(row.expectancy_pct),
            "sharpe_ratio": (
                float(row.sharpe_ratio) if row.sharpe_ratio is not None else None
            ),
            "statistically_sufficient": row.statistically_sufficient,
            "created_at": row.created_at,
        }
        for row in rows
    ]


@router.post("/trading/tick/{symbol}")
async def trading_tick(
    symbol: str,
    request: TickRequest,
    db: DbDep,
    _: AdminDep,
) -> dict:
    settings = get_settings()
    if settings.trading_mode == "LIVE" and not settings.live_is_armed:
        raise HTTPException(
            status_code=409,
            detail="LIVE mode is selected but safety gates are not armed",
        )

    async with TradingEngine(db, settings) as engine:
        return await engine.process_symbol(symbol.upper(), request.timeframe)


@router.get("/trading/status")
def trading_status(db: DbDep) -> dict:
    settings = get_settings()
    summary = DashboardService(db, settings).summary()
    return {
        "mode": summary["mode"],
        "live_armed": summary["live_armed"],
        "live_halt": summary["live_halt"],
        "binance_testnet": summary["binance_testnet"],
        "open_positions": len(summary["open_trades"]),
        "closed_trades": summary["closed_trades"],
        "realized_pnl": summary["realized_pnl"],
        "win_rate": summary["win_rate"],
    }


@router.get("/trading/halt")
def live_halt_status(db: DbDep) -> dict:
    return {
        "halt": RuntimeStateService(db).live_halt(),
    }


@router.post("/trading/halt/clear")
def clear_live_halt(
    request: HaltClearRequest,
    db: DbDep,
    _: AdminDep,
) -> dict:
    if not request.confirm_reconciled:
        raise HTTPException(
            status_code=409,
            detail=(
                "Confirm that Binance orders and balances were manually reconciled "
                "before clearing the halt"
            ),
        )

    runtime = RuntimeStateService(db)
    previous = runtime.live_halt()
    runtime.clear_live_halt()
    db.commit()
    return {
        "cleared": True,
        "previous_halt": previous,
        "note": request.note,
    }


@router.get("/dashboard/summary")
def dashboard_summary(db: DbDep) -> dict:
    return DashboardService(db, get_settings()).summary()
