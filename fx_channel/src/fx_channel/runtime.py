from __future__ import annotations

import threading
import time
import zipfile
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .content import ContentRegistry, load_content_registry
from .gacha import GachaEngine, GachaError
from .market import PriceProvider, build_price_provider
from .persistence import (
    PlayerStateStore,
    SQLitePlayerStateStore,
    build_player_state_store,
)
from .season import SeasonManager, SeasonSnapshot
from .skill_api import MarketSnapshot, PricePoint
from .skills import SkillEngine, SkillError
from .trading import TradingEngine, TradingError


class FxChannelRuntime:
    """Backend-only runtime for all authoritative game state and rules."""

    def __init__(
        self,
        operator_config: dict[str, Any],
        *,
        content_root: str | Path = "content",
        data_root: str | Path | None = None,
    ) -> None:
        self._config = operator_config
        self._data_root = Path(data_root or ".").resolve()
        self._symbols = list(operator_config["symbols"])
        self._price_provider: PriceProvider = build_price_provider(
            operator_config
        )
        self._content: ContentRegistry = load_content_registry(
            content_root
        )
        self._state_store: PlayerStateStore = build_player_state_store(
            operator_config.get("storage", {}),
            base_dir=self._data_root,
        )
        self._season_lock = threading.RLock()

        self._market_history: dict[str, deque[PricePoint]] = {
            symbol: deque(maxlen=5000)
            for symbol in self._symbols
        }
        market_config = operator_config.get("market", {})
        market_mode = str(market_config.get("mode", "simulated"))
        if market_mode == "real":
            source_config = market_config.get("real", {})
            default_interval = 10.0
            interval_key = "poll_seconds"
        else:
            source_config = market_config.get("simulated", {})
            default_interval = 5.0
            interval_key = "tick_seconds"

        if not isinstance(source_config, Mapping):
            source_config = {}

        self._history_sample_interval = max(
            0.0,
            float(
                source_config.get(
                    interval_key,
                    default_interval,
                )
            ),
        )
        self._last_history_sample_at: float | None = None

        raw_game_config = operator_config.get("game", {})
        self._game_config = (
            dict(raw_game_config)
            if isinstance(raw_game_config, Mapping)
            else {}
        )

        self._season = SeasonManager(
            config=operator_config.get("season", {}),
            state_store=self._state_store,
        )
        current_season = self._season.snapshot()
        self._trading = self._build_trading(current_season)

        economy_config = operator_config.get("economy", {})
        starting_currencies = (
            economy_config.get("starting_currencies", {})
            if isinstance(economy_config, Mapping)
            else {}
        )
        if not isinstance(starting_currencies, Mapping):
            starting_currencies = {}

        raw_starting_characters = (
            economy_config.get("starting_characters", [])
            if isinstance(economy_config, Mapping)
            else []
        )
        starting_characters = (
            [str(value) for value in raw_starting_characters]
            if isinstance(raw_starting_characters, list)
            else []
        )

        self._gacha = GachaEngine(
            content=self._content,
            starting_currencies={
                str(currency): int(amount)
                for currency, amount in starting_currencies.items()
            },
            starting_characters=starting_characters,
            state_store=self._state_store,
        )
        self._skills = SkillEngine(
            content=self._content,
            state_store=self._state_store,
        )

    def _trading_namespace(
        self,
        season: SeasonSnapshot,
    ) -> str:
        if self._season.reset_balance:
            return f"trading:{season.id}"
        return "trading"

    def _build_trading(
        self,
        season: SeasonSnapshot,
    ) -> TradingEngine:
        return TradingEngine(
            symbols=self._symbols,
            starting_balance=self._game_config.get(
                "starting_balance",
                1_000_000,
            ),
            max_leverage=self._game_config.get(
                "max_leverage",
                25,
            ),
            allow_negative_balance=bool(
                self._game_config.get(
                    "allow_negative_balance",
                    False,
                )
            ),
            state_store=self._state_store,
            state_namespace=self._trading_namespace(season),
        )

    def _ensure_season(self) -> SeasonSnapshot:
        with self._season_lock:
            season, changed = self._season.ensure_current()
            if changed and self._season.reset_balance:
                self._trading = self._build_trading(season)
            return season

    def _prepare_player(
        self,
        player_id: str,
    ) -> SeasonSnapshot:
        season = self._ensure_season()
        self._season.mark_participant(player_id)
        return season

    def _prices(self) -> dict[str, float]:
        raw = self._price_provider.get_prices(self._symbols)
        prices = {
            symbol: float(raw[symbol])
            for symbol in self._symbols
        }

        monotonic_now = time.monotonic()
        should_sample = (
            self._last_history_sample_at is None
            or self._history_sample_interval <= 0
            or (
                monotonic_now - self._last_history_sample_at
                >= self._history_sample_interval
            )
        )

        if should_sample:
            timestamp = time.time()
            for symbol, price in prices.items():
                self._market_history[symbol].append(
                    PricePoint(
                        timestamp=timestamp,
                        price=price,
                    )
                )
            self._last_history_sample_at = monotonic_now

        return prices

    def _market_snapshot(
        self,
        prices: Mapping[str, float],
    ) -> MarketSnapshot:
        return MarketSnapshot.readonly(
            dict(prices),
            {
                symbol: tuple(history)
                for symbol, history in self._market_history.items()
            },
        )

    def _owned_skill_ids(
        self,
        player_id: str,
    ) -> set[str]:
        collection = self._gacha.snapshot(player_id)
        owned: set[str] = set()

        for row in collection["characters"]:
            character = self._content.characters.get(
                str(row["id"])
            )
            if character is not None:
                owned.update(character.skills)

        return owned

    def user_quotes(self) -> list[dict[str, Any]]:
        self._ensure_season()
        prices = self._prices()
        return [
            {
                "symbol": symbol,
                "price": prices[symbol],
            }
            for symbol in self._symbols
        ]

    def user_home(
        self,
        player_id: str,
    ) -> dict[str, Any]:
        season = self._prepare_player(player_id)
        prices = self._prices()
        portfolio = self._trading.snapshot(
            player_id=player_id,
            prices=prices,
        )
        collection = self._gacha.snapshot(player_id)
        owned_skill_ids = self._owned_skill_ids(player_id)

        return {
            "player": {
                "player_id": player_id,
                "display_name": player_id,
                "balance": portfolio["available_balance"],
                "equity": portfolio["equity"],
            },
            "season": season.to_dict(),
            "quotes": [
                {
                    "symbol": symbol,
                    "price": prices[symbol],
                }
                for symbol in self._symbols
            ],
            "positions": portfolio["positions"],
            "portfolio": portfolio,
            "wallet": collection["currencies"],
            "characters": collection["characters"],
            "skills": [
                {
                    "id": skill.id,
                    "name": skill.name,
                    "type": skill.type,
                    "description": skill.description,
                    "cooldown_seconds": skill.cooldown_seconds,
                }
                for skill in self._content.skills.values()
                if skill.id in owned_skill_ids
            ],
            "gacha_pools": self._gacha.public_pools(),
        }

    def user_ranking(
        self,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        season = self._ensure_season()
        limit = max(1, min(int(limit), 1000))
        prices = self._prices()
        player_ids = self._season.player_ids(season)

        rows: list[dict[str, Any]] = []
        for player_id in player_ids:
            portfolio = self._trading.snapshot(
                player_id=player_id,
                prices=prices,
            )
            rows.append(
                {
                    "player_id": player_id,
                    "equity": float(portfolio["equity"]),
                    "available_balance": float(
                        portfolio["available_balance"]
                    ),
                    "unrealized_pnl": float(
                        portfolio["unrealized_pnl"]
                    ),
                }
            )

        rows.sort(
            key=lambda row: (
                -float(row["equity"]),
                str(row["player_id"]),
            )
        )

        return [
            {
                "rank": index,
                **row,
            }
            for index, row in enumerate(
                rows[:limit],
                start=1,
            )
        ]

    def user_action(
        self,
        player_id: str,
        action: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        season = self._prepare_player(player_id)

        try:
            if action == "place_order":
                symbol = str(
                    payload.get("symbol", "")
                ).upper()
                prices = self._prices()
                if symbol not in prices:
                    raise TradingError(
                        f"Unknown symbol: {symbol}"
                    )

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
                        "season_id": season.id,
                        "position_id": position.id,
                        "symbol": position.symbol,
                        "side": position.side,
                        "entry_price": float(
                            position.entry_price
                        ),
                        "margin": float(position.margin),
                        "leverage": float(position.leverage),
                        "portfolio": portfolio,
                    },
                }

            if action == "close_position":
                position_id = str(
                    payload.get("position_id", "")
                )
                if not position_id:
                    raise TradingError(
                        "position_id is required."
                    )

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
                    raise TradingError(
                        "Position not found."
                    )

                close_result = self._trading.close_position(
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
                        "season_id": season.id,
                        "position_id": position_id,
                        "exit_price": float(
                            close_result["exit_price"]
                        ),
                        "realized_pnl": float(
                            close_result["realized_pnl"]
                        ),
                        "portfolio": portfolio,
                    },
                }

            if action == "portfolio":
                prices = self._prices()
                return {
                    "ok": True,
                    "message": "Portfolio loaded.",
                    "data": {
                        "season_id": season.id,
                        "portfolio": (
                            self._trading.snapshot(
                                player_id=player_id,
                                prices=prices,
                            )
                        ),
                    },
                }

            if action == "draw_gacha":
                gacha_id = str(
                    payload.get("gacha_id", "")
                )
                count = int(payload.get("count", 1))
                result = self._gacha.draw(
                    player_id=player_id,
                    gacha_id=gacha_id,
                    count=count,
                )
                return {
                    "ok": True,
                    "message": "Gacha draw completed.",
                    "data": result,
                }

            if action == "use_skill":
                skill_id = str(
                    payload.get("skill_id", "")
                ).strip()
                symbol = str(
                    payload.get("symbol", "")
                ).strip().upper()

                if symbol not in self._symbols:
                    raise SkillError(
                        f"Unknown symbol: {symbol}"
                    )
                if (
                    skill_id
                    not in self._owned_skill_ids(player_id)
                ):
                    raise SkillError(
                        "You do not own a character "
                        "with this skill."
                    )

                prices = self._prices()
                skill_result = self._skills.execute(
                    player_id=player_id,
                    skill_id=skill_id,
                    symbol=symbol,
                    market=self._market_snapshot(prices),
                    public_game_data={
                        "market_mode": (
                            self._config["market"]["mode"]
                        ),
                        "season_id": season.id,
                    },
                )
                return {
                    "ok": True,
                    "message": skill_result.message,
                    "data": {
                        "title": skill_result.title,
                        "result": dict(skill_result.data),
                        "disclaimer": skill_result.disclaimer,
                    },
                }

            return {
                "ok": False,
                "message": (
                    f"Unknown user action: {action!r}"
                ),
                "data": {},
            }

        except (
            TradingError,
            GachaError,
            SkillError,
            ValueError,
            TypeError,
        ) as exc:
            return {
                "ok": False,
                "message": str(exc),
                "data": {},
            }

    def _backup_server_state(
        self,
    ) -> dict[str, Any]:
        if not isinstance(
            self._state_store,
            SQLitePlayerStateStore,
        ):
            return {
                "ok": False,
                "message": (
                    "Server state backup requires "
                    "SQLite storage."
                ),
                "data": {},
            }

        timestamp = datetime.now(
            timezone.utc
        ).strftime("%Y%m%d-%H%M%S")
        backup_dir = self._data_root / "backups"
        backup_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        temp_db = (
            backup_dir
            / f"fx_channel-{timestamp}.db"
        )
        archive = (
            backup_dir
            / f"fx_channel-backup-{timestamp}.zip"
        )
        secret_path = (
            self._data_root
            / "data"
            / "user_session_secret.bin"
        )

        self._state_store.backup_to(temp_db)

        try:
            with zipfile.ZipFile(
                archive,
                mode="w",
                compression=zipfile.ZIP_DEFLATED,
            ) as output:
                output.write(
                    temp_db,
                    arcname="fx_channel.db",
                )
                if secret_path.exists():
                    output.write(
                        secret_path,
                        arcname="user_session_secret.bin",
                    )
        finally:
            temp_db.unlink(missing_ok=True)

        return {
            "ok": True,
            "message": (
                "Server state backup created."
            ),
            "data": {
                "backup": str(archive),
                "contains_session_secret": (
                    secret_path.exists()
                ),
            },
        }

    def operator_status(
        self,
    ) -> dict[str, Any]:
        season = self._ensure_season()
        return {
            "market_mode": str(
                self._config["market"]["mode"]
            ),
            "symbols": list(self._symbols),
            "characters": len(
                self._content.characters
            ),
            "skills": len(self._content.skills),
            "gacha_pools": len(
                self._content.gacha
            ),
            "season": season.to_dict(),
            "season_participants": len(
                self._season.player_ids(season)
            ),
        }

    def operator_action(
        self,
        action: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        try:
            if action == "backup_server_state":
                return self._backup_server_state()

            if action == "advance_season":
                with self._season_lock:
                    season = self._season.advance_now()
                    if self._season.reset_balance:
                        self._trading = (
                            self._build_trading(season)
                        )
                return {
                    "ok": True,
                    "message": "Season advanced.",
                    "data": {
                        "season": season.to_dict(),
                    },
                }

            if action == "grant_currency":
                player_id = str(
                    payload.get("player_id", "")
                ).strip()
                currency = str(
                    payload.get("currency", "")
                ).strip()
                amount = int(
                    payload.get("amount", 0)
                )

                if not player_id:
                    raise GachaError(
                        "player_id is required."
                    )

                balance = self._gacha.grant_currency(
                    player_id=player_id,
                    currency=currency,
                    amount=amount,
                )
                return {
                    "ok": True,
                    "message": "Currency granted.",
                    "data": {
                        "player_id": player_id,
                        "currency": currency,
                        "balance": balance,
                    },
                }

            return {
                "ok": False,
                "message": (
                    f"Unknown operator action: {action!r}"
                ),
                "data": {},
            }

        except (
            GachaError,
            ValueError,
            TypeError,
        ) as exc:
            return {
                "ok": False,
                "message": str(exc),
                "data": {},
            }
