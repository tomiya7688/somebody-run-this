from __future__ import annotations

from fx_channel.persistence import SQLitePlayerStateStore
from fx_channel.season import SeasonManager


class FakeClock:
    def __init__(self, value: float) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


def test_season_state_survives_restart(tmp_path) -> None:
    store = SQLitePlayerStateStore(tmp_path / "fx_channel.db")
    clock = FakeClock(1000)

    first = SeasonManager(
        config={
            "enabled": True,
            "duration_days": 7,
        },
        state_store=store,
        clock=clock,
    )
    first.advance_now(now=2000)

    second = SeasonManager(
        config={
            "enabled": True,
            "duration_days": 7,
        },
        state_store=SQLitePlayerStateStore(tmp_path / "fx_channel.db"),
        clock=FakeClock(3000),
    )

    assert second.snapshot().id == "season-000002"
    assert second.snapshot().start_at == 2000
