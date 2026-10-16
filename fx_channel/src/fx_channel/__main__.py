from __future__ import annotations

import argparse
import json
import time

from .config import load_operator_config
from .market import build_price_provider


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Check fx_channel market provider configuration."
    )
    parser.add_argument(
        "--config",
        default="config/operator.yaml",
        help="Path to operator YAML configuration.",
    )
    parser.add_argument(
        "--ticks",
        type=int,
        default=1,
        help="Number of price ticks to print.",
    )
    args = parser.parse_args()

    config = load_operator_config(args.config)
    provider = build_price_provider(config)
    symbols = config["symbols"]

    tick_seconds = float(
        config["market"].get("simulated", {}).get("tick_seconds", 5)
        if config["market"]["mode"] == "simulated"
        else config["market"].get("real", {}).get("poll_seconds", 10)
    )

    for index in range(args.ticks):
        prices = provider.get_prices(symbols)
        print(json.dumps(prices, ensure_ascii=False, indent=2))

        if index + 1 < args.ticks:
            time.sleep(tick_seconds)


if __name__ == "__main__":
    main()
