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


class ApplicationPort(Protocol):
    """
    Stable boundary exposed to every GUI.

    GUI implementations must use this interface instead of importing domain,
    market, gacha, persistence, or provider implementations directly.
    """

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


class Frontend(Protocol):
    """Interface implemented by swappable GUI/frontends."""

    def run(
        self,
        app: ApplicationPort,
        options: Mapping[str, Any],
    ) -> None:
        ...
