from __future__ import annotations

import argparse
import ast
from pathlib import Path


COMMON_FORBIDDEN = {
    "fx_channel.market",
    "fx_channel.config",
    "fx_channel.content",
    "fx_channel.skill_api",
    "fx_channel.runtime",
    "fx_channel.http_clients",
    "fx_channel.frontend_loader",
}


def _imports(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result: list[tuple[int, str]] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            result.append((node.lineno, node.module))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                result.append((node.lineno, alias.name))

    return result


def validate_frontend_file(
    path: Path,
    *,
    allowed_contract: str,
    forbidden_contract: str,
) -> list[str]:
    errors: list[str] = []

    for lineno, module in _imports(path):
        if module == forbidden_contract or module.startswith(forbidden_contract + "."):
            errors.append(
                f"{path}:{lineno}: frontend must not import opposite app contract "
                f"{module!r}"
            )
            continue

        if any(
            module == prefix or module.startswith(prefix + ".")
            for prefix in COMMON_FORBIDDEN
        ):
            errors.append(
                f"{path}:{lineno}: frontend must not import internal module {module!r}"
            )
            continue

        if module.startswith("fx_channel.") and module != allowed_contract:
            errors.append(
                f"{path}:{lineno}: frontend may only depend on "
                f"{allowed_contract!r}; found {module!r}"
            )

    return errors


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate user/operator GUI separation."
    )
    parser.add_argument(
        "--frontends",
        default="src/fx_channel/frontends",
        help="Directory containing built-in frontend adapters.",
    )
    args = parser.parse_args()

    root = Path(args.frontends)
    errors: list[str] = []

    user_root = root / "user"
    operator_root = root / "operator"

    for path in sorted(user_root.rglob("*.py")):
        if path.name == "__init__.py":
            continue
        errors.extend(
            validate_frontend_file(
                path,
                allowed_contract="fx_channel.user_frontend_api",
                forbidden_contract="fx_channel.operator_frontend_api",
            )
        )

    for path in sorted(operator_root.rglob("*.py")):
        if path.name == "__init__.py":
            continue
        errors.extend(
            validate_frontend_file(
                path,
                allowed_contract="fx_channel.operator_frontend_api",
                forbidden_contract="fx_channel.user_frontend_api",
            )
        )

    if errors:
        raise SystemExit("ARCHITECTURE ERROR:\n" + "\n".join(errors))

    print("OK: user and operator frontends are isolated by separate contracts")


if __name__ == "__main__":
    main()
