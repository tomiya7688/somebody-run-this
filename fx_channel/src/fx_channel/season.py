from __future__ import annotations

import math
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from .persistence import PlayerStateStore


class SeasonError(ValueError):
    """Raised when season configuration or operations are invalid."""


@dataclass(frozen=True)
class SeasonSnapshot:
    id: str
    index: int
    enabled: bool
    start_at: float
    end_at: float | None
    duration_seconds: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "index": self.index,
            "enabled": self.enabled,
            "start_at": self.start_at,
            "start_at_iso": datetime.fromtimestamp(
                self.start_at,
                tz=timezone.utc,
            ).isoformat(),
            "end_at": self.end_at,
            "end_at_iso": (
                datetime.fromtimestamp(
                    self.end_at,
                    tz=timezone.utc,
                ).isoformat()
                if self.end_at is not None
                else None
            ),
            "duration_seconds": self.duration_seconds,
        }


class SeasonManager:
    """Persistent UTC season clock with automatic rollover."""

    _STATE_NAMESPACE = "system"
    _STATE_PLAYER_ID = "__season__"

    def __init__(
        self,
        *,
        config: Mapping[str, Any] | None,
        state_store: PlayerStateStore,
        clock: Callable[[], float] = time.time,
    ) -> None:
        raw = dict(config or {})
        self.enabled = bool(raw.get("enabled", True))
        self.reset_balance = bool(raw.get("reset_balance", True))
        self.keep_achievements = bool(raw.get("keep_achievements", True))
        self._state_store = state_store
        self._clock = clock

        duration_days = float(raw.get("duration_days", 7))
        if self.enabled and duration_days <= 0:
            raise SeasonError("season.duration_days must be greater than 0.")

        self.duration_seconds = (
            duration_days * 86400.0
            if self.enabled
            else None
        )
        self._current = self._load_or_create()

    def _load_or_create(self) -> SeasonSnapshot:
        stored = self._state_store.load(
            self._STATE_NAMESPACE,
            self._STATE_PLAYER_ID,
        )

        if stored is not None:
            snapshot = self._deserialize(stored)
            # If the operator changed enabled/duration settings, keep the
            # current index but start using the new schedule from now.
            if snapshot.enabled != self.enabled:
                return self._start_new_schedule(
                    index=snapshot.index + 1,
                    now=self._clock(),
                )
            if (
                self.enabled
                and snapshot.duration_seconds != self.duration_seconds
            ):
                return self._start_new_schedule(
                    index=snapshot.index + 1,
                    now=self._clock(),
                )
            return snapshot

        return self._start_new_schedule(index=1, now=self._clock())

    def _deserialize(
        self,
        stored: Mapping[str, Any],
    ) -> SeasonSnapshot:
        enabled = bool(stored.get("enabled", self.enabled))
        index = int(stored.get("index", 1))
        start_at = float(stored.get("start_at", self._clock()))
        raw_end = stored.get("end_at")
        end_at = float(raw_end) if raw_end is not None else None
        raw_duration = stored.get("duration_seconds")
        duration = (
            float(raw_duration)
            if raw_duration is not None
            else None
        )

        return SeasonSnapshot(
            id=str(stored.get("id", self._season_id(index, enabled))),
            index=index,
            enabled=enabled,
            start_at=start_at,
            end_at=end_at,
            duration_seconds=duration,
        )

    def _season_id(self, index: int, enabled: bool) -> str:
        if not enabled:
            return "permanent"
        return f"season-{index:06d}"

    def _start_new_schedule(
        self,
        *,
        index: int,
        now: float,
    ) -> SeasonSnapshot:
        snapshot = SeasonSnapshot(
            id=self._season_id(index, self.enabled),
            index=index,
            enabled=self.enabled,
            start_at=now,
            end_at=(
                now + self.duration_seconds
                if self.duration_seconds is not None
                else None
            ),
            duration_seconds=self.duration_seconds,
        )
        self._save(snapshot)
        self._current = snapshot
        return snapshot

    def _save(self, snapshot: SeasonSnapshot) -> None:
        self._state_store.save(
            self._STATE_NAMESPACE,
            self._STATE_PLAYER_ID,
            {
                "id": snapshot.id,
                "index": snapshot.index,
                "enabled": snapshot.enabled,
                "start_at": snapshot.start_at,
                "end_at": snapshot.end_at,
                "duration_seconds": snapshot.duration_seconds,
            },
        )

    def ensure_current(
        self,
        now: float | None = None,
    ) -> tuple[SeasonSnapshot, bool]:
        current = self._current
        if (
            not current.enabled
            or current.end_at is None
            or current.duration_seconds is None
        ):
            return current, False

        timestamp = self._clock() if now is None else float(now)
        if timestamp < current.end_at:
            return current, False

        elapsed_after_first_end = max(0.0, timestamp - current.end_at)
        extra_periods = math.floor(
            elapsed_after_first_end / current.duration_seconds
        )
        periods = 1 + extra_periods

        next_snapshot = SeasonSnapshot(
            id=self._season_id(
                current.index + periods,
                True,
            ),
            index=current.index + periods,
            enabled=True,
            start_at=current.start_at + periods * current.duration_seconds,
            end_at=current.end_at + periods * current.duration_seconds,
            duration_seconds=current.duration_seconds,
        )
        self._save(next_snapshot)
        self._current = next_snapshot
        return next_snapshot, True

    def advance_now(
        self,
        now: float | None = None,
    ) -> SeasonSnapshot:
        timestamp = self._clock() if now is None else float(now)
        return self._start_new_schedule(
            index=self._current.index + 1,
            now=timestamp,
        )

    def snapshot(self) -> SeasonSnapshot:
        current, _ = self.ensure_current()
        return current

    def participant_namespace(
        self,
        season: SeasonSnapshot | None = None,
    ) -> str:
        target = season or self.snapshot()
        return f"season_players:{target.id}"

    def mark_participant(
        self,
        player_id: str,
        *,
        now: float | None = None,
    ) -> None:
        season = self.snapshot()
        namespace = self.participant_namespace(season)
        if self._state_store.load(namespace, player_id) is not None:
            return

        self._state_store.save(
            namespace,
            player_id,
            {
                "joined_at": (
                    self._clock()
                    if now is None
                    else float(now)
                )
            },
        )

    def player_ids(
        self,
        season: SeasonSnapshot | None = None,
    ) -> list[str]:
        target = season or self.snapshot()
        return self._state_store.list_player_ids(
            self.participant_namespace(target)
        )
