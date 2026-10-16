from __future__ import annotations

from typing import Any, Mapping, Protocol, Sequence

from .user_frontend_api import (
    ActionResult,
    CharacterView,
    HomeView,
    MarketQuoteView,
    PlayerSummaryView,
)


class UserBackendPort(Protocol):
    """Network/service boundary used by the user application."""

    def get_home(self, player_id: str) -> Mapping[str, Any]:
        ...

    def get_quotes(self) -> Sequence[Mapping[str, Any]]:
        ...

    def post_action(
        self,
        player_id: str,
        action: str,
        payload: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        ...


class UserApplication:
    """
    User-client application layer.

    It does not load operator.yaml, PriceProvider, content YAML, DB adapters,
    or operator functions. It only talks to the user backend port.
    """

    def __init__(self, backend: UserBackendPort) -> None:
        self._backend = backend

    def refresh_quotes(self) -> Sequence[MarketQuoteView]:
        return tuple(
            MarketQuoteView(symbol=str(item["symbol"]), price=float(item["price"]))
            for item in self._backend.get_quotes()
        )

    def get_home_view(self, player_id: str) -> HomeView:
        raw = self._backend.get_home(player_id)
        player = raw["player"]

        return HomeView(
            player=PlayerSummaryView(
                player_id=str(player["player_id"]),
                display_name=str(player["display_name"]),
                balance=float(player["balance"]),
                equity=float(player["equity"]),
            ),
            quotes=tuple(
                MarketQuoteView(
                    symbol=str(item["symbol"]),
                    price=float(item["price"]),
                )
                for item in raw.get("quotes", [])
            ),
            characters=tuple(
                CharacterView(
                    id=str(item["id"]),
                    name=str(item["name"]),
                    rarity=str(item["rarity"]),
                    skill_ids=tuple(str(x) for x in item.get("skill_ids", [])),
                )
                for item in raw.get("characters", [])
            ),
        )

    def execute_action(
        self,
        player_id: str,
        action: str,
        payload: Mapping[str, Any],
    ) -> ActionResult:
        raw = self._backend.post_action(player_id, action, payload)
        return ActionResult(
            ok=bool(raw["ok"]),
            message=str(raw["message"]),
            data=dict(raw.get("data", {})),
        )
