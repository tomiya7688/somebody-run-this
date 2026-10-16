from __future__ import annotations

import random

import pytest

from fx_channel.content import load_content_registry
from fx_channel.gacha import GachaEngine, GachaError


def engine() -> GachaEngine:
    content = load_content_registry("content")
    return GachaEngine(
        content=content,
        starting_currencies={"premium_gem": 3000},
        starting_characters=["rookie_aki"],
        rng=random.Random(1),
    )


def test_starting_character_and_wallet() -> None:
    snapshot = engine().snapshot("p1")
    assert snapshot["currencies"]["premium_gem"] == 3000
    assert snapshot["characters"][0]["id"] == "rookie_aki"


def test_draw_is_server_authoritative_and_charges_currency() -> None:
    gacha = engine()
    result = gacha.draw(
        player_id="p1",
        gacha_id="standard_character",
        count=1,
    )
    assert len(result["results"]) == 1
    assert result["remaining"] == 2700


def test_insufficient_currency_is_rejected() -> None:
    content = load_content_registry("content")
    gacha = GachaEngine(
        content=content,
        starting_currencies={"premium_gem": 0},
        rng=random.Random(1),
    )

    with pytest.raises(GachaError):
        gacha.draw(
            player_id="p1",
            gacha_id="standard_character",
        )


def test_public_rates_sum_to_one() -> None:
    pools = engine().public_pools()
    probabilities = [
        entry["probability"]
        for entry in pools[0]["entries"]
    ]
    assert sum(probabilities) == pytest.approx(1.0)


def test_operator_can_grant_currency() -> None:
    gacha = engine()
    balance = gacha.grant_currency(
        player_id="p1",
        currency="premium_gem",
        amount=500,
    )
    assert balance == 3500
