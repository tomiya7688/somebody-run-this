from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import json
from pathlib import Path
import re
import sqlite3
import time
import uuid
from typing import Iterable

from .identity import Permission, Principal, require_permission
from .inference import InferenceCapabilities
from .policy_engine import PolicyCapabilities, PolicyEngine, PolicyLayer
from .storage import connect


_MODEL_KEY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_BACKEND_KEY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SHA256_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


class ModelRegistryError(ValueError):
    """Raised when model registry metadata or policy is invalid."""


class ModelAccessDenied(PermissionError):
    """Raised when a model is not available to the authenticated principal."""


class ModelNotFound(LookupError):
    """Raised when a model is not present in the caller's organization."""


class ModelSourceKind(StrEnum):
    LOCAL = "local"
    EXTERNAL = "external"


class ModelHealthState(StrEnum):
    UNKNOWN = "unknown"
    READY = "ready"
    UNHEALTHY = "unhealthy"


class ModelPolicyScopeType(StrEnum):
    ORGANIZATION = "organization"
    GROUP = "group"
    PROJECT = "project"


@dataclass(frozen=True)
class ModelCapabilities:
    text: bool = True
    streaming: bool = True
    vision: bool = False
    tool_calling: bool = False
    context_limit: int | None = None

    def __post_init__(self) -> None:
        for name in ("text", "streaming", "vision", "tool_calling"):
            if not isinstance(getattr(self, name), bool):
                raise ModelRegistryError(f"{name} capability must be boolean")
        if self.context_limit is not None:
            if (
                isinstance(self.context_limit, bool)
                or not isinstance(self.context_limit, int)
                or not 1 <= self.context_limit <= 1_048_576
            ):
                raise ModelRegistryError(
                    "context_limit must be between 1 and 1048576"
                )

    def to_json(self) -> str:
        return json.dumps(
            {
                "text": self.text,
                "streaming": self.streaming,
                "vision": self.vision,
                "tool_calling": self.tool_calling,
            },
            separators=(",", ":"),
            sort_keys=True,
        )

    @classmethod
    def from_json(
        cls,
        raw: str,
        *,
        context_limit: int | None,
    ) -> "ModelCapabilities":
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ModelRegistryError("stored model capabilities are invalid") from exc
        if not isinstance(payload, dict):
            raise ModelRegistryError("stored model capabilities must be an object")
        return cls(
            text=payload.get("text", False),
            streaming=payload.get("streaming", False),
            vision=payload.get("vision", False),
            tool_calling=payload.get("tool_calling", False),
            context_limit=context_limit,
        )

    def to_inference_capabilities(self) -> InferenceCapabilities:
        return InferenceCapabilities(
            text=self.text,
            streaming=self.streaming,
            vision=self.vision,
            tool_calling=self.tool_calling,
            max_context_tokens=self.context_limit,
        )

    def to_policy_capabilities(self) -> PolicyCapabilities:
        maximums: dict[str, int] = {}
        if self.context_limit is not None:
            maximums["context_tokens"] = self.context_limit
        return PolicyCapabilities(
            features={
                "text": self.text,
                "streaming": self.streaming,
                "vision": self.vision,
                "tool_calling": self.tool_calling,
            },
            integer_maximums=maximums,
        )


@dataclass(frozen=True)
class ModelRecord:
    id: str
    organization_id: str
    model_key: str
    display_name: str
    source_kind: ModelSourceKind
    backend_id: str
    backend_model_id: str
    local_path: Path | None
    revision: str | None
    digest: str | None
    enabled: bool
    capabilities: ModelCapabilities
    health_state: ModelHealthState
    health_detail: str
    last_health_at: int | None


@dataclass(frozen=True)
class UserModelView:
    model_id: str
    display_name: str
    capabilities: ModelCapabilities


@dataclass(frozen=True)
class ModelPolicyScope:
    organization_id: str
    scope_type: ModelPolicyScopeType
    scope_id: str
    revision: int
    allowed_model_ids: frozenset[str]
    default_model_id: str | None


