from __future__ import annotations

import argparse
import ast
from pathlib import Path


ALLOWED_FX_CHANNEL_IMPORTS = {
    "fx_channel.frontend_api",
}

DISALLOWED_PREFIXES = {
    "fx_channel.market",
    "fx_channel.config",
    "fx_channel.content",
    "fx_channel.skill_api",
    "fx_channel.frontend_loader",
}


def validate_frontend_file(path: Path) -> list[str]:
    errors: list[str] = []
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    for node in ast.walk(tree):
        module: str | None = None

        if isinstance(node, ast.ImportFrom):
            module = node.module
        elif isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.name
                if any(
                    name == prefix or name.startswith(prefix + ".")
                    for prefix in DISALLOWED_PREFIXES
                ):
                    errors.append(
                        f"{path}:{node.lineno}: frontend must not import {name!r}"
                    )
            continue

        if module is None:
            continue

        if any(
            module == prefix or module.startswith(prefix + ".")
            for prefix in DISALLOWED_PREFIXES
        ):
            errors.append(
                f"{path}:{node.lineno}: frontend must not import {module!r}"
            )
        elif module.startswith("fx_channel.") and module not in ALLOWED_FX_CHANNEL_IMPORTS:
            errors.append(
                f"{path}:{node.lineno}: built-in frontend may only depend on "
                f"fx_channel.frontend_api; found {module!r}"
            )

    return errors


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate strict GUI/application dependency boundaries."
    )
    parser.add_argument(
        "--frontends",
        default="src/fx_channel/frontends",
        help="Directory containing built-in frontend adapters.",
    )
    args = parser.parse_args()

    root = Path(args.frontends)
    errors: list[str] = []

    for path in sorted(root.rglob("*.py")):
        if path.name == "__init__.py":
            continue
        errors.extend(validate_frontend_file(path))

    if errors:
        raise SystemExit("ARCHITECTURE ERROR:\n" + "\n".join(errors))

    print("OK: built-in frontends depend only on fx_channel.frontend_api")


if __name__ == "__main__":
    main()
