from __future__ import annotations

import argparse

from .application import FxChannelApplication
from .config import load_operator_config
from .frontend_loader import load_developer_config, load_frontend


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run fx_channel using a swappable frontend."
    )
    parser.add_argument(
        "--operator",
        default="config/operator.yaml",
        help="Operator configuration YAML.",
    )
    parser.add_argument(
        "--developer",
        default="config/developer.yaml",
        help=(
            "Developer frontend configuration YAML. "
            "If absent, jp_soft_pop is used."
        ),
    )
    parser.add_argument(
        "--content",
        default="content",
        help="Character/skill/gacha content directory.",
    )
    args = parser.parse_args()

    operator_config = load_operator_config(args.operator)
    developer_config = load_developer_config(args.developer)

    app = FxChannelApplication(
        operator_config,
        content_root=args.content,
    )
    frontend = load_frontend(developer_config)
    options = developer_config["frontend"].get("options", {})

    frontend.run(app, options)


if __name__ == "__main__":
    main()
