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


def test_health() -> None:
    response = make_client().get("/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_user_api_does_not_require_operator_token() -> None:
    response = make_client().get("/api/user/quotes")
    assert response.status_code == 200
    assert response.json()["quotes"][0]["symbol"] == "USDJPY"


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


def test_user_action_and_operator_action_are_separate() -> None:
    user = make_client().post(
        "/api/user/action",
        json={
            "player_id": "p1",
            "action": "ping",
            "payload": {"value": 1},
        },
    )
    assert user.status_code == 200

    operator_without_token = make_client().post(
        "/api/operator/action",
        json={"action": "ping", "payload": {}},
    )
    assert operator_without_token.status_code == 401
