from __future__ import annotations

import argparse

from .frontend_loader import load_frontend, load_frontend_config
from .http_clients import HttpUserBackendClient
from .user_application import UserApplication


DEFAULT_ENTRYPOINT = "fx_channel.frontends.user.jp_soft_pop:Frontend"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the fx_channel user app.")
    parser.add_argument(
        "--server",
        default="http://127.0.0.1:8787",
        help="fx_channel backend URL.",
    )
    parser.add_argument(
        "--frontend",
        default="config/user_frontend.yaml",
        help="User frontend configuration YAML.",
    )
    args = parser.parse_args()

    frontend_config = load_frontend_config(
        args.frontend,
        default_entrypoint=DEFAULT_ENTRYPOINT,
        default_options={"theme": "jp_soft_pop", "locale": "ja-JP"},
    )
    app = UserApplication(HttpUserBackendClient(args.server))
    frontend = load_frontend(frontend_config)
    frontend.run(app, frontend_config["frontend"].get("options", {}))


if __name__ == "__main__":
    main()
