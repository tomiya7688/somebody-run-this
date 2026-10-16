from __future__ import annotations

import pytest

from fx_channel.auth import UserAuthError, UserSessionManager


def manager() -> UserSessionManager:
    return UserSessionManager.from_operator_token("operator-secret-for-tests")


def test_issued_token_round_trips() -> None:
    auth = manager()
    session = auth.issue()
    assert auth.verify(session["token"]) == session["player_id"]


def test_tampered_token_is_rejected() -> None:
    auth = manager()
    session = auth.issue()
    token = session["token"]
    replacement = "0" if token[-1] != "0" else "1"

    with pytest.raises(UserAuthError):
        auth.verify(token[:-1] + replacement)
