from __future__ import annotations

from fx_channel.persistence import MemoryPlayerStateStore
from fx_channel.trading import TradingEngine


def test_season_namespaces_keep_previous_state() -> None:
    store = MemoryPlayerStateStore()

    first = TradingEngine(
        symbols=["USDJPY"],
        starting_balance=1_000_000,
        max_leverage=25,
        allow_negative_balance=False,
        state_store=store,
        state_namespace="trading:season-000001",
    )
    first.open_position(
        player_id="p1",
        symbol="USDJPY",
        side="buy",
        margin=100_000,
        leverage=1,
        price=100,
    )

    second = TradingEngine(
        symbols=["USDJPY"],
        starting_balance=1_000_000,
        max_leverage=25,
        allow_negative_balance=False,
        state_store=store,
        state_namespace="trading:season-000002",
    )

    second_snapshot = second.snapshot(
        player_id="p1",
        prices={"USDJPY": 100},
    )
    first_snapshot = first.snapshot(
        player_id="p1",
        prices={"USDJPY": 100},
    )

    assert second_snapshot["available_balance"] == 1_000_000
    assert second_snapshot["positions"] == []
    assert first_snapshot["available_balance"] == 900_000
    assert len(first_snapshot["positions"]) == 1
