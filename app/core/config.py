from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "BotTrader"
    app_env: str = "development"
    log_level: str = "INFO"

    database_url: str = "postgresql+psycopg2://bottrader:change_me@127.0.0.1:5432/bottrader"

    trading_mode: Literal["PAPER", "LIVE"] = "PAPER"
    live_trading_enabled: bool = False
    live_confirmation: str = ""
    bot_admin_token: str = "change-this-token"

    binance_base_url: str = "https://api.binance.com"
    binance_testnet_base_url: str = "https://testnet.binance.vision"
    binance_use_testnet: bool = True
    binance_api_key: str = ""
    binance_api_secret: str = ""
    binance_recv_window_ms: int = Field(default=5000, ge=1000, le=60000)
    binance_http_timeout_seconds: float = Field(default=15.0, gt=0)

    symbols_csv: str = "BTCUSDT,ETHUSDT,SOLUSDT"
    default_timeframe: str = "5m"
    worker_interval_seconds: int = Field(default=60, ge=10)
    market_lookback_candles: int = Field(default=500, ge=250, le=1000)

    buy_score_threshold: int = Field(default=75, ge=0, le=100)
    sell_score_threshold: int = Field(default=35, ge=0, le=100)
    rsi_period: int = Field(default=14, ge=2, le=100)
    atr_period: int = Field(default=14, ge=2, le=100)

    paper_initial_capital: float = Field(default=1000.0, gt=0)
    risk_per_trade: float = Field(default=0.01, gt=0, le=0.05)
    max_daily_loss: float = Field(default=0.03, gt=0, le=0.20)
    max_drawdown: float = Field(default=0.10, gt=0, le=0.50)
    max_open_positions: int = Field(default=3, ge=1, le=20)
    max_consecutive_losses: int = Field(default=3, ge=1, le=20)
    max_position_quote_fraction: float = Field(default=0.25, gt=0, le=1)
    stop_loss_pct: float = Field(default=0.01, gt=0, le=0.20)
    take_profit_r_multiple: float = Field(default=2.0, gt=0, le=10)
    trading_fee_bps: float = Field(default=10.0, ge=0, le=100)
    slippage_bps: float = Field(default=5.0, ge=0, le=100)

    min_backtest_trades: int = Field(default=100, ge=1)

    @property
    def symbols(self) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for raw in self.symbols_csv.split(","):
            symbol = raw.strip().upper()
            if symbol and symbol not in seen:
                seen.add(symbol)
                result.append(symbol)
        return result

    @property
    def trade_base_url(self) -> str:
        return self.binance_testnet_base_url if self.binance_use_testnet else self.binance_base_url

    @property
    def live_is_armed(self) -> bool:
        return (
            self.trading_mode == "LIVE"
            and self.live_trading_enabled
            and self.live_confirmation == "ENABLE_LIVE_SPOT"
            and bool(self.binance_api_key)
            and bool(self.binance_api_secret)
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
