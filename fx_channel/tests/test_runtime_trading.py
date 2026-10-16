from __future__ import annotations

from fx_channel.runtime import FxChannelRuntime


def config() -> dict:
    return {
        "market": {
            "mode": "simulated",
            "simulated": {
                "seed": 1,
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
    }


def test_runtime_place_and_close_position() -> None:
    runtime = FxChannelRuntime(config(), content_root="content")

    opened = runtime.user_action(
        "player-1",
        "place_order",
        {
            "symbol": "USDJPY",
            "side": "buy",
            "margin": 100_000,
            "leverage": 10,
        },
    )
    assert opened["ok"] is True
    position_id = opened["data"]["position_id"]

    home = runtime.user_home("player-1")
    assert len(home["positions"]) == 1
    assert home["portfolio"]["available_balance"] == 900_000

    closed = runtime.user_action(
        "player-1",
        "close_position",
        {"position_id": position_id},
    )
    assert closed["ok"] is True

    after = runtime.user_home("player-1")
    assert after["positions"] == []
    assert after["portfolio"]["available_balance"] == 1_000_000
