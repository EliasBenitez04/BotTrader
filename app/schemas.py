from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.market.binance import SUPPORTED_INTERVALS


class BacktestRequest(BaseModel):
    symbol: str = Field(min_length=5, max_length=20)
    timeframe: str = "5m"
    start_time: datetime
    end_time: datetime
    initial_capital: float = Field(default=1000.0, gt=0)
    max_candles: int = Field(default=100_000, ge=250, le=100_000)

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("timeframe")
    @classmethod
    def validate_timeframe(cls, value: str) -> str:
        if value not in SUPPORTED_INTERVALS:
            raise ValueError(f"Unsupported timeframe: {value}")
        return value


class TickRequest(BaseModel):
    timeframe: str | None = None

    @field_validator("timeframe")
    @classmethod
    def validate_timeframe(cls, value: str | None) -> str | None:
        if value is not None and value not in SUPPORTED_INTERVALS:
            raise ValueError(f"Unsupported timeframe: {value}")
        return value
