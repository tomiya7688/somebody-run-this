from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping


class TradingError(ValueError):
    """Raised when a player trading command is invalid."""


def _decimal(value: Any, *, field_name: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise TradingError(f"{field_name} must be a number.") from exc

    if not result.is_finite():
        raise TradingError(f"{field_name} must be finite.")
    return result


@dataclass(frozen=True)
class Position:
    id: str
    symbol: str
    side: str
    margin: Decimal
    leverage: Decimal
    entry_price: Decimal

    @property
    def exposure(self) -> Decimal:
        return self.margin * self.leverage

    def unrealized_pnl(self, current_price: Decimal) -> Decimal:
        if self.entry_price <= 0:
            return Decimal("0")

        change_ratio = (current_price - self.entry_price) / self.entry_price
        direction = Decimal("1") if self.side == "buy" else Decimal("-1")
        return self.exposure * change_ratio * direction


@dataclass
class PlayerPortfolio:
    player_id: str
    cash: Decimal
    positions: dict[str, Position] = field(default_factory=dict)


class TradingEngine:
    """
    In-memory trading domain for the first playable server.

    Prices are inputs from the Market layer. The trading engine never mutates
    the market and therefore cannot influence REAL or SIMULATED prices.
    """

    def __init__(
        self,
        *,
        symbols: list[str],
        starting_balance: float | int | str,
        max_leverage: float | int | str,
        allow_negative_balance: bool,
    ) -> None:
        self._symbols = frozenset(symbols)
        self._starting_balance = _decimal(
            starting_balance,
            field_name="starting_balance",
        )
        self._max_leverage = _decimal(max_leverage, field_name="max_leverage")
        self._allow_negative_balance = bool(allow_negative_balance)
        self._players: dict[str, PlayerPortfolio] = {}
        self._lock = threading.RLock()

    def _player(self, player_id: str) -> PlayerPortfolio:
        player_id = player_id.strip()
        if not player_id:
            raise TradingError("player_id is required.")

        player = self._players.get(player_id)
        if player is None:
            player = PlayerPortfolio(
                player_id=player_id,
                cash=self._starting_balance,
            )
            self._players[player_id] = player
        return player

    def open_position(
        self,
        *,
        player_id: str,
        symbol: str,
        side: str,
        margin: Any,
        leverage: Any,
        price: Any,
    ) -> Position:
        symbol = symbol.strip().upper()
        side = side.strip().lower()

        if symbol not in self._symbols:
            raise TradingError(f"Unknown symbol: {symbol}")
        if side not in {"buy", "sell"}:
            raise TradingError("side must be 'buy' or 'sell'.")

        margin_value = _decimal(margin, field_name="margin")
        leverage_value = _decimal(leverage, field_name="leverage")
        price_value = _decimal(price, field_name="price")

        if margin_value <= 0:
            raise TradingError("margin must be greater than 0.")
        if leverage_value < 1 or leverage_value > self._max_leverage:
            raise TradingError(
                f"leverage must be between 1 and {self._max_leverage}."
            )
        if price_value <= 0:
            raise TradingError("price must be greater than 0.")

        with self._lock:
            player = self._player(player_id)
            if margin_value > player.cash:
                raise TradingError("Insufficient available balance.")

            position = Position(
                id=uuid.uuid4().hex,
                symbol=symbol,
                side=side,
                margin=margin_value,
                leverage=leverage_value,
                entry_price=price_value,
            )
            player.cash -= margin_value
            player.positions[position.id] = position
            return position

    def close_position(
        self,
        *,
        player_id: str,
        position_id: str,
        current_price: Any,
    ) -> dict[str, Decimal | Position]:
        price_value = _decimal(current_price, field_name="current_price")
        if price_value <= 0:
            raise TradingError("current_price must be greater than 0.")

        with self._lock:
            player = self._player(player_id)
            position = player.positions.get(position_id)
            if position is None:
                raise TradingError("Position not found.")

            pnl = position.unrealized_pnl(price_value)
            if not self._allow_negative_balance:
                pnl = max(pnl, -position.margin)

            player.cash += position.margin + pnl
            del player.positions[position_id]

            if not self._allow_negative_balance and player.cash < 0:
                player.cash = Decimal("0")

            return {
                "position": position,
                "exit_price": price_value,
                "realized_pnl": pnl,
                "cash": player.cash,
            }

    def snapshot(
        self,
        *,
        player_id: str,
        prices: Mapping[str, Any],
    ) -> dict[str, Any]:
        normalized_prices = {
            symbol: _decimal(price, field_name=f"price[{symbol}]")
            for symbol, price in prices.items()
        }

        with self._lock:
            player = self._player(player_id)
            rows: list[dict[str, Any]] = []
            total_margin = Decimal("0")
            total_unrealized = Decimal("0")

            for position in player.positions.values():
                current_price = normalized_prices.get(position.symbol)
                if current_price is None:
                    continue

                pnl = position.unrealized_pnl(current_price)
                if not self._allow_negative_balance:
                    pnl = max(pnl, -position.margin)

                total_margin += position.margin
                total_unrealized += pnl

                rows.append(
                    {
                        "id": position.id,
                        "symbol": position.symbol,
                        "side": position.side,
                        "margin": float(position.margin),
                        "leverage": float(position.leverage),
                        "exposure": float(position.exposure),
                        "entry_price": float(position.entry_price),
                        "current_price": float(current_price),
                        "unrealized_pnl": float(pnl),
                    }
                )

            equity = player.cash + total_margin + total_unrealized
            if not self._allow_negative_balance:
                equity = max(equity, Decimal("0"))

            return {
                "player_id": player.player_id,
                "available_balance": float(player.cash),
                "locked_margin": float(total_margin),
                "unrealized_pnl": float(total_unrealized),
                "equity": float(equity),
                "positions": rows,
            }
