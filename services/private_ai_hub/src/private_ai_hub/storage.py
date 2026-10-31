from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Iterable


Migration = tuple[int, str]

MIGRATIONS: tuple[Migration, ...] = (
    (
        1,
        """
        CREATE TABLE IF NOT EXISTS service_metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """,
    ),
)


def connect(path: Path | str) -> sqlite3.Connection:
    database_path = Path(path)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    return connection


def _ensure_migration_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    connection.commit()


def current_version(connection: sqlite3.Connection) -> int:
    _ensure_migration_table(connection)
    row = connection.execute(
        "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
    ).fetchone()
    return int(row[0])


def target_version(migrations: Iterable[Migration] = MIGRATIONS) -> int:
    versions = [version for version, _sql in migrations]
    return max(versions, default=0)


def migrate(
    connection: sqlite3.Connection,
    migrations: Iterable[Migration] = MIGRATIONS,
) -> int:
    _ensure_migration_table(connection)
    applied = {
        int(row[0])
        for row in connection.execute("SELECT version FROM schema_migrations")
    }

    for version, sql in sorted(migrations, key=lambda item: item[0]):
        if version in applied:
            continue
        with connection:
            connection.executescript(sql)
            connection.execute(
                "INSERT INTO schema_migrations(version) VALUES (?)",
                (version,),
            )
    return current_version(connection)


def initialize(path: Path | str) -> int:
    with connect(path) as connection:
        return migrate(connection)


def is_ready(path: Path | str) -> bool:
    try:
        with connect(path) as connection:
            return current_version(connection) == target_version()
    except sqlite3.Error:
        return False
