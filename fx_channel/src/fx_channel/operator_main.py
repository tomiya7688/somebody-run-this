from __future__ import annotations

import argparse
import os

from .frontend_loader import load_frontend, load_frontend_config
from .http_clients import HttpOperatorBackendClient
from .operator_application import OperatorApplication


DEFAULT_ENTRYPOINT = "fx_channel.frontends.operator.control_panel:Frontend"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the fx_channel operator app.")
    parser.add_argument(
        "--server",
        default="http://127.0.0.1:8787",
        help="fx_channel backend URL.",
    )
    parser.add_argument(
        "--frontend",
        default="config/operator_frontend.yaml",
        help="Operator frontend configuration YAML.",
    )
    parser.add_argument(
        "--token-env",
        default="FX_CHANNEL_OPERATOR_TOKEN",
        help="Environment variable containing the operator API token.",
    )
    args = parser.parse_args()

    token = os.getenv(args.token_env)
    if not token:
        raise SystemExit(
            f"Operator token environment variable {args.token_env!r} is not set."
        )

    frontend_config = load_frontend_config(
        args.frontend,
        default_entrypoint=DEFAULT_ENTRYPOINT,
        default_options={"theme": "operator_control_panel", "locale": "ja-JP"},
    )
    app = OperatorApplication(HttpOperatorBackendClient(args.server, token))
    frontend = load_frontend(frontend_config)
    frontend.run(app, frontend_config["frontend"].get("options", {}))


if __name__ == "__main__":
    main()
