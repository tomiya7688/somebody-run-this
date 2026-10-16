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
    user_sessions = (
        UserSessionManager(user_session_secret)
        if user_session_secret is not None
        else UserSessionManager.from_operator_token(operator_token)
    )

    origins = list(cors_origins or [])
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=False,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type"],
        )

    def require_operator(authorization: str | None) -> None:
        expected = f"Bearer {operator_token}"
        actual = authorization or ""
        if not hmac.compare_digest(actual, expected):
            raise HTTPException(status_code=401, detail="Unauthorized")

    def require_user(authorization: str | None) -> str:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="User session required")

        token = authorization.removeprefix("Bearer ").strip()
        try:
            return user_sessions.verify(token)
        except UserAuthError as exc:
            raise HTTPException(status_code=401, detail="Invalid user session") from exc

    @app.get("/health")
    def health() -> dict[str, bool]:
        return {"ok": True}

    @app.post("/api/user/session")
    def user_session() -> dict[str, str]:
        return user_sessions.issue()

    @app.get("/api/user/quotes")
    def user_quotes() -> dict[str, Any]:
        return {"quotes": runtime.user_quotes()}

    @app.get("/api/user/home")
    def user_home(
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        player_id = require_user(authorization)
        return runtime.user_home(player_id)

    @app.post("/api/user/action")
    def user_action(
        request: UserActionRequest,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        player_id = require_user(authorization)
        return runtime.user_action(
            player_id,
            request.action,
            request.payload,
        )

    @app.get("/api/operator/status")
    def operator_status(
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        require_operator(authorization)
        return runtime.operator_status()

    @app.post("/api/operator/action")
    def operator_action(
        request: OperatorActionRequest,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        require_operator(authorization)
        return runtime.operator_action(request.action, request.payload)

    if web_user_dir is not None:
        web_path = Path(web_user_dir)
        if web_path.is_dir():
            app.mount(
                web_user_route,
                StaticFiles(directory=str(web_path), html=True),
                name="user-web",
            )

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
