from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence


@dataclass(frozen=True)
class MarketQuoteView:
    symbol: str
    price: float


@dataclass(frozen=True)
class PlayerSummaryView:
    player_id: str
    display_name: str
    balance: float
    equity: float


@dataclass(frozen=True)
class CharacterView:
    id: str
    name: str
    rarity: str
    skill_ids: tuple[str, ...]


@dataclass(frozen=True)
class HomeView:
    player: PlayerSummaryView
    quotes: tuple[MarketQuoteView, ...]
    characters: tuple[CharacterView, ...]


@dataclass(frozen=True)
class ActionResult:
    ok: bool
    message: str
    data: Mapping[str, Any]


class UserApplicationPort(Protocol):
    """The complete API visible to the user application GUI."""

    def get_home_view(self, player_id: str) -> HomeView:
        ...

    def refresh_quotes(self) -> Sequence[MarketQuoteView]:
        ...

    def execute_action(
        self,
        player_id: str,
        action: str,
        payload: Mapping[str, Any],
    ) -> ActionResult:
        ...


class UserFrontend(Protocol):
    def run(
        self,
        app: UserApplicationPort,
        options: Mapping[str, Any],
    ) -> None:
        ...
