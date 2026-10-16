from __future__ import annotations

import argparse
import hmac
import json
import os
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .config import load_operator_config
from .runtime import FxChannelRuntime


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False).encode("utf-8")


def _read_json(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length", "0"))
    if length <= 0:
        return {}
    raw = json.loads(handler.rfile.read(length).decode("utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("JSON body must be an object.")
    return raw


def build_handler(runtime: FxChannelRuntime, operator_token: str):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, payload: Any) -> None:
            body = _json_bytes(payload)
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _operator_authorized(self) -> bool:
            expected = f"Bearer {operator_token}"
            actual = self.headers.get("Authorization", "")
            return hmac.compare_digest(actual, expected)

        def do_GET(self) -> None:
            parsed = urllib.parse.urlparse(self.path)

            if parsed.path == "/health":
                self._send(200, {"ok": True})
                return

            if parsed.path == "/api/user/quotes":
                self._send(200, {"quotes": runtime.user_quotes()})
                return

            if parsed.path == "/api/user/home":
                query = urllib.parse.parse_qs(parsed.query)
                player_id = query.get("player_id", ["guest"])[0]
                self._send(200, runtime.user_home(player_id))
                return

            if parsed.path == "/api/operator/status":
                if not self._operator_authorized():
                    self._send(401, {"ok": False, "message": "Unauthorized"})
                    return
                self._send(200, runtime.operator_status())
                return

            self._send(404, {"ok": False, "message": "Not found"})

        def do_POST(self) -> None:
            parsed = urllib.parse.urlparse(self.path)

            try:
                payload = _read_json(self)
            except Exception as exc:
                self._send(400, {"ok": False, "message": str(exc)})
                return

            if parsed.path == "/api/user/action":
                self._send(
                    200,
                    runtime.user_action(
                        str(payload.get("player_id", "guest")),
                        str(payload.get("action", "")),
                        payload.get("payload", {}),
                    ),
                )
                return

            if parsed.path == "/api/operator/action":
                if not self._operator_authorized():
                    self._send(401, {"ok": False, "message": "Unauthorized"})
                    return
                self._send(
                    200,
                    runtime.operator_action(
                        str(payload.get("action", "")),
                        payload.get("payload", {}),
                    ),
                )
                return

            self._send(404, {"ok": False, "message": "Not found"})

        def log_message(self, format: str, *args: Any) -> None:
            print(f"[server] {self.address_string()} - {format % args}")

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the fx_channel backend server.")
    parser.add_argument(
        "--operator",
        default="config/operator.yaml",
        help="Operator/server configuration YAML.",
    )
    parser.add_argument(
        "--content",
        default="content",
        help="Character/skill/gacha content directory.",
    )
    args = parser.parse_args()

    config = load_operator_config(args.operator)
    server_config = config.get("server", {})
    host = str(server_config.get("host", "127.0.0.1"))
    port = int(server_config.get("port", 8787))
    token_env = str(
        server_config.get("operator_token_env", "FX_CHANNEL_OPERATOR_TOKEN")
    )
    operator_token = os.getenv(token_env)

    if not operator_token:
        raise SystemExit(
            f"Operator token environment variable {token_env!r} is not set."
        )

    runtime = FxChannelRuntime(config, content_root=args.content)
    server = ThreadingHTTPServer(
        (host, port),
        build_handler(runtime, operator_token),
    )

    print(f"fx_channel backend listening on http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
