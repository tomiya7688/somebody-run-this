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
    (
        2,
        """
        CREATE TABLE organizations (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            created_at INTEGER NOT NULL
        );

        CREATE TABLE users (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            username TEXT NOT NULL,
            username_key TEXT NOT NULL,
            display_name TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
            created_at INTEGER NOT NULL,
            UNIQUE (organization_id, username_key)
        );

        CREATE TABLE local_credentials (
            user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            salt BLOB NOT NULL,
            password_hash BLOB NOT NULL,
            scrypt_n INTEGER NOT NULL,
            scrypt_r INTEGER NOT NULL,
            scrypt_p INTEGER NOT NULL,
            dklen INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        );

        CREATE TABLE groups (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            name_key TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            UNIQUE (organization_id, name_key)
        );

        CREATE TABLE roles (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            name_key TEXT NOT NULL,
            built_in INTEGER NOT NULL DEFAULT 0 CHECK (built_in IN (0, 1)),
            created_at INTEGER NOT NULL,
            UNIQUE (organization_id, name_key)
        );

        CREATE TABLE role_permissions (
            role_id TEXT NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
            permission TEXT NOT NULL,
            PRIMARY KEY (role_id, permission)
        );

        CREATE TABLE user_roles (
            user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            role_id TEXT NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
            PRIMARY KEY (user_id, role_id)
        );

        CREATE TABLE group_roles (
            group_id TEXT NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
            role_id TEXT NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
            PRIMARY KEY (group_id, role_id)
        );

        CREATE TABLE group_memberships (
            group_id TEXT NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
            user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            PRIMARY KEY (group_id, user_id)
        );

        CREATE TABLE sessions (
            token_hash TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            provider_id TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            expires_at INTEGER NOT NULL,
            revoked_at INTEGER
        );

        CREATE INDEX sessions_user_idx ON sessions(user_id);
        CREATE INDEX sessions_expiry_idx ON sessions(expires_at);
        """,
    ),
    (
        3,
        """
        CREATE TABLE audit_chain_heads (
            organization_id TEXT NOT NULL,
            stream TEXT NOT NULL CHECK (stream IN ('security', 'conversation')),
            head_hash TEXT NOT NULL,
            last_event_id INTEGER,
            updated_at INTEGER NOT NULL,
            PRIMARY KEY (organization_id, stream)
        );

        CREATE TABLE audit_chain_anchors (
            organization_id TEXT NOT NULL,
            stream TEXT NOT NULL CHECK (stream IN ('security', 'conversation')),
            anchor_hash TEXT NOT NULL,
            updated_at INTEGER NOT NULL,
            PRIMARY KEY (organization_id, stream)
        );

        CREATE TABLE security_audit_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            organization_id TEXT NOT NULL,
            actor_user_id TEXT,
            event_type TEXT NOT NULL,
            occurred_at INTEGER NOT NULL,
            metadata_json TEXT NOT NULL,
            previous_hash TEXT NOT NULL,
            event_hash TEXT NOT NULL UNIQUE
        );

        CREATE INDEX security_audit_org_time_idx
            ON security_audit_events(organization_id, occurred_at, id);

        CREATE TABLE conversation_audit_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            organization_id TEXT NOT NULL,
            owner_user_id TEXT NOT NULL,
            actor_user_id TEXT,
            project_id TEXT,
            conversation_id TEXT,
            event_type TEXT NOT NULL,
            occurred_at INTEGER NOT NULL,
            metadata_json TEXT NOT NULL,
            prompt_content TEXT,
            response_content TEXT,
            previous_hash TEXT NOT NULL,
            event_hash TEXT NOT NULL UNIQUE
        );

        CREATE INDEX conversation_audit_org_time_idx
            ON conversation_audit_events(organization_id, occurred_at, id);
        CREATE INDEX conversation_audit_owner_time_idx
            ON conversation_audit_events(
                organization_id, owner_user_id, occurred_at, id
            );
        """,
    ),
    (
        4,
        """
        CREATE TABLE models (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL
                REFERENCES organizations(id) ON DELETE CASCADE,
            model_key TEXT NOT NULL,
            display_name TEXT NOT NULL,
            source_kind TEXT NOT NULL
                CHECK (source_kind IN ('local', 'external')),
            backend_id TEXT NOT NULL,
            backend_model_id TEXT NOT NULL,
            local_path TEXT,
            revision TEXT,
            digest TEXT,
            enabled INTEGER NOT NULL DEFAULT 0
                CHECK (enabled IN (0, 1)),
            capabilities_json TEXT NOT NULL,
            context_limit INTEGER,
            health_state TEXT NOT NULL DEFAULT 'unknown'
                CHECK (health_state IN ('unknown', 'ready', 'unhealthy')),
            health_detail TEXT NOT NULL DEFAULT '',
            last_health_at INTEGER,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            UNIQUE (organization_id, model_key),
            UNIQUE (organization_id, backend_id, backend_model_id),
            UNIQUE (organization_id, id)
        );

        CREATE INDEX models_org_enabled_health_idx
            ON models(organization_id, enabled, health_state, model_key);

        CREATE TABLE model_policy_scopes (
            organization_id TEXT NOT NULL
                REFERENCES organizations(id) ON DELETE CASCADE,
            scope_type TEXT NOT NULL
                CHECK (scope_type IN ('organization', 'group', 'project')),
            scope_id TEXT NOT NULL,
            revision INTEGER NOT NULL,
            default_model_key TEXT,
            updated_at INTEGER NOT NULL,
            PRIMARY KEY (organization_id, scope_type, scope_id),
            FOREIGN KEY (organization_id, default_model_key)
                REFERENCES models(organization_id, model_key)
                ON DELETE SET NULL
        );

        CREATE TABLE model_policy_allowed_models (
            organization_id TEXT NOT NULL,
            scope_type TEXT NOT NULL,
            scope_id TEXT NOT NULL,
            model_key TEXT NOT NULL,
            PRIMARY KEY (
                organization_id, scope_type, scope_id, model_key
            ),
            FOREIGN KEY (organization_id, scope_type, scope_id)
                REFERENCES model_policy_scopes(
                    organization_id, scope_type, scope_id
                )
                ON DELETE CASCADE,
            FOREIGN KEY (organization_id, model_key)
                REFERENCES models(organization_id, model_key)
                ON DELETE CASCADE
        );

        CREATE INDEX model_policy_allowed_model_idx
            ON model_policy_allowed_models(organization_id, model_key);
        """,
    ),
)


