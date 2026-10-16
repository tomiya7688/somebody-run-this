from __future__ import annotations

from fx_channel.persistence import MemoryPlayerStateStore
from fx_channel.season import SeasonManager


class FakeClock:
    def __init__(self, value: float = 1000.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


def test_season_rolls_over_after_duration() -> None:
    store = MemoryPlayerStateStore()
    clock = FakeClock()

    manager = SeasonManager(
        config={
            "enabled": True,
            "duration_days": 1,
            "reset_balance": True,
        },
        state_store=store,
        clock=clock,
    )

    first = manager.snapshot()
    assert first.id == "season-000001"

    clock.value += 86400
    second, changed = manager.ensure_current()

    assert changed is True
    assert second.id == "season-000002"
    assert second.start_at == 87400.0


def test_season_catches_up_after_long_downtime() -> None:
    store = MemoryPlayerStateStore()
    clock = FakeClock()

    manager = SeasonManager(
        config={
            "enabled": True,
            "duration_days": 1,
        },
        state_store=store,
        clock=clock,
    )

    clock.value += 86400 * 5 + 1
    current, changed = manager.ensure_current()

    assert changed is True
    assert current.index == 6


def test_participants_are_scoped_per_season() -> None:
    store = MemoryPlayerStateStore()
    clock = FakeClock()

    manager = SeasonManager(
        config={
            "enabled": True,
            "duration_days": 1,
        },
        state_store=store,
        clock=clock,
    )

    manager.mark_participant("p1")
    assert manager.player_ids() == ["p1"]

    clock.value += 86400
    manager.ensure_current()

    assert manager.player_ids() == []
    manager.mark_participant("p2")
    assert manager.player_ids() == ["p2"]


def test_disabled_season_is_permanent() -> None:
    manager = SeasonManager(
        config={"enabled": False},
        state_store=MemoryPlayerStateStore(),
    )

    current, changed = manager.ensure_current(now=10**12)

    assert changed is False
    assert current.id == "permanent"
    assert current.end_at is None
