from __future__ import annotations

from fx_channel.runtime import FxChannelRuntime


def config(*, reset_balance: bool = True) -> dict:
    return {
        "market": {
            "mode": "simulated",
            "simulated": {
                "seed": 1,
                "tick_seconds": 5,
                "base_volatility": 0.0,
                "drift": 0.0,
                "default_start_price": 100.0,
            },
        },
        "symbols": ["USDJPY"],
        "game": {
            "starting_balance": 1_000_000,
            "max_leverage": 25,
            "allow_negative_balance": False,
        },
        "economy": {
            "starting_currencies": {
                "premium_gem": 300,
            },
            "starting_characters": ["rookie_aki"],
        },
        "season": {
            "enabled": True,
            "duration_days": 7,
            "reset_balance": reset_balance,
            "keep_achievements": True,
        },
    }


def test_advancing_season_resets_trading_but_keeps_collection() -> None:
    runtime = FxChannelRuntime(
        config(reset_balance=True),
        content_root="content",
    )

    before = runtime.user_home("p1")
    first_season = before["season"]["id"]

    opened = runtime.user_action(
        "p1",
        "place_order",
        {
            "symbol": "USDJPY",
            "side": "buy",
            "margin": 100_000,
            "leverage": 5,
        },
    )
    assert opened["ok"] is True

    granted = runtime.operator_action(
        "grant_currency",
        {
            "player_id": "p1",
            "currency": "premium_gem",
            "amount": 500,
        },
    )
    assert granted["ok"] is True

    advanced = runtime.operator_action(
        "advance_season",
        {},
    )
    assert advanced["ok"] is True
    assert advanced["data"]["season"]["id"] != first_season

    after = runtime.user_home("p1")
    assert after["portfolio"]["available_balance"] == 1_000_000
    assert after["positions"] == []
    assert after["wallet"]["premium_gem"] == 800
    assert any(
        row["id"] == "rookie_aki"
        for row in after["characters"]
    )


def test_ranking_participants_reset_per_season() -> None:
    runtime = FxChannelRuntime(
        config(reset_balance=True),
        content_root="content",
    )

    runtime.user_home("p1")
    runtime.user_home("p2")
    assert {
        row["player_id"]
        for row in runtime.user_ranking()
    } == {"p1", "p2"}

    runtime.operator_action("advance_season", {})

    runtime.user_home("p1")
    assert [
        row["player_id"]
        for row in runtime.user_ranking()
    ] == ["p1"]


def test_reset_balance_false_carries_open_positions() -> None:
    runtime = FxChannelRuntime(
        config(reset_balance=False),
        content_root="content",
    )

    opened = runtime.user_action(
        "p1",
        "place_order",
        {
            "symbol": "USDJPY",
            "side": "buy",
            "margin": 100_000,
            "leverage": 5,
        },
    )
    assert opened["ok"] is True

    runtime.operator_action("advance_season", {})
    home = runtime.user_home("p1")

    assert home["portfolio"]["available_balance"] == 900_000
    assert len(home["positions"]) == 1
