from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .content import ContentRegistry, load_content_registry
from .market import PriceProvider, build_price_provider


class FxChannelRuntime:
    """
    Backend-only runtime.

    This object owns market providers and content registries. It is created by
    the server process and is never constructed inside the user or operator GUI
    applications.
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
        self._starting_balance = float(
            operator_config.get("game", {}).get("starting_balance", 1_000_000)
        )

    def user_quotes(self) -> list[dict[str, Any]]:
        prices = self._price_provider.get_prices(self._symbols)
        return [
            {"symbol": symbol, "price": float(prices[symbol])}
            for symbol in self._symbols
        ]

    def user_home(self, player_id: str) -> dict[str, Any]:
        quotes = self.user_quotes()
        characters = [
            {
                "id": character.id,
                "name": character.name,
                "rarity": character.rarity,
                "skill_ids": list(character.skills),
            }
            for character in self._content.characters.values()
        ]

        return {
            "player": {
                "player_id": player_id,
                "display_name": player_id,
                "balance": self._starting_balance,
                "equity": self._starting_balance,
            },
            "quotes": quotes,
            "characters": characters,
        }

    def user_action(
        self,
        player_id: str,
        action: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        return {
            "ok": False,
            "message": f"User action {action!r} is not implemented yet.",
            "data": {
                "player_id": player_id,
                "payload": dict(payload),
            },
        }

    def operator_status(self) -> dict[str, Any]:
        return {
            "market_mode": str(self._config["market"]["mode"]),
            "symbols": list(self._symbols),
            "characters": len(self._content.characters),
            "skills": len(self._content.skills),
            "gacha_pools": len(self._content.gacha),
        }

    def operator_action(
        self,
        action: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        return {
            "ok": False,
            "message": f"Operator action {action!r} is not implemented yet.",
            "data": {"payload": dict(payload)},
        }
