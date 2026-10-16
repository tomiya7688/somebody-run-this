from __future__ import annotations

import zipfile

from fx_channel.auth import load_or_create_session_secret
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
            "starting_currencies": {},
            "starting_characters": ["rookie_aki"],
        },
    }


def test_backup_contains_database_and_session_secret(tmp_path) -> None:
    load_or_create_session_secret(
        tmp_path / "data" / "user_session_secret.bin"
    )
    runtime = FxChannelRuntime(
        config(),
        content_root="content",
        data_root=tmp_path,
    )
    runtime.user_home("p1")

    result = runtime.operator_action(
        "backup_server_state",
        {},
    )

    assert result["ok"] is True
    archive = result["data"]["backup"]

    with zipfile.ZipFile(archive) as backup:
        assert set(backup.namelist()) == {
            "fx_channel.db",
            "user_session_secret.bin",
        }
