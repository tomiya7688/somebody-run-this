from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

from .content import ContentRegistry, load_content_registry
from .frontend_api import (
    ActionResult,
    CharacterView,
    HomeView,
    MarketQuoteView,
    PlayerSummaryView,
)
from .market import PriceProvider, build_price_provider


class FxChannelApplication:
    """
    GUI-neutral application facade.

    Frontends receive this object through the ApplicationPort contract.
    All business/application behavior belongs here or in lower layers,
    never in a frontend implementation.
    """

    def __init__(
        self,
        operator_config: dict[str, Any],
        *,
        content_root: str | Path = "content",
    ) -> None:
        self._config = operator_config
        self._symbols = list(operator_config["symbols"])
        self._price_provider: PriceProvider = build_price_provider(operator_config)
        self._content: ContentRegistry = load_content_registry(content_root)

        # Temporary in-memory defaults until persistence/player services are added.
        # Keeping this here (rather than in GUI) preserves the boundary.
        starting_balance = float(
            operator_config.get("game", {}).get("starting_balance", 1_000_000)
        )
        self._starting_balance = starting_balance

    def refresh_quotes(self) -> Sequence[MarketQuoteView]:
        prices = self._price_provider.get_prices(self._symbols)
        return tuple(
            MarketQuoteView(symbol=symbol, price=float(prices[symbol]))
            for symbol in self._symbols
        )

    def get_home_view(self, player_id: str) -> HomeView:
        quotes = tuple(self.refresh_quotes())

        # Player persistence/ownership will replace this bootstrap data later.
        player = PlayerSummaryView(
            player_id=player_id,
            display_name=player_id,
            balance=self._starting_balance,
            equity=self._starting_balance,
        )

        # For now expose registered character catalog entries as display DTOs.
        # Ownership state will be introduced in the player service.
        characters = tuple(
            CharacterView(
                id=character.id,
                name=character.name,
                rarity=character.rarity,
                skill_ids=character.skills,
            )
            for character in self._content.characters.values()
        )

        return HomeView(
            player=player,
            quotes=quotes,
            characters=characters,
        )

    def execute_action(
        self,
        player_id: str,
        action: str,
        payload: Mapping[str, Any],
    ) -> ActionResult:
        # Commands such as place_order/use_skill/draw_gacha will be registered
        # here as application use-cases. GUI code must never implement them.
        return ActionResult(
            ok=False,
            message=f"Action {action!r} is not implemented yet.",
            data={
                "player_id": player_id,
                "payload": dict(payload),
            },
        )
