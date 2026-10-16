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
        "economy": {
            "starting_currencies": {},
            "starting_characters": ["rookie_aki"],
        },
    }


def test_ranking_uses_server_portfolio_equity() -> None:
    runtime = FxChannelRuntime(config(), content_root="content")

    # Visiting home registers both players in persistent player state.
    runtime.user_home("p1")
    runtime.user_home("p2")

    runtime.user_action(
        "p2",
        "place_order",
        {
            "symbol": "USDJPY",
            "side": "buy",
            "margin": 100_000,
            "leverage": 1,
        },
    )

    ranking = runtime.user_ranking()

    assert [row["rank"] for row in ranking] == [1, 2]
    assert {row["player_id"] for row in ranking} == {"p1", "p2"}
    assert all(row["equity"] == 1_000_000 for row in ranking)
