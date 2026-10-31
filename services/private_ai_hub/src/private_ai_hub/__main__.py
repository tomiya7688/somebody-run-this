from __future__ import annotations

import argparse
from pathlib import Path

from .config import ConfigError, load_config
from .server import build_server
from .storage import initialize


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Private AI Hub bootstrap service")
    parser.add_argument("--config", type=Path, help="Path to TOML configuration")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        raise SystemExit(f"configuration error: {exc}") from exc

    initialize(config.storage.sqlite_path)
    server = build_server(
        config.server.host,
        config.server.port,
        config.storage.sqlite_path,
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
