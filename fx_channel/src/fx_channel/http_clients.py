from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any, Mapping, Sequence


def _json_request(
    url: str,
    *,
    method: str = "GET",
    payload: Mapping[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
) -> Any:
    body = None
    request_headers = {"Accept": "application/json"}
    request_headers.update(headers or {})

    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        request_headers["Content-Type"] = "application/json"

    request = urllib.request.Request(
        url,
        data=body,
        headers=request_headers,
        method=method,
    )

    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


class HttpUserBackendClient:
    def __init__(self, server_url: str) -> None:
        self._base = server_url.rstrip("/")

    def get_home(self, player_id: str) -> Mapping[str, Any]:
        query = urllib.parse.urlencode({"player_id": player_id})
        return _json_request(f"{self._base}/api/user/home?{query}")

    def get_quotes(self) -> Sequence[Mapping[str, Any]]:
        raw = _json_request(f"{self._base}/api/user/quotes")
        return raw["quotes"]

    def post_action(
        self,
        player_id: str,
        action: str,
        payload: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        return _json_request(
            f"{self._base}/api/user/action",
            method="POST",
            payload={
                "player_id": player_id,
                "action": action,
                "payload": dict(payload),
            },
        )


class HttpOperatorBackendClient:
    def __init__(self, server_url: str, token: str) -> None:
        self._base = server_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {token}"}

    def get_status(self) -> Mapping[str, Any]:
        return _json_request(
            f"{self._base}/api/operator/status",
            headers=self._headers,
        )

    def post_operator_action(
        self,
        action: str,
        payload: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        return _json_request(
            f"{self._base}/api/operator/action",
            method="POST",
            payload={"action": action, "payload": dict(payload)},
            headers=self._headers,
        )
