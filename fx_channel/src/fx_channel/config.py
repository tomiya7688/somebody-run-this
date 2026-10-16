from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class ConfigError(ValueError):
    """Raised when operator configuration is invalid."""


def load_operator_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    if not config_path.exists():
        raise ConfigError(
            f"Operator config not found: {config_path}. "
            "Copy config/operator.example.yaml to config/operator.yaml first."
        )

    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ConfigError("Operator config must be a YAML mapping.")

    market = raw.get("market")
    if not isinstance(market, dict):
        raise ConfigError("market section is required.")

    mode = market.get("mode")
    if mode not in {"real", "simulated"}:
        raise ConfigError("market.mode must be either 'real' or 'simulated'.")

    symbols = raw.get("symbols")
    if not isinstance(symbols, list) or not symbols or not all(
        isinstance(symbol, str) and symbol.strip() for symbol in symbols
    ):
        raise ConfigError("symbols must be a non-empty list of symbol names.")

    return raw
