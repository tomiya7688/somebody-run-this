from __future__ import annotations

import http.client
import ipaddress
import json
import math
import os
import random
import threading
import time
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol


class MarketError(RuntimeError):
    """Raised when market prices cannot be obtained."""


class PriceProvider(Protocol):
    def get_prices(self, symbols: list[str]) -> dict[str, float]:
        """Return the latest price for every requested symbol."""


@dataclass
class SimulatedPriceProvider:
    seed: int | None = None
    tick_seconds: float = 5.0
    base_volatility: float = 0.001
    drift: float = 0.0
    default_start_price: float = 100.0
    max_catchup_ticks: int = 1000
    clock: Callable[[], float] = field(
        default=time.monotonic,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed)
        self._prices: dict[str, float] = {}
        self._last_tick_at: float | None = None
        self._lock = threading.RLock()

    def get_prices(self, symbols: list[str]) -> dict[str, float]:
        with self._lock:
            for symbol in symbols:
                self._prices.setdefault(symbol, self.default_start_price)

            now = self.clock()
            if self._last_tick_at is None:
                self._last_tick_at = now
                return {
                    symbol: self._prices[symbol]
                    for symbol in symbols
                }

            if self.tick_seconds <= 0:
                ticks = 1
            else:
                elapsed = max(0.0, now - self._last_tick_at)
                ticks = int(elapsed // self.tick_seconds)

            if ticks <= 0:
                return {
                    symbol: self._prices[symbol]
                    for symbol in symbols
                }

            capped_ticks = min(ticks, max(1, self.max_catchup_ticks))

            for _ in range(capped_ticks):
                for symbol in symbols:
                    previous = self._prices[symbol]
                    # Geometric random walk: prices always remain positive.
                    shock = self._rng.gauss(0.0, self.base_volatility)
                    self._prices[symbol] = previous * math.exp(
                        self.drift + shock
                    )

            if self.tick_seconds <= 0 or ticks > capped_ticks:
                self._last_tick_at = now
            else:
                self._last_tick_at += capped_ticks * self.tick_seconds

            return {
                symbol: self._prices[symbol]
                for symbol in symbols
            }


@dataclass
class GenericHttpPriceProvider:
    endpoint: str
    api_key_env: str | None = None
    api_key_header: str = "X-API-Key"
    poll_seconds: float = 10.0
    timeout_seconds: float = 5.0
    max_response_bytes: int = 1_000_000
    on_error: str = "keep_last"
    fallback: PriceProvider | None = None
    clock: Callable[[], float] = field(
        default=time.monotonic,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        self._endpoint_parts = self._validate_endpoint(self.endpoint)
        if self.timeout_seconds <= 0:
            raise MarketError("timeout_seconds must be greater than 0.")
        if self.max_response_bytes <= 0:
            raise MarketError("max_response_bytes must be greater than 0.")

        self._last_prices: dict[str, float] = {}
        self._last_poll_at: float | None = None
        self._last_error: Exception | None = None
        self._lock = threading.RLock()

    @staticmethod
    def _validate_endpoint(endpoint: str) -> urllib.parse.SplitResult:
        parts = urllib.parse.urlsplit(endpoint)
        scheme = parts.scheme.lower()
        if scheme not in {"https", "http"}:
            raise MarketError("Market endpoint must use HTTPS.")
        if parts.username is not None or parts.password is not None:
            raise MarketError("Market endpoint must not contain credentials.")
        if parts.hostname is None:
            raise MarketError("Market endpoint must include a hostname.")
        if parts.fragment:
            raise MarketError("Market endpoint must not contain a URL fragment.")

        if scheme == "https":
            return parts

        host = parts.hostname.lower()
        if host == "localhost":
            return parts
        try:
            if ipaddress.ip_address(host).is_loopback:
                return parts
        except ValueError:
            pass

        raise MarketError("Plain HTTP market endpoints are allowed only on loopback.")

    def get_prices(self, symbols: list[str]) -> dict[str, float]:
        with self._lock:
            now = self.clock()
            within_poll_window = (
                self._last_poll_at is not None
                and self.poll_seconds > 0
                and now - self._last_poll_at < self.poll_seconds
            )

            if within_poll_window:
                if all(symbol in self._last_prices for symbol in symbols):
                    return {
                        symbol: self._last_prices[symbol]
                        for symbol in symbols
                    }
                return self._handle_error(
                    symbols,
                    self._last_error
                    or MarketError("Market data is not available yet."),
                )

            self._last_poll_at = now

            try:
                prices = self._fetch(symbols)
                self._last_prices.update(prices)
                self._last_error = None
                return {
                    symbol: self._last_prices[symbol]
                    for symbol in symbols
                }
            except Exception as exc:
                self._last_error = exc
                return self._handle_error(symbols, exc)

    def _handle_error(
        self,
        symbols: list[str],
        exc: Exception,
    ) -> dict[str, float]:
        if self.on_error == "keep_last":
            if all(symbol in self._last_prices for symbol in symbols):
                return {
                    symbol: self._last_prices[symbol]
                    for symbol in symbols
                }
        elif self.on_error == "fallback_simulated" and self.fallback is not None:
            return self.fallback.get_prices(symbols)

        raise MarketError(
            f"Failed to obtain real market prices: {exc}"
        ) from exc

    def _fetch(self, symbols: list[str]) -> dict[str, float]:
        parts = self._endpoint_parts
        query_items = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
        query_items.append(("symbols", ",".join(symbols)))
        query = urllib.parse.urlencode(query_items)
        path = parts.path or "/"
        target = urllib.parse.urlunsplit(("", "", path, query, ""))

        headers = {"Accept": "application/json"}

        if self.api_key_env:
            api_key = os.getenv(self.api_key_env)
            if not api_key:
                raise MarketError(
                    f"Environment variable {self.api_key_env!r} is not set."
                )
            headers[self.api_key_header] = api_key

        host = parts.hostname
        if host is None:
            raise MarketError("Market endpoint hostname disappeared after validation.")

        connection_class = (
            http.client.HTTPSConnection
            if parts.scheme.lower() == "https"
            else http.client.HTTPConnection
        )
        connection = connection_class(
            host,
            port=parts.port,
            timeout=self.timeout_seconds,
        )
        try:
            connection.request("GET", target, headers=headers)
            response = connection.getresponse()
            if not 200 <= response.status < 300:
                raise MarketError(
                    f"Market API returned HTTP {response.status}."
                )
            raw_payload = response.read(self.max_response_bytes + 1)
            if len(raw_payload) > self.max_response_bytes:
                raise MarketError("Market API response exceeded the configured size limit.")
        finally:
            connection.close()

        payload = json.loads(raw_payload.decode("utf-8"))

        # Supported generic response forms:
        # {"rates": {"USDJPY": 150.1, "EURUSD": 1.08}}
        # {"USDJPY": 150.1, "EURUSD": 1.08}
        raw_rates: Any
        if isinstance(payload, dict) and isinstance(payload.get("rates"), dict):
            raw_rates = payload["rates"]
        else:
            raw_rates = payload

        if not isinstance(raw_rates, dict):
            raise MarketError(
                "API response must be a mapping of symbol -> price."
            )

        prices: dict[str, float] = {}
        for symbol in symbols:
            if symbol not in raw_rates:
                raise MarketError(
                    f"API response did not include {symbol!r}."
                )

            price = float(raw_rates[symbol])
            if not math.isfinite(price) or price <= 0:
                raise MarketError(
                    f"Invalid price for {symbol!r}: {price!r}"
                )

            prices[symbol] = price

        return prices


def build_price_provider(config: dict[str, Any]) -> PriceProvider:
    market = config["market"]
    mode = market["mode"]

    simulated_config = market.get("simulated", {})
    simulated = SimulatedPriceProvider(
        seed=simulated_config.get("seed"),
        tick_seconds=float(simulated_config.get("tick_seconds", 5)),
        base_volatility=float(
            simulated_config.get("base_volatility", 0.001)
        ),
        drift=float(simulated_config.get("drift", 0.0)),
        default_start_price=float(
            simulated_config.get("default_start_price", 100.0)
        ),
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
        api_key_header=str(
            real_config.get("api_key_header", "X-API-Key")
        ),
        poll_seconds=float(real_config.get("poll_seconds", 10)),
        timeout_seconds=float(real_config.get("timeout_seconds", 5)),
        on_error=str(real_config.get("on_error", "keep_last")),
        fallback=simulated,
    )
