from __future__ import annotations

import base64
import hashlib
import hmac
import secrets


class UserAuthError(ValueError):
    """Raised when a user session token is invalid."""


class UserSessionManager:
    """
    Stateless anonymous user sessions.

    Tokens are signed with a key derived from the server operator secret. The
    operator secret itself is never sent to clients.
    """

    def __init__(self, secret: bytes) -> None:
        if len(secret) < 32:
            raise ValueError("Session signing secret must be at least 32 bytes.")
        self._secret = secret

    @classmethod
    def from_operator_token(cls, operator_token: str) -> "UserSessionManager":
        secret = hashlib.sha256(
            ("fx_channel:user-session:" + operator_token).encode("utf-8")
        ).digest()
        return cls(secret)

    def issue(self) -> dict[str, str]:
        player_id = secrets.token_hex(16)
        token = self._encode(player_id)
        return {
            "player_id": player_id,
            "token": token,
        }

    def verify(self, token: str) -> str:
        parts = token.split(".")
        if len(parts) != 3 or parts[0] != "v1":
            raise UserAuthError("Invalid user token.")

        _, player_id, signature = parts
        if len(player_id) != 32:
            raise UserAuthError("Invalid user token.")

        try:
            int(player_id, 16)
        except ValueError as exc:
            raise UserAuthError("Invalid user token.") from exc

        payload = f"v1.{player_id}".encode("utf-8")
        expected = hmac.new(
            self._secret,
            payload,
            hashlib.sha256,
        ).digest()

        try:
            actual = base64.urlsafe_b64decode(
                signature + "=" * (-len(signature) % 4)
            )
        except Exception as exc:
            raise UserAuthError("Invalid user token.") from exc

        if not hmac.compare_digest(actual, expected):
            raise UserAuthError("Invalid user token.")

        return player_id

    def _encode(self, player_id: str) -> str:
        payload = f"v1.{player_id}".encode("utf-8")
        signature = hmac.new(
            self._secret,
            payload,
            hashlib.sha256,
        ).digest()
        encoded = base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")
        return f"v1.{player_id}.{encoded}"
