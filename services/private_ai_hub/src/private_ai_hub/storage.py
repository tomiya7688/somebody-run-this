from __future__ import annotations

import logging
from pathlib import Path
import sqlite3
from typing import Iterable, Iterator


logger = logging.getLogger(__name__)

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


def _connect_read_only(path: Path) -> sqlite3.Connection:
    resolved = path.resolve(strict=True)
    connection = sqlite3.connect(
        f"{resolved.as_uri()}?mode=ro",
        uri=True,
    )
    connection.execute("PRAGMA query_only = ON")
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


def _read_current_version(connection: sqlite3.Connection) -> int:
    row = connection.execute(
        "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
    ).fetchone()
    return int(row[0])


def current_version(connection: sqlite3.Connection) -> int:
    _ensure_migration_table(connection)
    return _read_current_version(connection)


def target_version(migrations: Iterable[Migration] = MIGRATIONS) -> int:
    versions = [version for version, _sql in migrations]
    return max(versions, default=0)


def _iter_statements(sql: str) -> Iterator[str]:
    buffer = ""
    for line in sql.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            statement = buffer.strip()
            if statement:
                yield statement
            buffer = ""
    if buffer.strip():
        raise sqlite3.OperationalError("migration SQL contains an incomplete statement")


def migrate(
    connection: sqlite3.Connection,
    migrations: Iterable[Migration] = MIGRATIONS,
) -> int:
    _ensure_migration_table(connection)

    for version, sql in sorted(migrations, key=lambda item: item[0]):
        try:
            connection.execute("BEGIN IMMEDIATE")
            already_applied = connection.execute(
                "SELECT 1 FROM schema_migrations WHERE version = ?",
                (version,),
            ).fetchone()
            if already_applied is None:
                for statement in _iter_statements(sql):
                    connection.execute(statement)
                connection.execute(
                    "INSERT INTO schema_migrations(version) VALUES (?)",
                    (version,),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise

    return current_version(connection)


def initialize(path: Path | str) -> int:
    with connect(path) as connection:
        return migrate(connection)


def is_ready(path: Path | str) -> bool:
    database_path = Path(path)
    try:
        if not database_path.is_file():
            return False
        with _connect_read_only(database_path) as connection:
            try:
                return _read_current_version(connection) == target_version()
            except sqlite3.OperationalError as exc:
                if "no such table: schema_migrations" in str(exc):
                    return False
                raise
    except (OSError, sqlite3.Error) as exc:
        logger.warning(
            "readiness database check failed for %s: %s",
            database_path,
            exc,
        )
        return False
