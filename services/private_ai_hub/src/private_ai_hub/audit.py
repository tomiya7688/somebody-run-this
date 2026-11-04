from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import hmac
import itertools
import json
from pathlib import Path
import time
from typing import Mapping

from .identity import AuthorizationError, Permission, Principal, require_permission
from .storage import connect


_ZERO_HASH = "0" * 64
_REDACTED = "[REDACTED]"
_OMITTED_CONTENT = "[OMITTED: audit content exceeds configured limit]"

_SENSITIVE_KEYS = frozenset(
    {
        "password",
        "passwd",
        "secret",
        "client_secret",
        "token",
        "access_token",
        "refresh_token",
        "session_token",
        "authorization",
        "api_key",
        "apikey",
        "cookie",
        "set_cookie",
        "credential",
        "credentials",
        "private_key",
    }
)
_SENSITIVE_SUFFIXES = (
    "_password",
    "_secret",
    "_token",
    "_api_key",
    "_credential",
    "_credentials",
    "_private_key",
)


class AuditStream(StrEnum):
    SECURITY = "security"
    CONVERSATION = "conversation"


@dataclass(frozen=True)
class AuditSettings:
    security_enabled: bool = True
    conversation_enabled: bool = False
    store_prompt_content: bool = False
    store_response_content: bool = False
    retention_days: int = 180
    max_metadata_bytes: int = 16 * 1024
    max_content_bytes: int = 1024 * 1024

    def __post_init__(self) -> None:
        for name in (
            "security_enabled",
            "conversation_enabled",
            "store_prompt_content",
            "store_response_content",
        ):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"{name} must be boolean")

        for name, minimum, maximum in (
            ("retention_days", 0, 3650),
            ("max_metadata_bytes", 256, 1024 * 1024),
            ("max_content_bytes", 1024, 16 * 1024 * 1024),
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{name} must be an integer")
            if not minimum <= value <= maximum:
                raise ValueError(
                    f"{name} must be between {minimum} and {maximum}"
                )


@dataclass(frozen=True)
class SecurityAuditEvent:
    id: int
    organization_id: str
    actor_user_id: str | None
    event_type: str
    occurred_at: int
    metadata: Mapping[str, object]
    previous_hash: str
    event_hash: str


@dataclass(frozen=True)
class ConversationAuditEvent:
    id: int
    organization_id: str
    owner_user_id: str
    actor_user_id: str | None
    project_id: str | None
    conversation_id: str | None
    event_type: str
    occurred_at: int
    metadata: Mapping[str, object]
    prompt_content: str | None
    response_content: str | None
    previous_hash: str
    event_hash: str


def _non_empty(value: object, *, field: str, maximum: int = 256) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    normalized = value.strip()
    if len(normalized) > maximum:
        raise ValueError(f"{field} is too long")
    return normalized


def _optional_identifier(
    value: object | None,
    *,
    field: str,
    maximum: int = 256,
) -> str | None:
    if value is None:
        return None
    return _non_empty(value, field=field, maximum=maximum)


def _normalized_key(value: str) -> str:
    return value.strip().casefold().replace("-", "_").replace(" ", "_")


def _sensitive_key(value: str) -> bool:
    normalized = _normalized_key(value)
    return normalized in _SENSITIVE_KEYS or any(
        normalized.endswith(suffix) for suffix in _SENSITIVE_SUFFIXES
    )


def _redact_value(value: object, *, depth: int = 0) -> object:
    if depth > 8:
        return "[OMITTED: audit metadata depth limit]"

    if isinstance(value, Mapping):
        redacted: dict[str, object] = {}
        for raw_key, raw_value in itertools.islice(value.items(), 256):
            key = str(raw_key)
            redacted[key] = (
                _REDACTED
                if _sensitive_key(key)
                else _redact_value(raw_value, depth=depth + 1)
            )
        if len(value) > 256:
            redacted["_audit_entries_omitted"] = len(value) - 256
        return redacted

    if isinstance(value, (list, tuple)):
        items = [
            _redact_value(item, depth=depth + 1)
            for item in value[:256]
        ]
        if len(value) > 256:
            items.append(f"[OMITTED: {len(value) - 256} more audit items]")
        return items

    if value is None or isinstance(value, (bool, int, float)):
        return value

    if isinstance(value, str):
        if len(value) <= 4096:
            return value
        return value[:4096] + "[TRUNCATED]"

    if isinstance(value, bytes):
        return f"<bytes:{len(value)}>"

    return f"<{type(value).__name__}>"


def _metadata_json(
    metadata: Mapping[str, object] | None,
    *,
    maximum_bytes: int,
) -> str:
    safe = _redact_value(metadata or {})
    if not isinstance(safe, dict):
        safe = {"value": safe}
    serialized = json.dumps(
        safe,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    size = len(serialized.encode("utf-8"))
    if size <= maximum_bytes:
        return serialized
    return json.dumps(
        {
            "_audit_metadata_omitted": "size_limit",
            "original_bytes": size,
        },
        separators=(",", ":"),
        sort_keys=True,
    )


def _bounded_content(
    content: object | None,
    *,
    enabled: bool,
    maximum_bytes: int,
) -> str | None:
    if not enabled or content is None:
        return None
    if not isinstance(content, str):
        raise ValueError("audit conversation content must be a string")
    if len(content.encode("utf-8")) > maximum_bytes:
        return _OMITTED_CONTENT
    return content


def _timestamp(value: object | None) -> int:
    if value is None:
        return int(time.time())
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("audit timestamp must be an integer")
    if value < 0:
        raise ValueError("audit timestamp must be >= 0")
    return value


def _hash_payload(previous_hash: str, payload: Mapping[str, object]) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(
        (previous_hash + "\n" + canonical).encode("utf-8")
    ).hexdigest()


def _security_payload(
    *,
    organization_id: str,
    actor_user_id: str | None,
    event_type: str,
    occurred_at: int,
    metadata_json: str,
) -> dict[str, object]:
    return {
        "stream": AuditStream.SECURITY.value,
        "organization_id": organization_id,
        "actor_user_id": actor_user_id,
        "event_type": event_type,
        "occurred_at": occurred_at,
        "metadata_json": metadata_json,
    }


def _conversation_payload(
    *,
    organization_id: str,
    owner_user_id: str,
    actor_user_id: str | None,
    project_id: str | None,
    conversation_id: str | None,
    event_type: str,
    occurred_at: int,
    metadata_json: str,
    prompt_content: str | None,
    response_content: str | None,
) -> dict[str, object]:
    return {
        "stream": AuditStream.CONVERSATION.value,
        "organization_id": organization_id,
        "owner_user_id": owner_user_id,
        "actor_user_id": actor_user_id,
        "project_id": project_id,
        "conversation_id": conversation_id,
        "event_type": event_type,
        "occurred_at": occurred_at,
        "metadata_json": metadata_json,
        "prompt_content": prompt_content,
        "response_content": response_content,
    }


class AuditService:
    def __init__(
        self,
        database_path: Path | str,
        settings: AuditSettings | None = None,
    ) -> None:
        self.database_path = Path(database_path)
        self.settings = settings or AuditSettings()

    def _previous_hash(
        self,
        connection,
        organization_id: str,
        stream: AuditStream,
    ) -> str:
        row = connection.execute(
            """
            SELECT head_hash
            FROM audit_chain_heads
            WHERE organization_id = ? AND stream = ?
            """,
            (organization_id, stream.value),
        ).fetchone()
        if row is not None:
            return str(row[0])

        anchor = connection.execute(
            """
            SELECT anchor_hash
            FROM audit_chain_anchors
            WHERE organization_id = ? AND stream = ?
            """,
            (organization_id, stream.value),
        ).fetchone()
        return _ZERO_HASH if anchor is None else str(anchor[0])

    def _update_head(
        self,
        connection,
        *,
        organization_id: str,
        stream: AuditStream,
        event_hash: str,
        event_id: int | None,
        occurred_at: int,
    ) -> None:
        connection.execute(
            """
            INSERT INTO audit_chain_heads(
                organization_id, stream, head_hash, last_event_id, updated_at
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(organization_id, stream) DO UPDATE SET
                head_hash = excluded.head_hash,
                last_event_id = excluded.last_event_id,
                updated_at = excluded.updated_at
            """,
            (
                organization_id,
                stream.value,
                event_hash,
                event_id,
                occurred_at,
            ),
        )

    def record_security(
        self,
        event_type: str,
        *,
        organization_id: str,
        actor_user_id: str | None = None,
        metadata: Mapping[str, object] | None = None,
        occurred_at: int | None = None,
    ) -> int | None:
        if not self.settings.security_enabled:
            return None

        organization = _non_empty(
            organization_id,
            field="organization_id",
            maximum=128,
        )
        actor = _optional_identifier(
            actor_user_id,
            field="actor_user_id",
            maximum=128,
        )
        event = _non_empty(event_type, field="event_type", maximum=128)
        timestamp = _timestamp(occurred_at)
        metadata_json = _metadata_json(
            metadata,
            maximum_bytes=self.settings.max_metadata_bytes,
        )

        with connect(self.database_path) as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                previous_hash = self._previous_hash(
                    connection,
                    organization,
                    AuditStream.SECURITY,
                )
                payload = _security_payload(
                    organization_id=organization,
                    actor_user_id=actor,
                    event_type=event,
                    occurred_at=timestamp,
                    metadata_json=metadata_json,
                )
                event_hash = _hash_payload(previous_hash, payload)
                cursor = connection.execute(
                    """
                    INSERT INTO security_audit_events(
                        organization_id, actor_user_id, event_type,
                        occurred_at, metadata_json, previous_hash, event_hash
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        organization,
                        actor,
                        event,
                        timestamp,
                        metadata_json,
                        previous_hash,
                        event_hash,
                    ),
                )
                event_id = int(cursor.lastrowid)
                self._update_head(
                    connection,
                    organization_id=organization,
                    stream=AuditStream.SECURITY,
                    event_hash=event_hash,
                    event_id=event_id,
                    occurred_at=timestamp,
                )
                connection.commit()
                return event_id
            except Exception:
                connection.rollback()
                raise

    def record_admin_change(
        self,
        change_type: str,
        *,
        principal: Principal,
        target: str,
        before: object = None,
        after: object = None,
    ) -> int | None:
        require_permission(principal, Permission.ADMIN_MANAGE)
        return self.record_security(
            f"admin.{_non_empty(change_type, field='change_type', maximum=96)}",
            organization_id=principal.user.organization_id,
            actor_user_id=principal.user.id,
            metadata={
                "target": target,
                "before": before,
                "after": after,
            },
        )

    def record_conversation(
        self,
        event_type: str,
        *,
        organization_id: str,
        owner_user_id: str,
        actor_user_id: str | None = None,
        project_id: str | None = None,
        conversation_id: str | None = None,
        metadata: Mapping[str, object] | None = None,
        prompt_content: str | None = None,
        response_content: str | None = None,
        occurred_at: int | None = None,
    ) -> int | None:
        if not self.settings.conversation_enabled:
            return None

        organization = _non_empty(
            organization_id,
            field="organization_id",
            maximum=128,
        )
        owner = _non_empty(
            owner_user_id,
            field="owner_user_id",
            maximum=128,
        )
        actor = _optional_identifier(
            actor_user_id,
            field="actor_user_id",
            maximum=128,
        )
        project = _optional_identifier(
            project_id,
            field="project_id",
            maximum=128,
        )
        conversation = _optional_identifier(
            conversation_id,
            field="conversation_id",
            maximum=128,
        )
        event = _non_empty(event_type, field="event_type", maximum=128)
        timestamp = _timestamp(occurred_at)
        metadata_json = _metadata_json(
            metadata,
            maximum_bytes=self.settings.max_metadata_bytes,
        )
        prompt = _bounded_content(
            prompt_content,
            enabled=self.settings.store_prompt_content,
            maximum_bytes=self.settings.max_content_bytes,
        )
        response = _bounded_content(
            response_content,
            enabled=self.settings.store_response_content,
            maximum_bytes=self.settings.max_content_bytes,
        )

        with connect(self.database_path) as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                previous_hash = self._previous_hash(
                    connection,
                    organization,
                    AuditStream.CONVERSATION,
                )
                payload = _conversation_payload(
                    organization_id=organization,
                    owner_user_id=owner,
                    actor_user_id=actor,
                    project_id=project,
                    conversation_id=conversation,
                    event_type=event,
                    occurred_at=timestamp,
                    metadata_json=metadata_json,
                    prompt_content=prompt,
                    response_content=response,
                )
                event_hash = _hash_payload(previous_hash, payload)
                cursor = connection.execute(
                    """
                    INSERT INTO conversation_audit_events(
                        organization_id, owner_user_id, actor_user_id,
                        project_id, conversation_id, event_type,
                        occurred_at, metadata_json,
                        prompt_content, response_content,
                        previous_hash, event_hash
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        organization,
                        owner,
                        actor,
                        project,
                        conversation,
                        event,
                        timestamp,
                        metadata_json,
                        prompt,
                        response,
                        previous_hash,
                        event_hash,
                    ),
                )
                event_id = int(cursor.lastrowid)
                self._update_head(
                    connection,
                    organization_id=organization,
                    stream=AuditStream.CONVERSATION,
                    event_hash=event_hash,
                    event_id=event_id,
                    occurred_at=timestamp,
                )
                connection.commit()
                return event_id
            except Exception:
                connection.rollback()
                raise

    def _limit(self, limit: object) -> int:
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise ValueError("audit list limit must be an integer")
        if not 1 <= limit <= 1000:
            raise ValueError("audit list limit must be between 1 and 1000")
        return limit

    def list_security(
        self,
        principal: Principal,
        *,
        limit: int = 100,
    ) -> tuple[SecurityAuditEvent, ...]:
        require_permission(principal, Permission.SECURITY_AUDIT_READ)
        resolved_limit = self._limit(limit)
        with connect(self.database_path) as connection:
            rows = connection.execute(
                """
                SELECT id, organization_id, actor_user_id, event_type,
                       occurred_at, metadata_json, previous_hash, event_hash
                FROM security_audit_events
                WHERE organization_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (principal.user.organization_id, resolved_limit),
            ).fetchall()

        return tuple(
            SecurityAuditEvent(
                id=int(row[0]),
                organization_id=str(row[1]),
                actor_user_id=None if row[2] is None else str(row[2]),
                event_type=str(row[3]),
                occurred_at=int(row[4]),
                metadata=json.loads(str(row[5])),
                previous_hash=str(row[6]),
                event_hash=str(row[7]),
            )
            for row in rows
        )

    def list_conversation(
        self,
        principal: Principal,
        *,
        limit: int = 100,
    ) -> tuple[ConversationAuditEvent, ...]:
        require_permission(principal, Permission.CONVERSATION_AUDIT_READ)
        resolved_limit = self._limit(limit)
        with connect(self.database_path) as connection:
            rows = connection.execute(
                """
                SELECT id, organization_id, owner_user_id, actor_user_id,
                       project_id, conversation_id, event_type, occurred_at,
                       metadata_json, prompt_content, response_content,
                       previous_hash, event_hash
                FROM conversation_audit_events
                WHERE organization_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (principal.user.organization_id, resolved_limit),
            ).fetchall()

        return tuple(
            ConversationAuditEvent(
                id=int(row[0]),
                organization_id=str(row[1]),
                owner_user_id=str(row[2]),
                actor_user_id=None if row[3] is None else str(row[3]),
                project_id=None if row[4] is None else str(row[4]),
                conversation_id=None if row[5] is None else str(row[5]),
                event_type=str(row[6]),
                occurred_at=int(row[7]),
                metadata=json.loads(str(row[8])),
                prompt_content=None if row[9] is None else str(row[9]),
                response_content=None if row[10] is None else str(row[10]),
                previous_hash=str(row[11]),
                event_hash=str(row[12]),
            )
            for row in rows
        )

    def _anchor_hash(
        self,
        connection,
        organization_id: str,
        stream: AuditStream,
    ) -> str:
        row = connection.execute(
            """
            SELECT anchor_hash
            FROM audit_chain_anchors
            WHERE organization_id = ? AND stream = ?
            """,
            (organization_id, stream.value),
        ).fetchone()
        return _ZERO_HASH if row is None else str(row[0])

    def verify_chain(
        self,
        organization_id: str,
        stream: AuditStream | str,
    ) -> bool:
        organization = _non_empty(
            organization_id,
            field="organization_id",
            maximum=128,
        )
        resolved_stream = AuditStream(stream)

        with connect(self.database_path) as connection:
            current_hash = self._anchor_hash(
                connection,
                organization,
                resolved_stream,
            )

            if resolved_stream is AuditStream.SECURITY:
                rows = connection.execute(
                    """
                    SELECT actor_user_id, event_type, occurred_at,
                           metadata_json, previous_hash, event_hash
                    FROM security_audit_events
                    WHERE organization_id = ?
                    ORDER BY id
                    """,
                    (organization,),
                ).fetchall()
                for row in rows:
                    payload = _security_payload(
                        organization_id=organization,
                        actor_user_id=None if row[0] is None else str(row[0]),
                        event_type=str(row[1]),
                        occurred_at=int(row[2]),
                        metadata_json=str(row[3]),
                    )
                    if str(row[4]) != current_hash:
                        return False
                    expected = _hash_payload(current_hash, payload)
                    if not hmac.compare_digest(
                        expected.encode("ascii"),
                        str(row[5]).encode("ascii"),
                    ):
                        return False
                    current_hash = expected
            else:
                rows = connection.execute(
                    """
                    SELECT owner_user_id, actor_user_id, project_id,
                           conversation_id, event_type, occurred_at,
                           metadata_json, prompt_content, response_content,
                           previous_hash, event_hash
                    FROM conversation_audit_events
                    WHERE organization_id = ?
                    ORDER BY id
                    """,
                    (organization,),
                ).fetchall()
                for row in rows:
                    payload = _conversation_payload(
                        organization_id=organization,
                        owner_user_id=str(row[0]),
                        actor_user_id=None if row[1] is None else str(row[1]),
                        project_id=None if row[2] is None else str(row[2]),
                        conversation_id=None if row[3] is None else str(row[3]),
                        event_type=str(row[4]),
                        occurred_at=int(row[5]),
                        metadata_json=str(row[6]),
                        prompt_content=None if row[7] is None else str(row[7]),
                        response_content=None if row[8] is None else str(row[8]),
                    )
                    if str(row[9]) != current_hash:
                        return False
                    expected = _hash_payload(current_hash, payload)
                    if not hmac.compare_digest(
                        expected.encode("ascii"),
                        str(row[10]).encode("ascii"),
                    ):
                        return False
                    current_hash = expected

            head = connection.execute(
                """
                SELECT head_hash
                FROM audit_chain_heads
                WHERE organization_id = ? AND stream = ?
                """,
                (organization, resolved_stream.value),
            ).fetchone()
            if head is None:
                return not rows and current_hash == _ZERO_HASH
            return str(head[0]) == current_hash

    def _purge_stream_prefix(
        self,
        connection,
        *,
        organization_id: str,
        stream: AuditStream,
        cutoff: int,
        now: int,
    ) -> int:
        table = (
            "security_audit_events"
            if stream is AuditStream.SECURITY
            else "conversation_audit_events"
        )
        rows = connection.execute(
            f"""
            SELECT id, occurred_at, event_hash
            FROM {table}
            WHERE organization_id = ?
            ORDER BY id
            """,
            (organization_id,),
        ).fetchall()

        last_id: int | None = None
        last_hash: str | None = None
        deleted = 0
        for raw_id, raw_time, raw_hash in rows:
            if int(raw_time) >= cutoff:
                break
            last_id = int(raw_id)
            last_hash = str(raw_hash)
            deleted += 1

        if last_id is None or last_hash is None:
            return 0

        connection.execute(
            f"DELETE FROM {table} WHERE organization_id = ? AND id <= ?",
            (organization_id, last_id),
        )
        connection.execute(
            """
            INSERT INTO audit_chain_anchors(
                organization_id, stream, anchor_hash, updated_at
            )
            VALUES (?, ?, ?, ?)
            ON CONFLICT(organization_id, stream) DO UPDATE SET
                anchor_hash = excluded.anchor_hash,
                updated_at = excluded.updated_at
            """,
            (organization_id, stream.value, last_hash, now),
        )

        remaining = connection.execute(
            f"""
            SELECT id, event_hash
            FROM {table}
            WHERE organization_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (organization_id,),
        ).fetchone()
        if remaining is None:
            self._update_head(
                connection,
                organization_id=organization_id,
                stream=stream,
                event_hash=last_hash,
                event_id=None,
                occurred_at=now,
            )
        return deleted

    def purge_expired(self, *, now: int | None = None) -> int:
        if self.settings.retention_days == 0:
            return 0

        timestamp = _timestamp(now)
        cutoff = timestamp - self.settings.retention_days * 24 * 60 * 60

        with connect(self.database_path) as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                organizations = {
                    str(row[0])
                    for row in connection.execute(
                        """
                        SELECT organization_id FROM security_audit_events
                        UNION
                        SELECT organization_id FROM conversation_audit_events
                        """
                    ).fetchall()
                }
                deleted = 0
                for organization_id in organizations:
                    deleted += self._purge_stream_prefix(
                        connection,
                        organization_id=organization_id,
                        stream=AuditStream.SECURITY,
                        cutoff=cutoff,
                        now=timestamp,
                    )
                    deleted += self._purge_stream_prefix(
                        connection,
                        organization_id=organization_id,
                        stream=AuditStream.CONVERSATION,
                        cutoff=cutoff,
                        now=timestamp,
                    )
                connection.commit()
                return deleted
            except Exception:
                connection.rollback()
                raise
