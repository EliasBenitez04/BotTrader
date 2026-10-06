from app.core.config import Settings


def test_live_is_not_armed_without_explicit_confirmation() -> None:
    settings = Settings(
        trading_mode="LIVE",
        live_trading_enabled=True,
        live_confirmation="",
        binance_api_key="key",
        binance_api_secret="secret",
    )
    assert settings.live_is_armed is False


def test_live_requires_all_gates() -> None:
    settings = Settings(
        trading_mode="LIVE",
        live_trading_enabled=True,
        live_confirmation="ENABLE_LIVE_SPOT",
        binance_api_key="key",
        binance_api_secret="secret",
    )
    assert settings.live_is_armed is True
