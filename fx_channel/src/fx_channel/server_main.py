from __future__ import annotations

import argparse
import hmac
import os
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .auth import UserAuthError, UserSessionManager, load_or_create_session_secret
from .config import load_operator_config
from .runtime import FxChannelRuntime


class UserActionRequest(BaseModel):
    action: str
    payload: dict[str, Any] = Field(default_factory=dict)


class OperatorActionRequest(BaseModel):
    action: str
    payload: dict[str, Any] = Field(default_factory=dict)


class _ApiRoutes:
    def __init__(
        self,
        runtime: FxChannelRuntime,
        *,
        operator_token: str,
        user_sessions: UserSessionManager,
    ) -> None:
        self._runtime = runtime
        self._operator_token = operator_token
        self._user_sessions = user_sessions

    def _require_operator(self, authorization: str | None) -> None:
        expected = f"Bearer {self._operator_token}"
        actual = authorization or ""
        if not hmac.compare_digest(actual, expected):
            raise HTTPException(status_code=401, detail="Unauthorized")

    def _require_user(self, authorization: str | None) -> str:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="User session required")

        token = authorization.removeprefix("Bearer ").strip()
        try:
            return self._user_sessions.verify(token)
        except UserAuthError as exc:
            raise HTTPException(status_code=401, detail="Invalid user session") from exc

    def health(self) -> dict[str, bool]:
        return {"ok": True}

    def user_session(self) -> dict[str, str]:
        return self._user_sessions.issue()

    def user_quotes(self) -> dict[str, Any]:
        return {"quotes": self._runtime.user_quotes()}

    def user_home(
        self,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        player_id = self._require_user(authorization)
        return self._runtime.user_home(player_id)

    def user_ranking(
        self,
        limit: int = 100,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        self._require_user(authorization)
        return {"ranking": self._runtime.user_ranking(limit=limit)}

    def user_action(
        self,
        request: UserActionRequest,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        player_id = self._require_user(authorization)
        return self._runtime.user_action(
            player_id,
            request.action,
            request.payload,
        )

    def operator_status(
        self,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        self._require_operator(authorization)
        return self._runtime.operator_status()

    def operator_action(
        self,
        request: OperatorActionRequest,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        self._require_operator(authorization)
        return self._runtime.operator_action(request.action, request.payload)


def _create_user_sessions(
    operator_token: str,
    user_session_secret: bytes | None,
) -> UserSessionManager:
    if user_session_secret is not None:
        return UserSessionManager(user_session_secret)
    return UserSessionManager.from_operator_token(operator_token)


def _configure_cors(app: FastAPI, cors_origins: list[str] | None) -> None:
    origins = list(cors_origins or [])
    if not origins:
        return

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )


def _register_routes(app: FastAPI, routes: _ApiRoutes) -> None:
    app.add_api_route("/health", routes.health, methods=["GET"])
    app.add_api_route("/api/user/session", routes.user_session, methods=["POST"])
    app.add_api_route("/api/user/quotes", routes.user_quotes, methods=["GET"])
    app.add_api_route("/api/user/home", routes.user_home, methods=["GET"])
    app.add_api_route("/api/user/ranking", routes.user_ranking, methods=["GET"])
    app.add_api_route("/api/user/action", routes.user_action, methods=["POST"])
    app.add_api_route("/api/operator/status", routes.operator_status, methods=["GET"])
    app.add_api_route("/api/operator/action", routes.operator_action, methods=["POST"])


def _mount_user_web(
    app: FastAPI,
    web_user_dir: str | Path | None,
    web_user_route: str,
) -> None:
    if web_user_dir is None:
        return

    web_path = Path(web_user_dir)
    if not web_path.is_dir():
        return

    app.mount(
        web_user_route,
        StaticFiles(directory=str(web_path), html=True),
        name="user-web",
    )


def create_app(
    runtime: FxChannelRuntime,
    *,
    operator_token: str,
    user_session_secret: bytes | None = None,
    cors_origins: list[str] | None = None,
    web_user_dir: str | Path | None = None,
    web_user_route: str = "/play",
) -> FastAPI:
    app = FastAPI(
        title="fx_channel server",
        version="0.1.0",
    )
    user_sessions = _create_user_sessions(operator_token, user_session_secret)
    routes = _ApiRoutes(
        runtime,
        operator_token=operator_token,
        user_sessions=user_sessions,
    )

    _configure_cors(app, cors_origins)
    _register_routes(app, routes)
    _mount_user_web(app, web_user_dir, web_user_route)
    return app


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
    parser.add_argument(
        "--web-user",
        default="web-user",
        help="Optional Flutter Web build directory served at /play.",
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

    raw_origins = server_config.get("cors_origins", [])
    cors_origins = (
        [str(value) for value in raw_origins]
        if isinstance(raw_origins, list)
        else []
    )
    web_user_route = str(server_config.get("user_web_route", "/play"))

    operator_path = Path(args.operator).resolve()
    data_root = operator_path.parent.parent

    runtime = FxChannelRuntime(
        config,
        content_root=args.content,
        data_root=data_root,
    )
    user_session_secret = load_or_create_session_secret(
        data_root / "data" / "user_session_secret.bin"
    )

    app = create_app(
        runtime,
        operator_token=operator_token,
        user_session_secret=user_session_secret,
        cors_origins=cors_origins,
        web_user_dir=args.web_user,
        web_user_route=web_user_route,
    )

    print(f"fx_channel backend listening on http://{host}:{port}")
    if Path(args.web_user).is_dir():
        print(f"user web app: http://{host}:{port}{web_user_route}")

    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
