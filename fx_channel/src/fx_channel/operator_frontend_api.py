from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol


@dataclass(frozen=True)
class OperatorStatusView:
    market_mode: str
    symbols: tuple[str, ...]
    characters: int
    skills: int
    gacha_pools: int


@dataclass(frozen=True)
class OperatorActionResult:
    ok: bool
    message: str
    data: Mapping[str, Any]


class OperatorApplicationPort(Protocol):
    """The complete API visible to the operator application GUI."""

    def get_status(self) -> OperatorStatusView:
        ...

    def execute_operator_action(
        self,
        action: str,
        payload: Mapping[str, Any],
    ) -> OperatorActionResult:
        ...


class OperatorFrontend(Protocol):
    def run(
        self,
        app: OperatorApplicationPort,
        options: Mapping[str, Any],
    ) -> None:
        ...
