from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping, Protocol, Sequence


@dataclass(frozen=True)
class PricePoint:
    timestamp: float
    price: float


@dataclass(frozen=True)
class MarketSnapshot:
    """
    Read-only market data exposed to skills.

    Skill implementations deliberately receive snapshots/history, not a
    PriceProvider or simulated-market engine. They therefore have no API for
    changing market prices.
    """

    prices: Mapping[str, float]
    history: Mapping[str, Sequence[PricePoint]]

    @classmethod
    def readonly(
        cls,
        prices: dict[str, float],
        history: dict[str, Sequence[PricePoint]],
    ) -> "MarketSnapshot":
        frozen_history = {
            symbol: tuple(points)
            for symbol, points in history.items()
        }
        return cls(
            prices=MappingProxyType(dict(prices)),
            history=MappingProxyType(frozen_history),
        )


@dataclass(frozen=True)
class SkillContext:
    player_id: str
    symbol: str
    market: MarketSnapshot
    public_game_data: Mapping[str, Any]


@dataclass(frozen=True)
class SkillResult:
    title: str
    message: str
    data: Mapping[str, Any]
    disclaimer: str | None = None


class SkillImplementation(Protocol):
    def execute(
        self,
        context: SkillContext,
        parameters: Mapping[str, Any],
    ) -> SkillResult:
        """Analyze read-only game/market data and return a player-facing result."""
