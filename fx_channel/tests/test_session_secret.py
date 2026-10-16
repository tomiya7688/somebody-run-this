from __future__ import annotations

from fx_channel.auth import UserSessionManager, load_or_create_session_secret


def test_session_secret_survives_restart(tmp_path) -> None:
    path = tmp_path / "data" / "user_session_secret.bin"

    first_secret = load_or_create_session_secret(path)
    first = UserSessionManager(first_secret)
    session = first.issue()

    second_secret = load_or_create_session_secret(path)
    second = UserSessionManager(second_secret)

    assert first_secret == second_secret
    assert second.verify(session["token"]) == session["player_id"]
