from __future__ import annotations

from typing import Any, Mapping, Protocol

from .operator_frontend_api import OperatorActionResult, OperatorStatusView


class OperatorBackendPort(Protocol):
    """Authenticated network/service boundary used by the operator app."""

    def get_status(self) -> Mapping[str, Any]:
        ...

    def post_operator_action(
        self,
        action: str,
        payload: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        ...


class OperatorApplication:
    """
    Operator-client application layer.

    This application is separate from UserApplication and has a different port.
    User frontends never receive this object.
    """

    def __init__(self, backend: OperatorBackendPort) -> None:
        self._backend = backend

    def get_status(self) -> OperatorStatusView:
        raw = self._backend.get_status()
        return OperatorStatusView(
            market_mode=str(raw["market_mode"]),
            symbols=tuple(str(x) for x in raw["symbols"]),
            characters=int(raw["characters"]),
            skills=int(raw["skills"]),
            gacha_pools=int(raw["gacha_pools"]),
        )

    def execute_operator_action(
        self,
        action: str,
        payload: Mapping[str, Any],
    ) -> OperatorActionResult:
        raw = self._backend.post_operator_action(action, payload)
        return OperatorActionResult(
            ok=bool(raw["ok"]),
            message=str(raw["message"]),
            data=dict(raw.get("data", {})),
        )
