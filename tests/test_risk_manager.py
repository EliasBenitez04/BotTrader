from app.risk.manager import RiskLimits, RiskManager, RiskSnapshot


def test_position_size_respects_risk_and_cap() -> None:
    manager = RiskManager(
        RiskLimits(risk_per_trade=0.01, max_position_quote_fraction=0.25)
    )
    quantity = manager.calculate_position_size(
        equity=1000,
        entry_price=100,
        stop_loss=99,
    )
    assert quantity == 2.5


def test_daily_loss_blocks_new_trade() -> None:
    manager = RiskManager(RiskLimits(max_daily_loss=0.03))
    decision = manager.can_open(
        RiskSnapshot(
            equity=960,
            day_start_equity=1000,
            peak_equity=1000,
            open_positions=0,
            consecutive_losses=0,
        )
    )
    assert decision.allowed is False
    assert "Daily loss limit reached" in decision.reasons


def test_drawdown_blocks_new_trade() -> None:
    manager = RiskManager(RiskLimits(max_drawdown=0.10))
    decision = manager.can_open(
        RiskSnapshot(
            equity=890,
            day_start_equity=890,
            peak_equity=1000,
            open_positions=0,
            consecutive_losses=0,
        )
    )
    assert decision.allowed is False
    assert "Maximum drawdown limit reached" in decision.reasons
