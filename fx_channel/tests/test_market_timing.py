from __future__ import annotations

from fx_channel.market import GenericHttpPriceProvider, SimulatedPriceProvider


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value


class CountingHttpProvider(GenericHttpPriceProvider):
    def __post_init__(self) -> None:
        super().__post_init__()
        self.fetch_count = 0

    def _fetch(self, symbols: list[str]) -> dict[str, float]:
        self.fetch_count += 1
        return {
            symbol: 100.0 + self.fetch_count
            for symbol in symbols
        }


def test_simulated_market_does_not_advance_per_request() -> None:
    clock = FakeClock()
    provider = SimulatedPriceProvider(
        seed=1,
        tick_seconds=5,
        base_volatility=0.01,
        clock=clock,
    )

    first = provider.get_prices(["USDJPY"])
    second = provider.get_prices(["USDJPY"])
    assert second == first

    clock.value = 4.99
    third = provider.get_prices(["USDJPY"])
    assert third == first

    clock.value = 5.0
    fourth = provider.get_prices(["USDJPY"])
    assert fourth != first


def test_real_market_respects_poll_interval() -> None:
    clock = FakeClock()
    provider = CountingHttpProvider(
        endpoint="https://unused.example",
        poll_seconds=10,
        clock=clock,
    )

    first = provider.get_prices(["USDJPY"])
    second = provider.get_prices(["USDJPY"])

    assert first == second
    assert provider.fetch_count == 1

    clock.value = 9.9
    provider.get_prices(["USDJPY"])
    assert provider.fetch_count == 1

    clock.value = 10.0
    third = provider.get_prices(["USDJPY"])
    assert provider.fetch_count == 2
    assert third["USDJPY"] == 102.0
