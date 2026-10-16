from __future__ import annotations

from fx_channel.persistence import SQLitePlayerStateStore


def test_sqlite_store_survives_reopen(tmp_path) -> None:
    path = tmp_path / "fx_channel.db"

    first = SQLitePlayerStateStore(path)
    first.save(
        "gacha",
        "player-1",
        {
            "currencies": {"premium_gem": 1200},
            "characters": {"rookie_aki": 1},
        },
    )

    second = SQLitePlayerStateStore(path)
    loaded = second.load("gacha", "player-1")

    assert loaded is not None
    assert loaded["currencies"]["premium_gem"] == 1200
    assert loaded["characters"]["rookie_aki"] == 1


def test_sqlite_backup(tmp_path) -> None:
    source_path = tmp_path / "source.db"
    backup_path = tmp_path / "backup.db"

    store = SQLitePlayerStateStore(source_path)
    store.save("test", "p1", {"value": 42})
    store.backup_to(backup_path)

    backup = SQLitePlayerStateStore(backup_path)
    assert backup.load("test", "p1") == {"value": 42}
