from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
import os
import tomllib


class ConfigError(ValueError):
    """Raised when service configuration is invalid."""


@dataclass(frozen=True)
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 8787
    request_timeout_seconds: int = 10
    max_connections: int = 64


@dataclass(frozen=True)
class StorageConfig:
    sqlite_path: Path = Path("./data/private_ai_hub.sqlite3")


@dataclass(frozen=True)
class AuthConfig:
    session_ttl_seconds: int = 12 * 60 * 60
    login_attempts_per_minute: int = 10


@dataclass(frozen=True)
class AuditConfig:
    security_enabled: bool = True
    conversation_enabled: bool = False
    store_prompt_content: bool = False
    store_response_content: bool = False
    retention_days: int = 180
    max_metadata_bytes: int = 16 * 1024
    max_content_bytes: int = 1024 * 1024


@dataclass(frozen=True)
class AppConfig:
    server: ServerConfig = ServerConfig()
    storage: StorageConfig = StorageConfig()
    auth: AuthConfig = AuthConfig()
    audit: AuditConfig = AuditConfig()


def _read_toml(path: Path | None) -> dict:
    if path is None:
        return {}
    if not path.exists():
        raise ConfigError(f"config file does not exist: {path}")
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"invalid TOML in {path}: {exc}") from exc
    except OSError as exc:
        raise ConfigError(f"cannot read config file {path}: {exc}") from exc


def _as_int(value: object, *, field: str) -> int:
    if isinstance(value, bool):
        raise ConfigError(f"{field} must be an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value.strip(), 10)
        except ValueError as exc:
            raise ConfigError(f"{field} must be an integer") from exc
    raise ConfigError(f"{field} must be an integer")


def _as_bool(value: object, *, field: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    raise ConfigError(f"{field} must be a boolean")


def _bounded_int(
    value: object,
    *,
    field: str,
    minimum: int,
    maximum: int,
) -> int:
    resolved = _as_int(value, field=field)
    if not minimum <= resolved <= maximum:
        raise ConfigError(
            f"{field} must be between {minimum} and {maximum}"
        )
    return resolved


def load_config(
    path: Path | str | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> AppConfig:
    env_map = os.environ if env is None else env
    config_path = Path(path) if path is not None else None
    raw = _read_toml(config_path)

    server_raw = raw.get("server", {})
    storage_raw = raw.get("storage", {})
    auth_raw = raw.get("auth", {})
    audit_raw = raw.get("audit", {})
    for section_name, section in (
        ("server", server_raw),
        ("storage", storage_raw),
        ("auth", auth_raw),
        ("audit", audit_raw),
    ):
        if not isinstance(section, dict):
            raise ConfigError(f"[{section_name}] must be a table")

    host = env_map.get("PRIVATE_AI_HOST", server_raw.get("host", "127.0.0.1"))
    port_raw = env_map.get("PRIVATE_AI_PORT", server_raw.get("port", 8787))
    timeout_raw = env_map.get(
        "PRIVATE_AI_REQUEST_TIMEOUT_SECONDS",
        server_raw.get("request_timeout_seconds", 10),
    )
    max_connections_raw = env_map.get(
        "PRIVATE_AI_MAX_CONNECTIONS",
        server_raw.get("max_connections", 64),
    )
    sqlite_path_raw = env_map.get(
        "PRIVATE_AI_SQLITE_PATH",
        storage_raw.get("sqlite_path", "./data/private_ai_hub.sqlite3"),
    )
    session_ttl_raw = env_map.get(
        "PRIVATE_AI_SESSION_TTL_SECONDS",
        auth_raw.get("session_ttl_seconds", 12 * 60 * 60),
    )
    login_attempts_raw = env_map.get(
        "PRIVATE_AI_LOGIN_ATTEMPTS_PER_MINUTE",
        auth_raw.get("login_attempts_per_minute", 10),
    )

    security_enabled_raw = env_map.get(
        "PRIVATE_AI_AUDIT_SECURITY_ENABLED",
        audit_raw.get("security_enabled", True),
    )
    conversation_enabled_raw = env_map.get(
        "PRIVATE_AI_AUDIT_CONVERSATION_ENABLED",
        audit_raw.get("conversation_enabled", False),
    )
    store_prompt_raw = env_map.get(
        "PRIVATE_AI_AUDIT_STORE_PROMPT_CONTENT",
        audit_raw.get("store_prompt_content", False),
    )
    store_response_raw = env_map.get(
        "PRIVATE_AI_AUDIT_STORE_RESPONSE_CONTENT",
        audit_raw.get("store_response_content", False),
    )
    retention_raw = env_map.get(
        "PRIVATE_AI_AUDIT_RETENTION_DAYS",
        audit_raw.get("retention_days", 180),
    )
    metadata_bytes_raw = env_map.get(
        "PRIVATE_AI_AUDIT_MAX_METADATA_BYTES",
        audit_raw.get("max_metadata_bytes", 16 * 1024),
    )
    content_bytes_raw = env_map.get(
        "PRIVATE_AI_AUDIT_MAX_CONTENT_BYTES",
        audit_raw.get("max_content_bytes", 1024 * 1024),
    )

    if not isinstance(host, str) or not host.strip():
        raise ConfigError("server.host must be a non-empty string")

    port = _bounded_int(
        port_raw,
        field="server.port",
        minimum=1,
        maximum=65535,
    )
    request_timeout_seconds = _bounded_int(
        timeout_raw,
        field="server.request_timeout_seconds",
        minimum=1,
        maximum=3600,
    )
    max_connections = _bounded_int(
        max_connections_raw,
        field="server.max_connections",
        minimum=1,
        maximum=4096,
    )

    if (
        not isinstance(sqlite_path_raw, (str, os.PathLike))
        or not str(sqlite_path_raw).strip()
    ):
        raise ConfigError("storage.sqlite_path must be a non-empty path")

    session_ttl_seconds = _bounded_int(
        session_ttl_raw,
        field="auth.session_ttl_seconds",
        minimum=300,
        maximum=31 * 24 * 60 * 60,
    )
    login_attempts_per_minute = _bounded_int(
        login_attempts_raw,
        field="auth.login_attempts_per_minute",
        minimum=1,
        maximum=1000,
    )

    audit = AuditConfig(
        security_enabled=_as_bool(
            security_enabled_raw,
            field="audit.security_enabled",
        ),
        conversation_enabled=_as_bool(
            conversation_enabled_raw,
            field="audit.conversation_enabled",
        ),
        store_prompt_content=_as_bool(
            store_prompt_raw,
            field="audit.store_prompt_content",
        ),
        store_response_content=_as_bool(
            store_response_raw,
            field="audit.store_response_content",
        ),
        retention_days=_bounded_int(
            retention_raw,
            field="audit.retention_days",
            minimum=0,
            maximum=3650,
        ),
        max_metadata_bytes=_bounded_int(
            metadata_bytes_raw,
            field="audit.max_metadata_bytes",
            minimum=256,
            maximum=1024 * 1024,
        ),
        max_content_bytes=_bounded_int(
            content_bytes_raw,
            field="audit.max_content_bytes",
            minimum=1024,
            maximum=16 * 1024 * 1024,
        ),
    )

    return AppConfig(
        server=ServerConfig(
            host=host.strip(),
            port=port,
            request_timeout_seconds=request_timeout_seconds,
            max_connections=max_connections,
        ),
        storage=StorageConfig(sqlite_path=Path(sqlite_path_raw)),
        auth=AuthConfig(
            session_ttl_seconds=session_ttl_seconds,
            login_attempts_per_minute=login_attempts_per_minute,
        ),
        audit=audit,
    )
