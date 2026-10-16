from __future__ import annotations

import json
import math
import os
import random
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol


class MarketError(RuntimeError):
    """Raised when market prices cannot be obtained."""


class PriceProvider(Protocol):
    def get_prices(self, symbols: list[str]) -> dict[str, float]:
        """Return the latest price for every requested symbol."""


@dataclass
class SimulatedPriceProvider:
    seed: int | None = None
    base_volatility: float = 0.001
    drift: float = 0.0
    default_start_price: float = 100.0

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed)
        self._prices: dict[str, float] = {}

    def get_prices(self, symbols: list[str]) -> dict[str, float]:
        result: dict[str, float] = {}

        for symbol in symbols:
            previous = self._prices.get(symbol, self.default_start_price)

            # Geometric random walk: prices always remain positive.
            shock = self._rng.gauss(0.0, self.base_volatility)
            next_price = previous * math.exp(self.drift + shock)

            self._prices[symbol] = next_price
            result[symbol] = next_price

        return result


@dataclass
class GenericHttpPriceProvider:
    endpoint: str
    api_key_env: str | None = None
    api_key_header: str = "X-API-Key"
    timeout_seconds: float = 5.0
    on_error: str = "keep_last"
    fallback: PriceProvider | None = None

    def __post_init__(self) -> None:
        self._last_prices: dict[str, float] = {}

    def get_prices(self, symbols: list[str]) -> dict[str, float]:
        try:
            prices = self._fetch(symbols)
            self._last_prices.update(prices)
            return {symbol: self._last_prices[symbol] for symbol in symbols}
        except Exception as exc:
            if self.on_error == "keep_last":
                if all(symbol in self._last_prices for symbol in symbols):
                    return {symbol: self._last_prices[symbol] for symbol in symbols}
            elif self.on_error == "fallback_simulated" and self.fallback is not None:
                return self.fallback.get_prices(symbols)

            raise MarketError(f"Failed to obtain real market prices: {exc}") from exc

    def _fetch(self, symbols: list[str]) -> dict[str, float]:
        separator = "&" if "?" in self.endpoint else "?"
        query = urllib.parse.urlencode({"symbols": ",".join(symbols)})
        url = f"{self.endpoint}{separator}{query}"

        headers = {"Accept": "application/json"}

        if self.api_key_env:
            api_key = os.getenv(self.api_key_env)
            if not api_key:
                raise MarketError(
                    f"Environment variable {self.api_key_env!r} is not set."
                )
            headers[self.api_key_header] = api_key

        request = urllib.request.Request(url, headers=headers)

        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))

        # Supported generic response forms:
        # {"rates": {"USDJPY": 150.1, "EURUSD": 1.08}}
        # {"USDJPY": 150.1, "EURUSD": 1.08}
        raw_rates: Any
        if isinstance(payload, dict) and isinstance(payload.get("rates"), dict):
            raw_rates = payload["rates"]
        else:
            raw_rates = payload

        if not isinstance(raw_rates, dict):
            raise MarketError("API response must be a mapping of symbol -> price.")

        prices: dict[str, float] = {}
        for symbol in symbols:
            if symbol not in raw_rates:
                raise MarketError(f"API response did not include {symbol!r}.")

            price = float(raw_rates[symbol])
            if not math.isfinite(price) or price <= 0:
                raise MarketError(f"Invalid price for {symbol!r}: {price!r}")

            prices[symbol] = price

        return prices


def build_price_provider(config: dict[str, Any]) -> PriceProvider:
    market = config["market"]
    mode = market["mode"]

    simulated_config = market.get("simulated", {})
    simulated = SimulatedPriceProvider(
        seed=simulated_config.get("seed"),
        base_volatility=float(simulated_config.get("base_volatility", 0.001)),
        drift=float(simulated_config.get("drift", 0.0)),
        default_start_price=float(simulated_config.get("default_start_price", 100.0)),
    )

    if mode == "simulated":
        return simulated

    real_config = market.get("real", {})
    provider_name = real_config.get("provider", "generic_http")
    if provider_name != "generic_http":
        raise MarketError(
            f"Unknown real market provider {provider_name!r}. "
            "Add an adapter before selecting it."
        )

    return GenericHttpPriceProvider(
        endpoint=str(real_config["endpoint"]),
        api_key_env=real_config.get("api_key_env"),
        api_key_header=str(real_config.get("api_key_header", "X-API-Key")),
        timeout_seconds=float(real_config.get("timeout_seconds", 5)),
        on_error=str(real_config.get("on_error", "keep_last")),
        fallback=simulated,
    )
