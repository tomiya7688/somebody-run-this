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
class AppConfig:
    server: ServerConfig = ServerConfig()
    storage: StorageConfig = StorageConfig()


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
    if not isinstance(server_raw, dict):
        raise ConfigError("[server] must be a table")
    if not isinstance(storage_raw, dict):
        raise ConfigError("[storage] must be a table")

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

    if not isinstance(host, str) or not host.strip():
        raise ConfigError("server.host must be a non-empty string")

    port = _as_int(port_raw, field="server.port")
    if not 1 <= port <= 65535:
        raise ConfigError("server.port must be between 1 and 65535")

    request_timeout_seconds = _as_int(
        timeout_raw, field="server.request_timeout_seconds"
    )
    if not 1 <= request_timeout_seconds <= 3600:
        raise ConfigError("server.request_timeout_seconds must be between 1 and 3600")

    max_connections = _as_int(
        max_connections_raw, field="server.max_connections"
    )
    if not 1 <= max_connections <= 4096:
        raise ConfigError("server.max_connections must be between 1 and 4096")

    if not isinstance(sqlite_path_raw, (str, os.PathLike)) or not str(sqlite_path_raw).strip():
        raise ConfigError("storage.sqlite_path must be a non-empty path")

    return AppConfig(
        server=ServerConfig(
            host=host.strip(),
            port=port,
            request_timeout_seconds=request_timeout_seconds,
            max_connections=max_connections,
        ),
        storage=StorageConfig(sqlite_path=Path(sqlite_path_raw)),
    )
