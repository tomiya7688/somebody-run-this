from __future__ import annotations

from fx_channel.runtime import FxChannelRuntime


def config() -> dict:
    return {
        "storage": {
            "type": "sqlite",
            "sqlite": {"path": "data/fx_channel.db"},
        },
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
            "starting_currencies": {"premium_gem": 0},
            "starting_characters": ["rookie_aki"],
        },
    }


def test_player_state_survives_runtime_restart(tmp_path) -> None:
    first = FxChannelRuntime(
        config(),
        content_root="content",
        data_root=tmp_path,
    )

    granted = first.operator_action(
        "grant_currency",
        {
            "player_id": "player-1",
            "currency": "premium_gem",
            "amount": 3000,
        },
    )
    assert granted["ok"] is True

    opened = first.user_action(
        "player-1",
        "place_order",
        {
            "symbol": "USDJPY",
            "side": "buy",
            "margin": 100_000,
            "leverage": 5,
        },
    )
    assert opened["ok"] is True

    drawn = first.user_action(
        "player-1",
        "draw_gacha",
        {
            "gacha_id": "standard_character",
            "count": 1,
        },
    )
    assert drawn["ok"] is True

    second = FxChannelRuntime(
        config(),
        content_root="content",
        data_root=tmp_path,
    )
    home = second.user_home("player-1")

    assert home["portfolio"]["available_balance"] == 900_000
    assert len(home["positions"]) == 1
    assert home["wallet"]["premium_gem"] == 2700

    owned = {
        character["id"]: character["copies"]
        for character in home["characters"]
    }
    assert owned["rookie_aki"] >= 1
