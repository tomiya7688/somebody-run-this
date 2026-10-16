from __future__ import annotations

from typing import Any, Mapping

from fastapi.testclient import TestClient

from fx_channel.server_main import create_app


class FakeRuntime:
    def user_quotes(self) -> list[dict[str, Any]]:
        return [{"symbol": "USDJPY", "price": 150.25}]

    def user_home(self, player_id: str) -> dict[str, Any]:
        return {
            "player": {
                "player_id": player_id,
                "display_name": player_id,
                "balance": 1_000_000,
                "equity": 1_000_000,
            },
            "quotes": self.user_quotes(),
            "positions": [],
            "portfolio": {
                "available_balance": 1_000_000,
                "locked_margin": 0,
                "unrealized_pnl": 0,
                "equity": 1_000_000,
                "positions": [],
            },
            "characters": [],
        }

    def user_action(
        self,
        player_id: str,
        action: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        return {
            "ok": True,
            "message": action,
            "data": {"player_id": player_id, **dict(payload)},
        }

    def operator_status(self) -> dict[str, Any]:
        return {
            "market_mode": "simulated",
            "symbols": ["USDJPY"],
            "characters": 0,
            "skills": 0,
            "gacha_pools": 0,
        }

    def operator_action(
        self,
        action: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        return {
            "ok": True,
            "message": action,
            "data": dict(payload),
        }


def make_client() -> TestClient:
    app = create_app(
        FakeRuntime(),  # type: ignore[arg-type]
        operator_token="operator-secret",
    )
    return TestClient(app)


def new_user(client: TestClient) -> dict[str, str]:
    response = client.post("/api/user/session")
    assert response.status_code == 200
    return response.json()


def test_health() -> None:
    response = make_client().get("/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_quotes_are_public() -> None:
    response = make_client().get("/api/user/quotes")
    assert response.status_code == 200
    assert response.json()["quotes"][0]["symbol"] == "USDJPY"


def test_user_home_requires_session() -> None:
    response = make_client().get("/api/user/home")
    assert response.status_code == 401


def test_user_session_authorizes_home_and_action() -> None:
    client = make_client()
    session = new_user(client)
    headers = {"Authorization": f"Bearer {session['token']}"}

    home = client.get("/api/user/home", headers=headers)
    assert home.status_code == 200
    assert home.json()["player"]["player_id"] == session["player_id"]

    action = client.post(
        "/api/user/action",
        headers=headers,
        json={
            "action": "ping",
            "payload": {"value": 1},
        },
    )
    assert action.status_code == 200
    assert action.json()["data"]["player_id"] == session["player_id"]


def test_tampered_user_token_is_rejected() -> None:
    client = make_client()
    session = new_user(client)
    token = session["token"]
    replacement = "0" if token[-1] != "0" else "1"

    response = client.get(
        "/api/user/home",
        headers={"Authorization": f"Bearer {token[:-1] + replacement}"},
    )
    assert response.status_code == 401


def test_operator_api_rejects_missing_token() -> None:
    response = make_client().get("/api/operator/status")
    assert response.status_code == 401


def test_operator_api_accepts_valid_token() -> None:
    response = make_client().get(
        "/api/operator/status",
        headers={"Authorization": "Bearer operator-secret"},
    )
    assert response.status_code == 200
    assert response.json()["market_mode"] == "simulated"


def test_user_token_cannot_access_operator_api() -> None:
    client = make_client()
    session = new_user(client)
    response = client.get(
        "/api/operator/status",
        headers={"Authorization": f"Bearer {session['token']}"},
    )
    assert response.status_code == 401
