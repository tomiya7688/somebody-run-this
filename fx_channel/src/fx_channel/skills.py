from __future__ import annotations

import statistics
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .content import ContentRegistry, SkillDefinition
from .persistence import PlayerStateStore
from .skill_api import MarketSnapshot, SkillContext, SkillResult


class SkillError(ValueError):
    """Raised when a player cannot execute a requested skill."""


SkillFunction = Callable[
    [SkillContext, Mapping[str, Any]],
    SkillResult,
]


def _trend_reader_v1(
    context: SkillContext,
    parameters: Mapping[str, Any],
) -> SkillResult:
    history = list(context.market.history.get(context.symbol, ()))
    lookback = max(2, int(parameters.get("lookback_ticks", 120)))
    points = history[-lookback:]

    if len(points) < 2:
        return SkillResult(
            title="トレンドリーダー",
            message="まだ分析に必要な価格履歴が十分にありません。",
            data={
                "symbol": context.symbol,
                "samples": len(points),
                "signal": "insufficient_data",
            },
            disclaimer="この表示は予測であり、将来の値動きを保証しません。",
        )

    first = points[0].price
    last = points[-1].price
    if first <= 0:
        raise SkillError("Price history contains an invalid price.")

    change_ratio = (last - first) / first
    if change_ratio > 0:
        direction = "up"
        direction_ja = "上昇"
    elif change_ratio < 0:
        direction = "down"
        direction_ja = "下降"
    else:
        direction = "flat"
        direction_ja = "横ばい"

    strength = min(abs(change_ratio) * 1000.0, 1.0)

    return SkillResult(
        title="トレンドリーダー",
        message=(
            f"{context.symbol} は直近{len(points)}点では"
            f"{direction_ja}傾向です。"
        ),
        data={
            "symbol": context.symbol,
            "samples": len(points),
            "direction": direction,
            "change_ratio": change_ratio,
            "signal_strength": strength,
        },
        disclaimer="過去の値動きからの推測であり、将来の値動きを保証しません。",
    )


def _volatility_alert_v1(
    context: SkillContext,
    parameters: Mapping[str, Any],
) -> SkillResult:
    history = list(context.market.history.get(context.symbol, ()))
    lookback = max(3, int(parameters.get("lookback_ticks", 60)))
    threshold = float(parameters.get("threshold", 0.01))
    points = history[-lookback:]

    if len(points) < 3:
        return SkillResult(
            title="ボラティリティアラート",
            message="まだ変動率の計算に必要な履歴が十分にありません。",
            data={
                "symbol": context.symbol,
                "samples": len(points),
                "signal": "insufficient_data",
            },
        )

    returns: list[float] = []
    for previous, current in zip(points, points[1:]):
        if previous.price <= 0:
            continue
        returns.append((current.price - previous.price) / previous.price)

    if len(returns) < 2:
        raise SkillError("Not enough valid returns to calculate volatility.")

    volatility = statistics.pstdev(returns)
    active = volatility >= threshold

    return SkillResult(
        title="ボラティリティアラート",
        message=(
            "値動きが大きくなっています。"
            if active
            else "現在の値動きは設定された警戒水準を下回っています。"
        ),
        data={
            "symbol": context.symbol,
            "samples": len(points),
            "volatility": volatility,
            "threshold": threshold,
            "alert": active,
        },
    )


DEFAULT_IMPLEMENTATIONS: dict[str, SkillFunction] = {
    "trend_reader_v1": _trend_reader_v1,
    "volatility_alert_v1": _volatility_alert_v1,
}


@dataclass
class SkillEngine:
    content: ContentRegistry
    state_store: PlayerStateStore | None = None
    implementations: Mapping[str, SkillFunction] | None = None

    _STATE_NAMESPACE = "skills"

    def __post_init__(self) -> None:
        self._implementations = dict(
            self.implementations or DEFAULT_IMPLEMENTATIONS
        )

    def execute(
        self,
        *,
        player_id: str,
        skill_id: str,
        symbol: str,
        market: MarketSnapshot,
        public_game_data: Mapping[str, Any] | None = None,
        now: float | None = None,
    ) -> SkillResult:
        definition = self.content.skills.get(skill_id)
        if definition is None:
            raise SkillError("Skill not found.")

        implementation = self._implementations.get(definition.implementation)
        if implementation is None:
            raise SkillError(
                f"Skill implementation {definition.implementation!r} "
                "is not installed."
            )

        timestamp = time.time() if now is None else float(now)
        self._check_cooldown(
            player_id=player_id,
            definition=definition,
            now=timestamp,
        )

        context = SkillContext(
            player_id=player_id,
            symbol=symbol,
            market=market,
            public_game_data=dict(public_game_data or {}),
        )
        result = implementation(context, definition.parameters)
        self._record_use(
            player_id=player_id,
            skill_id=skill_id,
            now=timestamp,
        )
        return result

    def _load_state(self, player_id: str) -> dict[str, Any]:
        if self.state_store is None:
            return {}

        loaded = self.state_store.load(self._STATE_NAMESPACE, player_id)
        return dict(loaded or {})

    def _check_cooldown(
        self,
        *,
        player_id: str,
        definition: SkillDefinition,
        now: float,
    ) -> None:
        if definition.cooldown_seconds <= 0:
            return

        state = self._load_state(player_id)
        raw_last_used = dict(state.get("last_used", {}))
        last_used = raw_last_used.get(definition.id)
        if last_used is None:
            return

        remaining = (
            float(last_used)
            + definition.cooldown_seconds
            - now
        )
        if remaining > 0:
            raise SkillError(
                f"Skill is on cooldown for {remaining:.0f} more seconds."
            )

    def _record_use(
        self,
        *,
        player_id: str,
        skill_id: str,
        now: float,
    ) -> None:
        if self.state_store is None:
            return

        state = self._load_state(player_id)
        last_used = dict(state.get("last_used", {}))
        last_used[skill_id] = now
        state["last_used"] = last_used

        self.state_store.save(
            self._STATE_NAMESPACE,
            player_id,
            state,
        )
