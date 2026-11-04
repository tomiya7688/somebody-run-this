from __future__ import annotations

import argparse
import getpass
from pathlib import Path

from .audit import AuditSettings
from .auth import bootstrap_local_admin
from .config import ConfigError, load_config
from .server import build_server
from .storage import initialize


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Private AI Hub service")
    parser.add_argument("--config", type=Path, help="Path to TOML configuration")
    parser.add_argument(
        "--create-admin",
        action="store_true",
        help="Create the first local administrator and exit",
    )
    parser.add_argument(
        "--organization-id",
        default="default",
        help="Organization id for --create-admin",
    )
    parser.add_argument(
        "--organization-name",
        default="Default Organization",
        help="Organization name for --create-admin",
    )
    parser.add_argument(
        "--username",
        help="Administrator username for --create-admin",
    )
    parser.add_argument(
        "--display-name",
        help="Administrator display name for --create-admin",
    )
    return parser.parse_args()


def _create_admin(args: argparse.Namespace, database_path: Path) -> int:
    if not args.username:
        raise SystemExit("--username is required with --create-admin")

    password = getpass.getpass("New administrator password: ")
    confirmation = getpass.getpass("Confirm password: ")
    if password != confirmation:
        raise SystemExit("password confirmation does not match")

    try:
        user = bootstrap_local_admin(
            database_path,
            organization_id=args.organization_id,
            organization_name=args.organization_name,
            username=args.username,
            display_name=args.display_name,
            password=password,
        )
    except ValueError as exc:
        raise SystemExit(f"cannot create administrator: {exc}") from exc

    print(
        "Created local administrator "
        f"{user.username!r} in organization {user.organization_id!r}."
    )
    return 0


def main() -> int:
    args = parse_args()
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        raise SystemExit(f"configuration error: {exc}") from exc

    initialize(config.storage.sqlite_path)

    if args.create_admin:
        return _create_admin(args, config.storage.sqlite_path)

    server = build_server(
        config.server.host,
        config.server.port,
        config.storage.sqlite_path,
        max_connections=config.server.max_connections,
        request_timeout_seconds=config.server.request_timeout_seconds,
        session_ttl_seconds=config.auth.session_ttl_seconds,
        login_attempts_per_minute=config.auth.login_attempts_per_minute,
        audit_settings=AuditSettings(
            security_enabled=config.audit.security_enabled,
            conversation_enabled=config.audit.conversation_enabled,
            store_prompt_content=config.audit.store_prompt_content,
            store_response_content=config.audit.store_response_content,
            retention_days=config.audit.retention_days,
            max_metadata_bytes=config.audit.max_metadata_bytes,
            max_content_bytes=config.audit.max_content_bytes,
        ),
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
