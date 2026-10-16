from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .content import ContentRegistry, load_content_registry
from .market import PriceProvider, build_price_provider
from .trading import TradingEngine, TradingError


class FxChannelRuntime:
    """Backend-only runtime for market, trading, content, and operator state."""

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

        game_config = operator_config.get("game", {})
        self._trading = TradingEngine(
            symbols=self._symbols,
            starting_balance=game_config.get("starting_balance", 1_000_000),
            max_leverage=game_config.get("max_leverage", 25),
            allow_negative_balance=bool(
                game_config.get("allow_negative_balance", False)
            ),
        )

    def _prices(self) -> dict[str, float]:
        raw = self._price_provider.get_prices(self._symbols)
        return {
            symbol: float(raw[symbol])
            for symbol in self._symbols
        }

    def user_quotes(self) -> list[dict[str, Any]]:
        prices = self._prices()
        return [
            {"symbol": symbol, "price": prices[symbol]}
            for symbol in self._symbols
        ]

    def user_home(self, player_id: str) -> dict[str, Any]:
        prices = self._prices()
        portfolio = self._trading.snapshot(
            player_id=player_id,
            prices=prices,
        )
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
                "balance": portfolio["available_balance"],
                "equity": portfolio["equity"],
            },
            "quotes": [
                {"symbol": symbol, "price": prices[symbol]}
                for symbol in self._symbols
            ],
            "positions": portfolio["positions"],
            "portfolio": portfolio,
            "characters": characters,
        }

    def user_action(
        self,
        player_id: str,
        action: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        try:
            if action == "place_order":
                symbol = str(payload.get("symbol", "")).upper()
                prices = self._prices()
                if symbol not in prices:
                    raise TradingError(f"Unknown symbol: {symbol}")

                position = self._trading.open_position(
                    player_id=player_id,
                    symbol=symbol,
                    side=str(payload.get("side", "")),
                    margin=payload.get("margin"),
                    leverage=payload.get("leverage", 1),
                    price=prices[symbol],
                )
                portfolio = self._trading.snapshot(
                    player_id=player_id,
                    prices=prices,
                )
                return {
                    "ok": True,
                    "message": "Position opened.",
                    "data": {
                        "position_id": position.id,
                        "symbol": position.symbol,
                        "side": position.side,
                        "entry_price": float(position.entry_price),
                        "margin": float(position.margin),
                        "leverage": float(position.leverage),
                        "portfolio": portfolio,
                    },
                }

            if action == "close_position":
                position_id = str(payload.get("position_id", ""))
                if not position_id:
                    raise TradingError("position_id is required.")

                prices = self._prices()
                current = self._trading.snapshot(
                    player_id=player_id,
                    prices=prices,
                )
                position_rows = {
                    row["id"]: row
                    for row in current["positions"]
                }
                row = position_rows.get(position_id)
                if row is None:
                    raise TradingError("Position not found.")

                result = self._trading.close_position(
                    player_id=player_id,
                    position_id=position_id,
                    current_price=prices[row["symbol"]],
                )
                portfolio = self._trading.snapshot(
                    player_id=player_id,
                    prices=prices,
                )
                return {
                    "ok": True,
                    "message": "Position closed.",
                    "data": {
                        "position_id": position_id,
                        "exit_price": float(result["exit_price"]),
                        "realized_pnl": float(result["realized_pnl"]),
                        "portfolio": portfolio,
                    },
                }

            if action == "portfolio":
                prices = self._prices()
                return {
                    "ok": True,
                    "message": "Portfolio loaded.",
                    "data": {
                        "portfolio": self._trading.snapshot(
                            player_id=player_id,
                            prices=prices,
                        )
                    },
                }

            return {
                "ok": False,
                "message": f"Unknown user action: {action!r}",
                "data": {},
            }

        except TradingError as exc:
            return {
                "ok": False,
                "message": str(exc),
                "data": {},
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
