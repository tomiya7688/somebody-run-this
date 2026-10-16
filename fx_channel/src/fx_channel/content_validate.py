from __future__ import annotations

import argparse

from .content import ContentError, load_content_registry


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate fx_channel characters, skills, and gacha YAML."
    )
    parser.add_argument(
        "--content",
        default="content",
        help="Path to fx_channel content directory.",
    )
    args = parser.parse_args()

    try:
        registry = load_content_registry(args.content)
    except ContentError as exc:
        raise SystemExit(f"CONTENT ERROR: {exc}") from exc

    print(
        "OK: "
        f"{len(registry.characters)} characters, "
        f"{len(registry.skills)} skills, "
        f"{len(registry.gacha)} gacha pools"
    )


if __name__ == "__main__":
    main()
