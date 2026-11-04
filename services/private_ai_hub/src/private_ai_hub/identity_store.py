from __future__ import annotations

from pathlib import Path
import time
import uuid

from .identity import (
    BUILTIN_ROLE_PERMISSIONS,
    Group,
    Organization,
    Permission,
    Role,
    User,
)
from .storage import connect


def _non_empty(value: object, *, field: str, maximum: int = 256) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    normalized = value.strip()
    if len(normalized) > maximum:
        raise ValueError(f"{field} is too long")
    return normalized


def _key(value: object, *, field: str) -> str:
    return _non_empty(value, field=field).casefold()


def _new_id() -> str:
    return str(uuid.uuid4())


def _builtin_role_id(organization_id: str, role_name: str) -> str:
    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"private-ai://{organization_id}/role/{role_name.casefold()}",
        )
    )


class IdentityStore:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def create_organization(
        self,
        organization_id: str,
        name: str,
    ) -> Organization:
        org_id = _non_empty(
            organization_id, field="organization_id", maximum=128
        )
        org_name = _non_empty(name, field="organization name")
        now = int(time.time())
        with connect(self.path) as connection:
            connection.execute(
                """
                INSERT INTO organizations(id, name, created_at)
                VALUES (?, ?, ?)
                """,
                (org_id, org_name, now),
            )
        return Organization(id=org_id, name=org_name)

    def get_organization(self, organization_id: str) -> Organization | None:
        with connect(self.path) as connection:
            row = connection.execute(
                "SELECT id, name FROM organizations WHERE id = ?",
                (organization_id,),
            ).fetchone()
        if row is None:
            return None
        return Organization(id=str(row[0]), name=str(row[1]))

    def create_user(
        self,
        organization_id: str,
        username: str,
        *,
        display_name: str | None = None,
        user_id: str | None = None,
        enabled: bool = True,
    ) -> User:
        org_id = _non_empty(
            organization_id, field="organization_id", maximum=128
        )
        user_name = _non_empty(username, field="username", maximum=128)
        user_key = _key(username, field="username")
        display = _non_empty(
            display_name if display_name is not None else user_name,
            field="display_name",
        )
        if not isinstance(enabled, bool):
            raise ValueError("enabled must be boolean")
        resolved_id = user_id or _new_id()
        now = int(time.time())

        with connect(self.path) as connection:
            connection.execute(
                """
                INSERT INTO users(
                    id, organization_id, username, username_key,
                    display_name, enabled, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    resolved_id,
                    org_id,
                    user_name,
                    user_key,
                    display,
                    1 if enabled else 0,
                    now,
                ),
            )
        return User(
            id=resolved_id,
            organization_id=org_id,
            username=user_name,
            display_name=display,
            enabled=enabled,
        )

    def _user_from_row(self, row: tuple[object, ...]) -> User:
        return User(
            id=str(row[0]),
            organization_id=str(row[1]),
            username=str(row[2]),
            display_name=str(row[3]),
            enabled=bool(row[4]),
        )

    def get_user(self, user_id: str) -> User | None:
        with connect(self.path) as connection:
            row = connection.execute(
                """
                SELECT id, organization_id, username, display_name, enabled
                FROM users
                WHERE id = ?
                """,
                (user_id,),
            ).fetchone()
        return None if row is None else self._user_from_row(row)

    def find_user_by_username(
        self,
        organization_id: str,
        username: str,
    ) -> User | None:
        user_key = _key(username, field="username")
        with connect(self.path) as connection:
            row = connection.execute(
                """
                SELECT id, organization_id, username, display_name, enabled
                FROM users
                WHERE organization_id = ? AND username_key = ?
                """,
                (organization_id, user_key),
            ).fetchone()
        return None if row is None else self._user_from_row(row)

    def set_user_enabled(self, user_id: str, enabled: bool) -> None:
        if not isinstance(enabled, bool):
            raise ValueError("enabled must be boolean")
        with connect(self.path) as connection:
            cursor = connection.execute(
                "UPDATE users SET enabled = ? WHERE id = ?",
                (1 if enabled else 0, user_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"unknown user: {user_id}")

    def set_local_credential(
        self,
        user_id: str,
        *,
        salt: bytes,
        password_hash: bytes,
        scrypt_n: int,
        scrypt_r: int,
        scrypt_p: int,
        dklen: int,
    ) -> None:
        now = int(time.time())
        with connect(self.path) as connection:
            connection.execute(
                """
                INSERT INTO local_credentials(
                    user_id, salt, password_hash,
                    scrypt_n, scrypt_r, scrypt_p, dklen, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    salt = excluded.salt,
                    password_hash = excluded.password_hash,
                    scrypt_n = excluded.scrypt_n,
                    scrypt_r = excluded.scrypt_r,
                    scrypt_p = excluded.scrypt_p,
                    dklen = excluded.dklen,
                    updated_at = excluded.updated_at
                """,
                (
                    user_id,
                    salt,
                    password_hash,
                    scrypt_n,
                    scrypt_r,
                    scrypt_p,
                    dklen,
                    now,
                ),
            )

    def get_local_credential(
        self,
        user_id: str,
    ) -> tuple[bytes, bytes, int, int, int, int] | None:
        with connect(self.path) as connection:
            row = connection.execute(
                """
                SELECT salt, password_hash, scrypt_n, scrypt_r, scrypt_p, dklen
                FROM local_credentials
                WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()
        if row is None:
            return None
        return (
            bytes(row[0]),
            bytes(row[1]),
            int(row[2]),
            int(row[3]),
            int(row[4]),
            int(row[5]),
        )

    def _role_from_row(self, row: tuple[object, ...]) -> Role:
        return Role(
            id=str(row[0]),
            organization_id=str(row[1]),
            name=str(row[2]),
            built_in=bool(row[3]),
        )

    def ensure_role(
        self,
        organization_id: str,
        name: str,
        *,
        built_in: bool = False,
        role_id: str | None = None,
    ) -> Role:
        role_name = _non_empty(name, field="role name", maximum=128)
        role_key = _key(role_name, field="role name")
        with connect(self.path) as connection:
            row = connection.execute(
                """
                SELECT id, organization_id, name, built_in
                FROM roles
                WHERE organization_id = ? AND name_key = ?
                """,
                (organization_id, role_key),
            ).fetchone()
            if row is not None:
                role = self._role_from_row(row)
                if built_in and not role.built_in:
                    connection.execute(
                        "UPDATE roles SET built_in = 1 WHERE id = ?",
                        (role.id,),
                    )
                    role = Role(
                        id=role.id,
                        organization_id=role.organization_id,
                        name=role.name,
                        built_in=True,
                    )
                return role

            resolved_id = role_id or _new_id()
            connection.execute(
                """
                INSERT INTO roles(
                    id, organization_id, name, name_key, built_in, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    resolved_id,
                    organization_id,
                    role_name,
                    role_key,
                    1 if built_in else 0,
                    int(time.time()),
                ),
            )
        return Role(
            id=resolved_id,
            organization_id=organization_id,
            name=role_name,
            built_in=built_in,
        )

    def replace_role_permissions(
        self,
        role_id: str,
        permissions: frozenset[Permission | str] | set[Permission | str],
    ) -> None:
        normalized = sorted(
            {
                _non_empty(str(permission), field="permission", maximum=128)
                for permission in permissions
            }
        )
        with connect(self.path) as connection:
            role = connection.execute(
                "SELECT id FROM roles WHERE id = ?",
                (role_id,),
            ).fetchone()
            if role is None:
                raise KeyError(f"unknown role: {role_id}")
            connection.execute(
                "DELETE FROM role_permissions WHERE role_id = ?",
                (role_id,),
            )
            connection.executemany(
                """
                INSERT INTO role_permissions(role_id, permission)
                VALUES (?, ?)
                """,
                ((role_id, permission) for permission in normalized),
            )

    def ensure_builtin_roles(
        self,
        organization_id: str,
    ) -> dict[str, Role]:
        roles: dict[str, Role] = {}
        for name, permissions in BUILTIN_ROLE_PERMISSIONS.items():
            role = self.ensure_role(
                organization_id,
                name,
                built_in=True,
                role_id=_builtin_role_id(organization_id, name),
            )
            self.replace_role_permissions(role.id, set(permissions))
            roles[name] = role
        return roles

    def create_group(
        self,
        organization_id: str,
        name: str,
        *,
        group_id: str | None = None,
    ) -> Group:
        group_name = _non_empty(name, field="group name", maximum=128)
        group_key = _key(group_name, field="group name")
        resolved_id = group_id or _new_id()
        with connect(self.path) as connection:
            connection.execute(
                """
                INSERT INTO groups(
                    id, organization_id, name, name_key, created_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    resolved_id,
                    organization_id,
                    group_name,
                    group_key,
                    int(time.time()),
                ),
            )
        return Group(
            id=resolved_id,
            organization_id=organization_id,
            name=group_name,
        )

    def _entity_organization(
        self,
        connection,
        table: str,
        entity_id: str,
    ) -> str:
        if table not in {"users", "roles", "groups"}:
            raise ValueError("unsupported identity table")
        row = connection.execute(
            f"SELECT organization_id FROM {table} WHERE id = ?",
            (entity_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown {table[:-1]}: {entity_id}")
        return str(row[0])

    def add_user_to_group(self, user_id: str, group_id: str) -> None:
        with connect(self.path) as connection:
            user_org = self._entity_organization(connection, "users", user_id)
            group_org = self._entity_organization(connection, "groups", group_id)
            if user_org != group_org:
                raise ValueError("user and group must belong to the same organization")
            connection.execute(
                """
                INSERT OR IGNORE INTO group_memberships(group_id, user_id)
                VALUES (?, ?)
                """,
                (group_id, user_id),
            )

    def assign_role_to_user(self, user_id: str, role_id: str) -> None:
        with connect(self.path) as connection:
            user_org = self._entity_organization(connection, "users", user_id)
            role_org = self._entity_organization(connection, "roles", role_id)
            if user_org != role_org:
                raise ValueError("user and role must belong to the same organization")
            connection.execute(
                """
                INSERT OR IGNORE INTO user_roles(user_id, role_id)
                VALUES (?, ?)
                """,
                (user_id, role_id),
            )

    def assign_role_to_group(self, group_id: str, role_id: str) -> None:
        with connect(self.path) as connection:
            group_org = self._entity_organization(connection, "groups", group_id)
            role_org = self._entity_organization(connection, "roles", role_id)
            if group_org != role_org:
                raise ValueError("group and role must belong to the same organization")
            connection.execute(
                """
                INSERT OR IGNORE INTO group_roles(group_id, role_id)
                VALUES (?, ?)
                """,
                (group_id, role_id),
            )

    def permissions_for_user(self, user_id: str) -> frozenset[str]:
        with connect(self.path) as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT rp.permission
                FROM role_permissions rp
                JOIN user_roles ur ON ur.role_id = rp.role_id
                WHERE ur.user_id = ?

                UNION

                SELECT DISTINCT rp.permission
                FROM role_permissions rp
                JOIN group_roles gr ON gr.role_id = rp.role_id
                JOIN group_memberships gm ON gm.group_id = gr.group_id
                WHERE gm.user_id = ?
                """,
                (user_id, user_id),
            ).fetchall()
        return frozenset(str(row[0]) for row in rows)

    def create_session_record(
        self,
        *,
        token_hash: str,
        user_id: str,
        provider_id: str,
        created_at: int,
        expires_at: int,
    ) -> None:
        with connect(self.path) as connection:
            connection.execute(
                """
                INSERT INTO sessions(
                    token_hash, user_id, provider_id,
                    created_at, expires_at, revoked_at
                )
                VALUES (?, ?, ?, ?, ?, NULL)
                """,
                (
                    token_hash,
                    user_id,
                    provider_id,
                    created_at,
                    expires_at,
                ),
            )

    def active_session_user_id(
        self,
        token_hash: str,
        *,
        now: int,
    ) -> str | None:
        with connect(self.path) as connection:
            row = connection.execute(
                """
                SELECT s.user_id
                FROM sessions s
                JOIN users u ON u.id = s.user_id
                WHERE s.token_hash = ?
                  AND s.revoked_at IS NULL
                  AND s.expires_at > ?
                  AND u.enabled = 1
                """,
                (token_hash, now),
            ).fetchone()
        return None if row is None else str(row[0])

    def revoke_session(self, token_hash: str, *, now: int) -> None:
        with connect(self.path) as connection:
            connection.execute(
                """
                UPDATE sessions
                SET revoked_at = COALESCE(revoked_at, ?)
                WHERE token_hash = ?
                """,
                (now, token_hash),
            )

    def revoke_all_sessions(self, user_id: str, *, now: int) -> None:
        with connect(self.path) as connection:
            connection.execute(
                """
                UPDATE sessions
                SET revoked_at = COALESCE(revoked_at, ?)
                WHERE user_id = ? AND revoked_at IS NULL
                """,
                (now, user_id),
            )
