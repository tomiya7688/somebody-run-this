from __future__ import annotations

import pytest

from fx_channel.trading import TradingEngine, TradingError


def engine() -> TradingEngine:
    return TradingEngine(
        symbols=["USDJPY"],
        starting_balance=1_000_000,
        max_leverage=25,
        allow_negative_balance=False,
    )


def test_buy_position_profit() -> None:
    trading = engine()
    position = trading.open_position(
        player_id="p1",
        symbol="USDJPY",
        side="buy",
        margin=100_000,
        leverage=10,
        price=100,
    )

    snapshot = trading.snapshot(
        player_id="p1",
        prices={"USDJPY": 101},
    )
    assert snapshot["available_balance"] == 900_000
    assert snapshot["locked_margin"] == 100_000
    assert snapshot["unrealized_pnl"] == pytest.approx(10_000)
    assert snapshot["equity"] == pytest.approx(1_010_000)

    result = trading.close_position(
        player_id="p1",
        position_id=position.id,
        current_price=101,
    )
    assert result["realized_pnl"] == 10_000
    assert result["cash"] == 1_010_000


def test_sell_position_profit_when_price_falls() -> None:
    trading = engine()
    position = trading.open_position(
        player_id="p1",
        symbol="USDJPY",
        side="sell",
        margin=50_000,
        leverage=5,
        price=100,
    )
    result = trading.close_position(
        player_id="p1",
        position_id=position.id,
        current_price=98,
    )
    assert result["realized_pnl"] == 5_000


def test_cannot_exceed_available_balance() -> None:
    trading = engine()
    with pytest.raises(TradingError):
        trading.open_position(
            player_id="p1",
            symbol="USDJPY",
            side="buy",
            margin=1_000_001,
            leverage=1,
            price=100,
        )


def test_cannot_exceed_max_leverage() -> None:
    trading = engine()
    with pytest.raises(TradingError):
        trading.open_position(
            player_id="p1",
            symbol="USDJPY",
            side="buy",
            margin=10_000,
            leverage=26,
            price=100,
        )


def test_negative_balance_protection_caps_loss_at_margin() -> None:
    trading = engine()
    position = trading.open_position(
        player_id="p1",
        symbol="USDJPY",
        side="buy",
        margin=100_000,
        leverage=25,
        price=100,
    )
    result = trading.close_position(
        player_id="p1",
        position_id=position.id,
        current_price=1,
    )
    assert result["realized_pnl"] == -100_000
    assert result["cash"] == 900_000