def connect(path: Path | str) -> sqlite3.Connection:
    database_path = Path(path)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path, timeout=30.0)
    connection.execute("PRAGMA busy_timeout = 30000")
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _connect_read_only(path: Path) -> sqlite3.Connection:
    resolved = path.resolve(strict=True)
    connection = sqlite3.connect(
        f"{resolved.as_uri()}?mode=ro",
        uri=True,
        timeout=5.0,
    )
    connection.execute("PRAGMA busy_timeout = 5000")
    connection.execute("PRAGMA query_only = ON")
    return connection


def _create_migration_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def _read_current_version(connection: sqlite3.Connection) -> int:
    row = connection.execute(
        "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
    ).fetchone()
    return int(row[0])


def current_version(connection: sqlite3.Connection) -> int:
    try:
        return _read_current_version(connection)
    except sqlite3.OperationalError as exc:
        if "no such table: schema_migrations" in str(exc):
            return 0
        raise


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
    try:
        # Serialize schema creation, applied-version checks, migration SQL,
        # and version recording under one write transaction. A concurrent
        # initializer waits on BEGIN IMMEDIATE, then observes committed state.
        connection.execute("BEGIN IMMEDIATE")
        _create_migration_table(connection)

        for version, sql in sorted(migrations, key=lambda item: item[0]):
            already_applied = connection.execute(
                "SELECT 1 FROM schema_migrations WHERE version = ?",
                (version,),
            ).fetchone()
            if already_applied is not None:
                continue

            for statement in _iter_statements(sql):
                connection.execute(statement)
            connection.execute(
                "INSERT INTO schema_migrations(version) VALUES (?)",
                (version,),
            )

        version = _read_current_version(connection)
        connection.commit()
        return version
    except Exception:
        connection.rollback()
        raise


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
