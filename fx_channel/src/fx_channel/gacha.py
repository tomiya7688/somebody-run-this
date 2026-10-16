from __future__ import annotations

import random
import threading
from dataclasses import dataclass, field
from typing import Mapping

from .content import ContentRegistry, GachaDefinition


class GachaError(ValueError):
    """Raised when a gacha or wallet command is invalid."""


@dataclass
class PlayerCollection:
    currencies: dict[str, int]
    characters: dict[str, int] = field(default_factory=dict)


class GachaEngine:
    """
    Server-authoritative gacha and collection state.

    Clients receive results and published rates, but never perform the draw.
    """

    def __init__(
        self,
        *,
        content: ContentRegistry,
        starting_currencies: Mapping[str, int] | None = None,
        starting_characters: list[str] | None = None,
        rng: random.Random | random.SystemRandom | None = None,
    ) -> None:
        self._content = content
        self._starting_currencies = {
            str(currency): int(amount)
            for currency, amount in (starting_currencies or {}).items()
        }
        self._starting_characters = list(starting_characters or [])
        self._rng = rng or random.SystemRandom()
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

        characters: dict[str, int] = {}
        for character_id in self._starting_characters:
            characters[character_id] = characters.get(character_id, 0) + 1

        player = PlayerCollection(
            currencies=dict(self._starting_currencies),
            characters=characters,
        )
        self._players[player_id] = player
        return player

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
