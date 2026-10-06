class BotTraderError(Exception):
    """Base exception for expected application failures."""


class MarketDataError(BotTraderError):
    """Raised when market data cannot be retrieved or validated."""


class BinanceAPIError(BotTraderError):
    """Raised when Binance returns an API or transport error."""


class RiskRejectedError(BotTraderError):
    """Raised when the risk engine rejects a new trade."""


class LiveTradingNotArmedError(BotTraderError):
    """Raised when a real order is requested without all safety gates enabled."""