def _non_empty(
    value: object,
    *,
    field: str,
    maximum: int,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ModelRegistryError(f"{field} must be a non-empty string")
    normalized = value.strip()
    if len(normalized) > maximum:
        raise ModelRegistryError(f"{field} is too long")
    if any(ord(character) < 32 or ord(character) == 127 for character in normalized):
        raise ModelRegistryError(f"{field} contains control characters")
    return normalized


def _model_key(value: object) -> str:
    normalized = _non_empty(value, field="model_id", maximum=128)
    if not _MODEL_KEY_PATTERN.fullmatch(normalized):
        raise ModelRegistryError("model_id contains unsupported characters")
    return normalized


def _backend_key(value: object) -> str:
    normalized = _non_empty(value, field="backend_id", maximum=128)
    if not _BACKEND_KEY_PATTERN.fullmatch(normalized):
        raise ModelRegistryError("backend_id contains unsupported characters")
    return normalized


def _backend_model_id(value: object) -> str:
    return _non_empty(value, field="backend_model_id", maximum=512)


def _display_name(value: object) -> str:
    return _non_empty(value, field="display_name", maximum=256)


def _optional_text(
    value: object | None,
    *,
    field: str,
    maximum: int,
) -> str | None:
    if value is None:
        return None
    return _non_empty(value, field=field, maximum=maximum)


def _digest(value: object | None) -> str | None:
    if value is None:
        return None
    normalized = _non_empty(value, field="digest", maximum=80).casefold()
    if not _SHA256_PATTERN.fullmatch(normalized):
        raise ModelRegistryError(
            "digest must use the form sha256:<64 lowercase hex characters>"
        )
    return normalized


def _model_path(
    source_kind: ModelSourceKind,
    value: Path | str | None,
) -> Path | None:
    if source_kind is ModelSourceKind.EXTERNAL:
        if value is not None:
            raise ModelRegistryError(
                "external provider models cannot have a local_path"
            )
        return None

    if value is None:
        raise ModelRegistryError("local models require local_path")
    path = Path(value)
    if not path.is_absolute():
        raise ModelRegistryError("local_path must be absolute")
    return path


def _health_detail(value: object) -> str:
    if not isinstance(value, str):
        raise ModelRegistryError("health_detail must be a string")
    if len(value) > 1024:
        raise ModelRegistryError("health_detail is too long")
    if any(ord(character) == 0 for character in value):
        raise ModelRegistryError("health_detail contains NUL")
    return value


def _scope_id(value: object) -> str:
    return _non_empty(value, field="scope_id", maximum=128)


def _model_id_set(values: Iterable[str]) -> frozenset[str]:
    if isinstance(values, (str, bytes)):
        raise ModelRegistryError("allowed models must be a collection")
    result = {_model_key(value) for value in values}
    if len(result) > 4096:
        raise ModelRegistryError("too many models in allowlist")
    return frozenset(result)


class ModelRegistry:
    def __init__(
        self,
        database_path: Path | str,
        *,
        policy_engine: PolicyEngine | None = None,
    ) -> None:
        self.database_path = Path(database_path)
        self.policy_engine = policy_engine or PolicyEngine()

    def _require_manage(self, principal: Principal) -> None:
        require_permission(principal, Permission.MODEL_MANAGE)

    def _record_from_row(self, row: tuple[object, ...]) -> ModelRecord:
        local_path = None if row[7] is None else Path(str(row[7]))
        context_limit = None if row[13] is None else int(row[13])
        return ModelRecord(
            id=str(row[0]),
            organization_id=str(row[1]),
            model_key=str(row[2]),
            display_name=str(row[3]),
            source_kind=ModelSourceKind(str(row[4])),
            backend_id=str(row[5]),
            backend_model_id=str(row[6]),
            local_path=local_path,
            revision=None if row[8] is None else str(row[8]),
            digest=None if row[9] is None else str(row[9]),
            enabled=bool(row[10]),
            capabilities=ModelCapabilities.from_json(
                str(row[12]),
                context_limit=context_limit,
            ),
            health_state=ModelHealthState(str(row[14])),
            health_detail=str(row[15]),
            last_health_at=None if row[16] is None else int(row[16]),
        )

    @staticmethod
    def _model_select_sql() -> str:
        return """
            SELECT id, organization_id, model_key, display_name,
                   source_kind, backend_id, backend_model_id, local_path,
                   revision, digest, enabled, updated_at,
                   capabilities_json, context_limit, health_state,
                   health_detail, last_health_at
            FROM models
        """

    def register_model(
        self,
        principal: Principal,
        *,
        model_id: str,
        display_name: str,
        source_kind: ModelSourceKind | str,
        backend_id: str,
        backend_model_id: str,
        capabilities: ModelCapabilities,
        local_path: Path | str | None = None,
        revision: str | None = None,
        digest: str | None = None,
        enabled: bool = False,
    ) -> ModelRecord:
        self._require_manage(principal)
        if not isinstance(capabilities, ModelCapabilities):
            raise ModelRegistryError("capabilities must be ModelCapabilities")
        if not isinstance(enabled, bool):
            raise ModelRegistryError("enabled must be boolean")

        kind = ModelSourceKind(source_kind)
        key = _model_key(model_id)
        display = _display_name(display_name)
        backend = _backend_key(backend_id)
        backend_model = _backend_model_id(backend_model_id)
        resolved_path = _model_path(kind, local_path)
        resolved_revision = _optional_text(
            revision,
            field="revision",
            maximum=256,
        )
        resolved_digest = _digest(digest)
        now = int(time.time())
        internal_id = str(uuid.uuid4())

        try:
            with connect(self.database_path) as connection:
                connection.execute(
                    """
                    INSERT INTO models(
                        id, organization_id, model_key, display_name,
                        source_kind, backend_id, backend_model_id, local_path,
                        revision, digest, enabled, capabilities_json,
                        context_limit, health_state, health_detail,
                        last_health_at, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        internal_id,
                        principal.user.organization_id,
                        key,
                        display,
                        kind.value,
                        backend,
                        backend_model,
                        None if resolved_path is None else str(resolved_path),
                        resolved_revision,
                        resolved_digest,
                        1 if enabled else 0,
                        capabilities.to_json(),
                        capabilities.context_limit,
                        ModelHealthState.UNKNOWN.value,
                        "",
                        None,
                        now,
                        now,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ModelRegistryError(
                "model_id or backend model is already registered"
            ) from exc

        record = self.get_model(
            principal.user.organization_id,
            key,
        )
        if record is None:
            raise RuntimeError("registered model could not be reloaded")
        return record

    def get_model(
        self,
        organization_id: str,
        model_id: str,
    ) -> ModelRecord | None:
        key = _model_key(model_id)
        with connect(self.database_path) as connection:
            row = connection.execute(
                self._model_select_sql()
                + " WHERE organization_id = ? AND model_key = ?",
                (organization_id, key),
            ).fetchone()
        return None if row is None else self._record_from_row(row)

    def list_catalog(self, principal: Principal) -> tuple[ModelRecord, ...]:
        self._require_manage(principal)
        with connect(self.database_path) as connection:
            rows = connection.execute(
                self._model_select_sql()
                + " WHERE organization_id = ? ORDER BY model_key COLLATE NOCASE",
                (principal.user.organization_id,),
            ).fetchall()
        return tuple(self._record_from_row(row) for row in rows)

    def set_enabled(
        self,
        principal: Principal,
        model_id: str,
        enabled: bool,
    ) -> ModelRecord:
        self._require_manage(principal)
        if not isinstance(enabled, bool):
            raise ModelRegistryError("enabled must be boolean")
        key = _model_key(model_id)
        with connect(self.database_path) as connection:
            cursor = connection.execute(
                """
                UPDATE models
                SET enabled = ?, updated_at = ?
                WHERE organization_id = ? AND model_key = ?
                """,
                (
                    1 if enabled else 0,
                    int(time.time()),
                    principal.user.organization_id,
                    key,
                ),
            )
            if cursor.rowcount != 1:
                raise ModelNotFound("model is not registered")
        record = self.get_model(principal.user.organization_id, key)
        if record is None:
            raise RuntimeError("updated model could not be reloaded")
        return record

    def update_health(
        self,
        organization_id: str,
        model_id: str,
        *,
        state: ModelHealthState | str,
        detail: str = "",
        capabilities: ModelCapabilities | None = None,
        occurred_at: int | None = None,
    ) -> ModelRecord:
        key = _model_key(model_id)
        health = ModelHealthState(state)
        health_detail = _health_detail(detail)
        timestamp = int(time.time()) if occurred_at is None else occurred_at
        if isinstance(timestamp, bool) or not isinstance(timestamp, int):
            raise ModelRegistryError("health timestamp must be an integer")
        if timestamp < 0:
            raise ModelRegistryError("health timestamp must be >= 0")
        if capabilities is not None and not isinstance(
            capabilities, ModelCapabilities
        ):
            raise ModelRegistryError("capabilities must be ModelCapabilities")

        with connect(self.database_path) as connection:
            if capabilities is None:
                cursor = connection.execute(
                    """
                    UPDATE models
                    SET health_state = ?, health_detail = ?,
                        last_health_at = ?, updated_at = ?
                    WHERE organization_id = ? AND model_key = ?
                    """,
                    (
                        health.value,
                        health_detail,
                        timestamp,
                        timestamp,
                        organization_id,
                        key,
                    ),
                )
            else:
                cursor = connection.execute(
                    """
                    UPDATE models
                    SET health_state = ?, health_detail = ?,
                        last_health_at = ?, updated_at = ?,
                        capabilities_json = ?, context_limit = ?
                    WHERE organization_id = ? AND model_key = ?
                    """,
                    (
                        health.value,
                        health_detail,
                        timestamp,
                        timestamp,
                        capabilities.to_json(),
                        capabilities.context_limit,
                        organization_id,
                        key,
                    ),
                )
            if cursor.rowcount != 1:
                raise ModelNotFound("model is not registered")

        record = self.get_model(organization_id, key)
        if record is None:
            raise RuntimeError("health-updated model could not be reloaded")
        return record

    def _validate_scope(
        self,
        connection,
        principal: Principal,
        scope_type: ModelPolicyScopeType,
        scope_id: str,
    ) -> str:
        organization_id = principal.user.organization_id
        resolved_scope = _scope_id(scope_id)

        if scope_type is ModelPolicyScopeType.ORGANIZATION:
            if resolved_scope != organization_id:
                raise ModelRegistryError(
                    "organization scope_id must match the principal organization"
                )
            return resolved_scope

        if scope_type is ModelPolicyScopeType.GROUP:
            row = connection.execute(
                """
                SELECT organization_id
                FROM groups
                WHERE id = ?
                """,
                (resolved_scope,),
            ).fetchone()
            if row is None:
                raise ModelRegistryError("group scope does not exist")
            if str(row[0]) != organization_id:
                raise ModelRegistryError(
                    "group scope belongs to another organization"
                )
            return resolved_scope

        # Project persistence is introduced by #32. At this stage a project
        # scope can be preconfigured by an administrator, but a user-supplied
        # project id must never be trusted as membership proof by callers.
        return resolved_scope

    def configure_allowlist(
        self,
        principal: Principal,
        *,
        scope_type: ModelPolicyScopeType | str,
        scope_id: str,
        allowed_model_ids: Iterable[str],
        default_model_id: str | None = None,
    ) -> ModelPolicyScope:
        self._require_manage(principal)
        resolved_type = ModelPolicyScopeType(scope_type)
        allowed = _model_id_set(allowed_model_ids)
        default_model = (
            None if default_model_id is None else _model_key(default_model_id)
        )
        if default_model is not None and default_model not in allowed:
            raise ModelRegistryError(
                "default model must be present in the same scope allowlist"
            )

        organization_id = principal.user.organization_id
        now = int(time.time())

        with connect(self.database_path) as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                resolved_scope_id = self._validate_scope(
                    connection,
                    principal,
                    resolved_type,
                    scope_id,
                )

                if allowed:
                    placeholders = ",".join("?" for _value in allowed)
                    rows = connection.execute(
                        f"""
                        SELECT model_key
                        FROM models
                        WHERE organization_id = ?
                          AND model_key IN ({placeholders})
                        """,
                        (organization_id, *sorted(allowed)),
                    ).fetchall()
                    existing = {str(row[0]).casefold() for row in rows}
                    missing = {
                        value for value in allowed if value.casefold() not in existing
                    }
                    if missing:
                        raise ModelRegistryError(
                            "allowlist contains unregistered models: "
                            + ", ".join(sorted(missing))
                        )

                row = connection.execute(
                    """
                    SELECT revision
                    FROM model_policy_scopes
                    WHERE organization_id = ?
                      AND scope_type = ?
                      AND scope_id = ?
                    """,
                    (
                        organization_id,
                        resolved_type.value,
                        resolved_scope_id,
                    ),
                ).fetchone()
                revision = 1 if row is None else int(row[0]) + 1

                connection.execute(
                    """
                    INSERT INTO model_policy_scopes(
                        organization_id, scope_type, scope_id,
                        revision, default_model_key, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(organization_id, scope_type, scope_id)
                    DO UPDATE SET
                        revision = excluded.revision,
                        default_model_key = excluded.default_model_key,
                        updated_at = excluded.updated_at
                    """,
                    (
                        organization_id,
                        resolved_type.value,
                        resolved_scope_id,
                        revision,
                        default_model,
                        now,
                    ),
                )
                connection.execute(
                    """
                    DELETE FROM model_policy_allowed_models
                    WHERE organization_id = ?
                      AND scope_type = ?
                      AND scope_id = ?
                    """,
                    (
                        organization_id,
                        resolved_type.value,
                        resolved_scope_id,
                    ),
                )
                connection.executemany(
                    """
                    INSERT INTO model_policy_allowed_models(
                        organization_id, scope_type, scope_id, model_key
                    )
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        (
                            organization_id,
                            resolved_type.value,
                            resolved_scope_id,
                            model_key,
                        )
                        for model_key in sorted(allowed)
                    ),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise

        scope = self.get_policy_scope(
            organization_id,
            resolved_type,
            resolved_scope_id,
        )
        if scope is None:
            raise RuntimeError("model policy scope could not be reloaded")
        return scope

    def get_policy_scope(
        self,
        organization_id: str,
        scope_type: ModelPolicyScopeType | str,
        scope_id: str,
    ) -> ModelPolicyScope | None:
        resolved_type = ModelPolicyScopeType(scope_type)
        resolved_scope = _scope_id(scope_id)
        with connect(self.database_path) as connection:
            row = connection.execute(
                """
                SELECT revision, default_model_key
                FROM model_policy_scopes
                WHERE organization_id = ?
                  AND scope_type = ?
                  AND scope_id = ?
                """,
                (
                    organization_id,
                    resolved_type.value,
                    resolved_scope,
                ),
            ).fetchone()
            if row is None:
                return None
            allowed_rows = connection.execute(
                """
                SELECT model_key
                FROM model_policy_allowed_models
                WHERE organization_id = ?
                  AND scope_type = ?
                  AND scope_id = ?
                ORDER BY model_key COLLATE NOCASE
                """,
                (
                    organization_id,
                    resolved_type.value,
                    resolved_scope,
                ),
            ).fetchall()

        return ModelPolicyScope(
            organization_id=organization_id,
            scope_type=resolved_type,
            scope_id=resolved_scope,
            revision=int(row[0]),
            allowed_model_ids=frozenset(str(item[0]) for item in allowed_rows),
            default_model_id=None if row[1] is None else str(row[1]),
        )

    def _available_records(
        self,
        organization_id: str,
    ) -> tuple[ModelRecord, ...]:
        with connect(self.database_path) as connection:
            rows = connection.execute(
                self._model_select_sql()
                + """
                  WHERE organization_id = ?
                    AND enabled = 1
                    AND health_state = ?
                  ORDER BY model_key COLLATE NOCASE
                """,
                (
                    organization_id,
                    ModelHealthState.READY.value,
                ),
            ).fetchall()
        return tuple(self._record_from_row(row) for row in rows)

    def _policy_layers(
        self,
        principal: Principal,
        *,
        project_id: str | None,
    ) -> tuple[PolicyLayer, ...]:
        organization_id = principal.user.organization_id
        layers: list[PolicyLayer] = []

        organization_scope = self.get_policy_scope(
            organization_id,
            ModelPolicyScopeType.ORGANIZATION,
            organization_id,
        )
        if organization_scope is None:
            layers.append(
                PolicyLayer(
                    name="organization",
                    revision=0,
                    allowed_values={},
                )
            )
        else:
            layers.append(
                PolicyLayer(
                    name="organization",
                    revision=organization_scope.revision,
                    allowed_values={
                        "model": organization_scope.allowed_model_ids
                    },
                )
            )

        for group_id in sorted(principal.group_ids):
            scope = self.get_policy_scope(
                organization_id,
                ModelPolicyScopeType.GROUP,
                group_id,
            )
            if scope is None:
                continue
            layers.append(
                PolicyLayer(
                    name=f"group:{group_id}",
                    revision=scope.revision,
                    allowed_values={"model": scope.allowed_model_ids},
                )
            )

        if project_id is not None:
            scope = self.get_policy_scope(
                organization_id,
                ModelPolicyScopeType.PROJECT,
                _scope_id(project_id),
            )
            if scope is not None:
                layers.append(
                    PolicyLayer(
                        name=f"project:{scope.scope_id}",
                        revision=scope.revision,
                        allowed_values={"model": scope.allowed_model_ids},
                    )
                )

        return tuple(layers)

    def list_effective_models(
        self,
        principal: Principal,
        *,
        project_id: str | None = None,
    ) -> tuple[UserModelView, ...]:
        records = self._available_records(principal.user.organization_id)
        available = {record.model_key for record in records}
        layers = self._policy_layers(
            principal,
            project_id=project_id,
        )

        visible: list[UserModelView] = []
        for record in records:
            decision = self.policy_engine.resolve_choice(
                "model",
                record.model_key,
                layers,
                available_values=available,
            )
            if not decision.permitted:
                continue
            visible.append(
                UserModelView(
                    model_id=record.model_key,
                    display_name=record.display_name,
                    capabilities=record.capabilities,
                )
            )
        return tuple(visible)

    def require_allowed_model(
        self,
        principal: Principal,
        model_id: str,
        *,
        project_id: str | None = None,
    ) -> ModelRecord:
        key = _model_key(model_id)
        record = self.get_model(principal.user.organization_id, key)
        if record is None:
            raise ModelAccessDenied("model is not available")
        if not record.enabled or record.health_state is not ModelHealthState.READY:
            raise ModelAccessDenied("model is not available")

        available_records = self._available_records(principal.user.organization_id)
        available = {item.model_key for item in available_records}
        layers = self._policy_layers(
            principal,
            project_id=project_id,
        )
        decision = self.policy_engine.resolve_choice(
            "model",
            record.model_key,
            layers,
            available_values=available,
        )
        if not decision.permitted:
            raise ModelAccessDenied("model is not available")
        return record

    def resolve_default_model(
        self,
        principal: Principal,
        *,
        project_id: str | None = None,
    ) -> ModelRecord | None:
        visible = self.list_effective_models(
            principal,
            project_id=project_id,
        )
        allowed = {model.model_id for model in visible}
        if not allowed:
            return None

        organization_id = principal.user.organization_id

        if project_id is not None:
            project_scope = self.get_policy_scope(
                organization_id,
                ModelPolicyScopeType.PROJECT,
                _scope_id(project_id),
            )
            if (
                project_scope is not None
                and project_scope.default_model_id in allowed
            ):
                return self.get_model(
                    organization_id,
                    project_scope.default_model_id,
                )

        group_defaults = {
            scope.default_model_id
            for group_id in principal.group_ids
            if (
                scope := self.get_policy_scope(
                    organization_id,
                    ModelPolicyScopeType.GROUP,
                    group_id,
                )
            )
            is not None
            and scope.default_model_id is not None
            and scope.default_model_id in allowed
        }
        if len(group_defaults) == 1:
            return self.get_model(
                organization_id,
                next(iter(group_defaults)),
            )

        organization_scope = self.get_policy_scope(
            organization_id,
            ModelPolicyScopeType.ORGANIZATION,
            organization_id,
        )
        if (
            organization_scope is not None
            and organization_scope.default_model_id in allowed
        ):
            return self.get_model(
                organization_id,
                organization_scope.default_model_id,
            )

        if len(allowed) == 1:
            return self.get_model(
                organization_id,
                next(iter(allowed)),
            )
        return None

    def policy_capabilities_for_model(
        self,
        principal: Principal,
        model_id: str,
        *,
        project_id: str | None = None,
    ) -> PolicyCapabilities:
        record = self.require_allowed_model(
            principal,
            model_id,
            project_id=project_id,
        )
        return record.capabilities.to_policy_capabilities()
