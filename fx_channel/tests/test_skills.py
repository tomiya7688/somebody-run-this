from __future__ import annotations

import pytest

from fx_channel.content import load_content_registry
from fx_channel.persistence import MemoryPlayerStateStore
from fx_channel.skill_api import MarketSnapshot, PricePoint
from fx_channel.skills import SkillEngine, SkillError


def market() -> MarketSnapshot:
    history = {
        "USDJPY": [
            PricePoint(timestamp=1, price=100.0),
            PricePoint(timestamp=2, price=100.5),
            PricePoint(timestamp=3, price=101.0),
            PricePoint(timestamp=4, price=100.7),
        ]
    }
    return MarketSnapshot.readonly(
        {"USDJPY": 100.7},
        history,
    )


def test_trend_reader_returns_read_only_analysis() -> None:
    engine = SkillEngine(
        content=load_content_registry("content"),
        state_store=MemoryPlayerStateStore(),
    )
    result = engine.execute(
        player_id="p1",
        skill_id="trend_reader",
        symbol="USDJPY",
        market=market(),
        now=1000,
    )

    assert result.data["symbol"] == "USDJPY"
    assert result.data["direction"] == "up"
    assert result.disclaimer is not None


def test_skill_cooldown_is_enforced() -> None:
    store = MemoryPlayerStateStore()
    engine = SkillEngine(
        content=load_content_registry("content"),
        state_store=store,
    )

    engine.execute(
        player_id="p1",
        skill_id="volatility_alert",
        symbol="USDJPY",
        market=market(),
        now=1000,
    )

    with pytest.raises(SkillError):
        engine.execute(
            player_id="p1",
            skill_id="volatility_alert",
            symbol="USDJPY",
            market=market(),
            now=1010,
        )


def test_skill_context_does_not_expose_price_provider() -> None:
    snapshot = market()
    assert not hasattr(snapshot, "set_price")
    assert not hasattr(snapshot, "price_provider")
