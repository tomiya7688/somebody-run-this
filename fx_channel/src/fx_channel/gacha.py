from __future__ import annotations

import random
import threading
from dataclasses import dataclass, field
from typing import Any, Mapping

from .content import ContentRegistry, GachaDefinition
from .persistence import PlayerStateStore


class GachaError(ValueError):
    """Raised when a gacha or wallet command is invalid."""


@dataclass
class PlayerCollection:
    currencies: dict[str, int]
    characters: dict[str, int] = field(default_factory=dict)


class GachaEngine:
    """Server-authoritative gacha, wallet, and character collection state."""

    _STATE_NAMESPACE = "gacha"

    def __init__(
        self,
        *,
        content: ContentRegistry,
        starting_currencies: Mapping[str, int] | None = None,
        starting_characters: list[str] | None = None,
        rng: random.Random | random.SystemRandom | None = None,
        state_store: PlayerStateStore | None = None,
    ) -> None:
        self._content = content
        self._starting_currencies = {
            str(currency): int(amount)
            for currency, amount in (starting_currencies or {}).items()
        }
        self._starting_characters = list(starting_characters or [])
        self._rng = rng or random.SystemRandom()
        self._state_store = state_store
        self._players: dict[str, PlayerCollection] = {}
        self._lock = threading.RLock()

        for currency, amount in self._starting_currencies.items():
            if amount < 0:
                raise GachaError(
                    f"Starting currency {currency!r} must not be negative."
                )

        for character_id in self._starting_characters:
            if character_id not in self._content.characters:
                raise GachaError(
                    f"Unknown starting character: {character_id}"
                )

    def _player(self, player_id: str) -> PlayerCollection:
        player = self._players.get(player_id)
        if player is not None:
            return player

        stored = (
            self._state_store.load(self._STATE_NAMESPACE, player_id)
            if self._state_store is not None
            else None
        )
        if stored is not None:
            player = self._deserialize_player(stored)
        else:
            characters: dict[str, int] = {}
            for character_id in self._starting_characters:
                characters[character_id] = characters.get(character_id, 0) + 1

            player = PlayerCollection(
                currencies=dict(self._starting_currencies),
                characters=characters,
            )
            self._save(player_id, player)

        self._players[player_id] = player
        return player

    def _deserialize_player(
        self,
        stored: Mapping[str, Any],
    ) -> PlayerCollection:
        raw_currencies = stored.get("currencies", {})
        raw_characters = stored.get("characters", {})

        if not isinstance(raw_currencies, Mapping):
            raise GachaError("Stored currencies must be an object.")
        if not isinstance(raw_characters, Mapping):
            raise GachaError("Stored characters must be an object.")

        currencies = {
            str(currency): int(amount)
            for currency, amount in raw_currencies.items()
        }
        characters = {
            str(character_id): int(copies)
            for character_id, copies in raw_characters.items()
            if str(character_id) in self._content.characters
        }

        return PlayerCollection(
            currencies=currencies,
            characters=characters,
        )

    def _save(
        self,
        player_id: str,
        player: PlayerCollection,
    ) -> None:
        if self._state_store is None:
            return

        self._state_store.save(
            self._STATE_NAMESPACE,
            player_id,
            {
                "currencies": dict(player.currencies),
                "characters": dict(player.characters),
            },
        )

    def grant_currency(
        self,
        *,
        player_id: str,
        currency: str,
        amount: int,
    ) -> int:
        currency = currency.strip()
        if not currency:
            raise GachaError("currency is required.")
        if amount <= 0:
            raise GachaError("amount must be greater than 0.")

        with self._lock:
            player = self._player(player_id)
            player.currencies[currency] = player.currencies.get(currency, 0) + amount
            self._save(player_id, player)
            return player.currencies[currency]

    def draw(
        self,
        *,
        player_id: str,
        gacha_id: str,
        count: int = 1,
    ) -> dict:
        if count < 1 or count > 10:
            raise GachaError("count must be between 1 and 10.")

        pool = self._content.gacha.get(gacha_id)
        if pool is None:
            raise GachaError("Gacha pool not found.")

        total_cost = pool.cost * count

        with self._lock:
            player = self._player(player_id)
            balance = player.currencies.get(pool.currency, 0)
            if balance < total_cost:
                raise GachaError(
                    f"Not enough {pool.currency}. "
                    f"Need {total_cost}, have {balance}."
                )

            results = [
                self._draw_one(pool)
                for _ in range(count)
            ]
            player.currencies[pool.currency] = balance - total_cost

            result_rows = []
            for character_id in results:
                previous = player.characters.get(character_id, 0)
                player.characters[character_id] = previous + 1
                character = self._content.characters[character_id]
                result_rows.append(
                    {
                        "character_id": character_id,
                        "name": character.name,
                        "rarity": character.rarity,
                        "is_new": previous == 0,
                        "copies": previous + 1,
                    }
                )

            self._save(player_id, player)

            return {
                "gacha_id": pool.id,
                "currency": pool.currency,
                "cost": total_cost,
                "remaining": player.currencies[pool.currency],
                "results": result_rows,
            }

    def snapshot(self, player_id: str) -> dict:
        with self._lock:
            player = self._player(player_id)
            owned = []
            for character_id, copies in sorted(player.characters.items()):
                character = self._content.characters[character_id]
                owned.append(
                    {
                        "id": character.id,
                        "name": character.name,
                        "rarity": character.rarity,
                        "skill_ids": list(character.skills),
                        "copies": copies,
                    }
                )

            return {
                "currencies": dict(player.currencies),
                "characters": owned,
            }

    def public_pools(self) -> list[dict]:
        pools = []
        for pool in self._content.gacha.values():
            total_weight = sum(entry.weight for entry in pool.entries)
            entries = []
            for entry in pool.entries:
                character = self._content.characters[entry.character]
                entries.append(
                    {
                        "character_id": character.id,
                        "name": character.name,
                        "rarity": character.rarity,
                        "weight": entry.weight,
                        "probability": (
                            entry.weight / total_weight
                            if total_weight > 0
                            else 0.0
                        ),
                    }
                )

            pools.append(
                {
                    "id": pool.id,
                    "name": pool.name,
                    "currency": pool.currency,
                    "cost": pool.cost,
                    "entries": entries,
                }
            )
        return pools

    def _draw_one(self, pool: GachaDefinition) -> str:
        total = sum(entry.weight for entry in pool.entries)
        if total <= 0:
            raise GachaError("Gacha pool has no positive weight.")

        cursor = self._rng.random() * total
        accumulated = 0.0

        for entry in pool.entries:
            accumulated += entry.weight
            if cursor < accumulated:
                return entry.character

        return pool.entries[-1].character
