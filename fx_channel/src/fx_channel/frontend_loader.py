from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import yaml


class FrontendConfigError(ValueError):
    pass


def load_frontend_config(
    path: str | Path,
    *,
    default_entrypoint: str,
    default_options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    config_path = Path(path)

    if not config_path.exists():
        return {
            "frontend": {
                "entrypoint": default_entrypoint,
                "options": dict(default_options or {}),
            }
        }

    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise FrontendConfigError("Frontend config must be a YAML mapping.")

    frontend = raw.get("frontend")
    if not isinstance(frontend, dict):
        raise FrontendConfigError("frontend section is required.")

    entrypoint = frontend.get("entrypoint")
    if not isinstance(entrypoint, str) or ":" not in entrypoint:
        raise FrontendConfigError(
            "frontend.entrypoint must use 'module.path:ClassName' format."
        )

    options = frontend.get("options", {})
    if not isinstance(options, dict):
        raise FrontendConfigError("frontend.options must be a mapping.")

    return raw


def load_frontend(config: dict[str, Any]) -> Any:
    frontend_config = config["frontend"]
    entrypoint = frontend_config["entrypoint"]
    module_name, class_name = entrypoint.split(":", 1)

    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise FrontendConfigError(
            f"Could not import frontend module {module_name!r}."
        ) from exc

    try:
        frontend_class = getattr(module, class_name)
    except AttributeError as exc:
        raise FrontendConfigError(
            f"Frontend class {class_name!r} was not found in {module_name!r}."
        ) from exc

    frontend = frontend_class()
    if not callable(getattr(frontend, "run", None)):
        raise FrontendConfigError(
            f"{entrypoint!r} must provide a callable run(app, options) method."
        )

    return frontend
