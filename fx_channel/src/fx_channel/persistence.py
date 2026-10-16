from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Mapping, Protocol


class PlayerStateStore(Protocol):
    def load(self, namespace: str, player_id: str) -> dict[str, Any] | None:
        ...

    def save(
        self,
        namespace: str,
        player_id: str,
        payload: Mapping[str, Any],
    ) -> None:
        ...

    def list_player_ids(self, namespace: str) -> list[str]:
        ...


class MemoryPlayerStateStore:
    """Ephemeral store for tests and explicit development use."""

    def __init__(self) -> None:
        self._data: dict[tuple[str, str], dict[str, Any]] = {}
        self._lock = threading.RLock()

    def load(self, namespace: str, player_id: str) -> dict[str, Any] | None:
        with self._lock:
            value = self._data.get((namespace, player_id))
            if value is None:
                return None
            return json.loads(json.dumps(value))

    def save(
        self,
        namespace: str,
        player_id: str,
        payload: Mapping[str, Any],
    ) -> None:
        with self._lock:
            self._data[(namespace, player_id)] = json.loads(
                json.dumps(dict(payload))
            )

    def list_player_ids(self, namespace: str) -> list[str]:
        with self._lock:
            return sorted(
                player_id
                for stored_namespace, player_id in self._data
                if stored_namespace == namespace
            )


class SQLitePlayerStateStore:
    """
    Zero-configuration persistent player store.

    State is separated by namespace so trading, gacha, achievements, etc. can
    evolve independently while sharing one SQLite database file.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.path,
            timeout=30,
            isolation_level=None,
        )
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        return connection

    def _initialize(self) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS player_state (
                    namespace TEXT NOT NULL,
                    player_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (namespace, player_id)
                )
                """
            )

    def load(self, namespace: str, player_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT payload
                FROM player_state
                WHERE namespace = ? AND player_id = ?
                """,
                (namespace, player_id),
            ).fetchone()

        if row is None:
            return None

        value = json.loads(row[0])
        if not isinstance(value, dict):
            raise ValueError("Stored player state must be a JSON object.")
        return value

    def save(
        self,
        namespace: str,
        player_id: str,
        payload: Mapping[str, Any],
    ) -> None:
        encoded = json.dumps(
            dict(payload),
            ensure_ascii=False,
            separators=(",", ":"),
        )

        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    """
                    INSERT INTO player_state(namespace, player_id, payload)
                    VALUES (?, ?, ?)
                    ON CONFLICT(namespace, player_id)
                    DO UPDATE SET
                        payload = excluded.payload,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (namespace, player_id, encoded),
                )
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise

    def list_player_ids(self, namespace: str) -> list[str]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT player_id
                FROM player_state
                WHERE namespace = ?
                ORDER BY player_id
                """,
                (namespace,),
            ).fetchall()

        return [str(row[0]) for row in rows]

    def backup_to(self, destination: str | Path) -> Path:
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)

        with self._lock:
            source = sqlite3.connect(self.path, timeout=30)
            try:
                dest = sqlite3.connect(target)
                try:
                    source.backup(dest)
                finally:
                    dest.close()
            finally:
                source.close()

        return target


def build_player_state_store(
    config: Mapping[str, Any] | None,
    *,
    base_dir: str | Path | None = None,
) -> PlayerStateStore:
    raw = dict(config or {})
    store_type = str(raw.get("type", "memory")).lower()

    if store_type == "memory":
        return MemoryPlayerStateStore()

    if store_type != "sqlite":
        raise ValueError(
            f"Unsupported storage.type {store_type!r}. "
            "Supported: memory, sqlite."
        )

    sqlite_config = raw.get("sqlite", {})
    if not isinstance(sqlite_config, Mapping):
        raise ValueError("storage.sqlite must be a mapping.")

    configured_path = Path(
        str(sqlite_config.get("path", "data/fx_channel.db"))
    )
    if configured_path.is_absolute():
        resolved = configured_path
    else:
        root = Path(base_dir or ".").resolve()
        resolved = root / configured_path

    return SQLitePlayerStateStore(resolved)
