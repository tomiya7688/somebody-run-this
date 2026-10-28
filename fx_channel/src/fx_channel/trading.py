from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, TypedDict

from .persistence import PlayerStateStore


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


class ClosePositionResult(TypedDict):
    position: Position
    exit_price: Decimal
    realized_pnl: Decimal
    cash: Decimal


@dataclass
class PlayerPortfolio:
    player_id: str
    cash: Decimal
    positions: dict[str, Position] = field(default_factory=dict)


class TradingEngine:
    """
    Server-authoritative trading domain.

    Prices are read-only inputs from the Market layer. The engine may persist
    player state, but it has no API to alter REAL or SIMULATED market prices.
    """

    _STATE_NAMESPACE = "trading"

    def __init__(
        self,
        *,
        symbols: list[str],
        starting_balance: float | int | str,
        max_leverage: float | int | str,
        allow_negative_balance: bool,
        state_store: PlayerStateStore | None = None,
        state_namespace: str = "trading",
    ) -> None:
        self._symbols = frozenset(symbols)
        self._starting_balance = _decimal(
            starting_balance,
            field_name="starting_balance",
        )
        self._max_leverage = _decimal(max_leverage, field_name="max_leverage")
        self._allow_negative_balance = bool(allow_negative_balance)
        self._state_store = state_store
        self._state_namespace = state_namespace
        self._players: dict[str, PlayerPortfolio] = {}
        self._lock = threading.RLock()

    def _player(self, player_id: str) -> PlayerPortfolio:
        player_id = player_id.strip()
        if not player_id:
            raise TradingError("player_id is required.")

        player = self._players.get(player_id)
        if player is not None:
            return player

        stored = (
            self._state_store.load(self._state_namespace, player_id)
            if self._state_store is not None
            else None
        )
        if stored is not None:
            player = self._deserialize_player(player_id, stored)
        else:
            player = PlayerPortfolio(
                player_id=player_id,
                cash=self._starting_balance,
            )

        self._players[player_id] = player
        return player

    def _deserialize_player(
        self,
        player_id: str,
        stored: Mapping[str, Any],
    ) -> PlayerPortfolio:
        cash = _decimal(stored.get("cash"), field_name="stored cash")
        positions: dict[str, Position] = {}

        raw_positions = stored.get("positions", [])
        if not isinstance(raw_positions, list):
            raise TradingError("Stored positions must be a list.")

        for raw in raw_positions:
            if not isinstance(raw, Mapping):
                raise TradingError("Stored position must be an object.")

            position = Position(
                id=str(raw["id"]),
                symbol=str(raw["symbol"]),
                side=str(raw["side"]),
                margin=_decimal(raw["margin"], field_name="stored margin"),
                leverage=_decimal(
                    raw["leverage"],
                    field_name="stored leverage",
                ),
                entry_price=_decimal(
                    raw["entry_price"],
                    field_name="stored entry_price",
                ),
            )
            positions[position.id] = position

        return PlayerPortfolio(
            player_id=player_id,
            cash=cash,
            positions=positions,
        )

    def _save(self, player: PlayerPortfolio) -> None:
        if self._state_store is None:
            return

        self._state_store.save(
            self._state_namespace,
            player.player_id,
            {
                "cash": str(player.cash),
                "positions": [
                    {
                        "id": position.id,
                        "symbol": position.symbol,
                        "side": position.side,
                        "margin": str(position.margin),
                        "leverage": str(position.leverage),
                        "entry_price": str(position.entry_price),
                    }
                    for position in player.positions.values()
                ],
            },
        )

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
            self._save(player)
            return position

    def close_position(
        self,
        *,
        player_id: str,
        position_id: str,
        current_price: Any,
    ) -> ClosePositionResult:
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

            self._save(player)

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
