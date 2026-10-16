from __future__ import annotations

from fx_channel.runtime import FxChannelRuntime


def config() -> dict:
    return {
        "market": {
            "mode": "simulated",
            "simulated": {
                "seed": 1,
                "base_volatility": 0.001,
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


def test_starter_character_can_use_owned_skill() -> None:
    runtime = FxChannelRuntime(config(), content_root="content")

    runtime.user_quotes()
    runtime.user_quotes()
    runtime.user_quotes()

    result = runtime.user_action(
        "p1",
        "use_skill",
        {
            "skill_id": "volatility_alert",
            "symbol": "USDJPY",
        },
    )

    assert result["ok"] is True
    assert result["data"]["title"] == "ボラティリティアラート"


def test_unowned_skill_is_rejected() -> None:
    runtime = FxChannelRuntime(config(), content_root="content")

    result = runtime.user_action(
        "p1",
        "use_skill",
        {
            "skill_id": "trend_reader",
            "symbol": "USDJPY",
        },
    )

    assert result["ok"] is False
    assert "do not own" in result["message"]
