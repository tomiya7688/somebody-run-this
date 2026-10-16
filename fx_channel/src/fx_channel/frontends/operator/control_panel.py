from __future__ import annotations

from typing import Any, Mapping

from fx_channel.operator_frontend_api import OperatorApplicationPort


class Frontend:
    """Default operator control-panel frontend adapter."""

    def run(
        self,
        app: OperatorApplicationPort,
        options: Mapping[str, Any],
    ) -> None:
        theme = str(options.get("theme", "operator_control_panel"))
        locale = str(options.get("locale", "ja-JP"))
        status = app.get_status()

        print(f"fx_channel OPERATOR frontend={theme} locale={locale}")
        print(f"market_mode: {status.market_mode}")
        print(f"symbols: {', '.join(status.symbols)}")
        print(
            f"content: {status.characters} characters / "
            f"{status.skills} skills / {status.gacha_pools} gacha pools"
        )
