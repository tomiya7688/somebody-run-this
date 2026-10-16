from __future__ import annotations

from typing import Any, Mapping

from fx_channel.frontend_api import ApplicationPort


class Frontend:
    """
    Default frontend adapter.

    The visual implementation will live entirely behind this adapter.
    It deliberately knows only ApplicationPort and display DTOs.
    """

    def run(
        self,
        app: ApplicationPort,
        options: Mapping[str, Any],
    ) -> None:
        theme = str(options.get("theme", "jp_soft_pop"))
        locale = str(options.get("locale", "ja-JP"))

        # Temporary bootstrap while the actual visual shell is built.
        # No game logic belongs here.
        quotes = app.refresh_quotes()

        print(f"fx_channel frontend={theme} locale={locale}")
        print("Default GUI: Japanese social-game style + slightly pop")
        for quote in quotes:
            print(f"{quote.symbol}: {quote.price}")
