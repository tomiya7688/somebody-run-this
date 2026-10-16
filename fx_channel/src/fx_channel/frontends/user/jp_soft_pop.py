from __future__ import annotations

from typing import Any, Mapping

from fx_channel.user_frontend_api import UserApplicationPort


class Frontend:
    """Default Japanese-social-game-inspired user frontend adapter."""

    def run(
        self,
        app: UserApplicationPort,
        options: Mapping[str, Any],
    ) -> None:
        theme = str(options.get("theme", "jp_soft_pop"))
        locale = str(options.get("locale", "ja-JP"))
        quotes = app.refresh_quotes()

        print(f"fx_channel USER frontend={theme} locale={locale}")
        print("Default GUI: Japanese social-game style + slightly pop")
        for quote in quotes:
            print(f"{quote.symbol}: {quote.price}")
