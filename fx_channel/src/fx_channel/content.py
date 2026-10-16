from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class ContentError(ValueError):
    """Raised when character, skill, or gacha content is invalid."""


@dataclass(frozen=True)
class SkillDefinition:
    id: str
    name: str
    type: str
    description: str
    implementation: str
    cooldown_seconds: int
    parameters: dict[str, Any]


@dataclass(frozen=True)
class CharacterDefinition:
    id: str
    name: str
    rarity: str
    description: str
    skills: tuple[str, ...]
    tags: tuple[str, ...]


@dataclass(frozen=True)
class GachaEntry:
    character: str
    weight: float


@dataclass(frozen=True)
class GachaDefinition:
    id: str
    name: str
    currency: str
    cost: int
    entries: tuple[GachaEntry, ...]


@dataclass(frozen=True)
class ContentRegistry:
    skills: dict[str, SkillDefinition]
    characters: dict[str, CharacterDefinition]
    gacha: dict[str, GachaDefinition]


ALLOWED_SKILL_TYPES = {"forecast", "analysis", "alert", "utility", "passive"}


def _load_yaml_files(directory: Path) -> list[tuple[Path, dict[str, Any]]]:
    if not directory.exists():
        return []

    result: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(directory.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ContentError(f"{path}: root must be a YAML mapping.")
        result.append((path, raw))
    return result


def _required_string(raw: dict[str, Any], key: str, path: Path) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ContentError(f"{path}: {key} must be a non-empty string.")
    return value.strip()


def load_content_registry(content_root: str | Path) -> ContentRegistry:
    root = Path(content_root)

    skills: dict[str, SkillDefinition] = {}
    for path, raw in _load_yaml_files(root / "skills"):
        skill_id = _required_string(raw, "id", path)
        if skill_id in skills:
            raise ContentError(f"{path}: duplicate skill id {skill_id!r}.")

        skill_type = _required_string(raw, "type", path)
        if skill_type not in ALLOWED_SKILL_TYPES:
            raise ContentError(
                f"{path}: unsupported skill type {skill_type!r}. "
                f"Allowed: {sorted(ALLOWED_SKILL_TYPES)}"
            )

        parameters = raw.get("parameters", {})
        if not isinstance(parameters, dict):
            raise ContentError(f"{path}: parameters must be a mapping.")

        cooldown = raw.get("cooldown_seconds", 0)
        if not isinstance(cooldown, int) or cooldown < 0:
            raise ContentError(f"{path}: cooldown_seconds must be >= 0.")

        skills[skill_id] = SkillDefinition(
            id=skill_id,
            name=_required_string(raw, "name", path),
            type=skill_type,
            description=_required_string(raw, "description", path),
            implementation=_required_string(raw, "implementation", path),
            cooldown_seconds=cooldown,
            parameters=parameters,
        )

    characters: dict[str, CharacterDefinition] = {}
    for path, raw in _load_yaml_files(root / "characters"):
        character_id = _required_string(raw, "id", path)
        if character_id in characters:
            raise ContentError(f"{path}: duplicate character id {character_id!r}.")

        raw_skills = raw.get("skills", [])
        if not isinstance(raw_skills, list) or not all(
            isinstance(item, str) and item.strip() for item in raw_skills
        ):
            raise ContentError(f"{path}: skills must be a list of skill IDs.")

        missing = [skill_id for skill_id in raw_skills if skill_id not in skills]
        if missing:
            raise ContentError(
                f"{path}: references unknown skill IDs: {', '.join(missing)}"
            )

        raw_tags = raw.get("tags", [])
        if not isinstance(raw_tags, list) or not all(
            isinstance(item, str) and item.strip() for item in raw_tags
        ):
            raise ContentError(f"{path}: tags must be a list of strings.")

        characters[character_id] = CharacterDefinition(
            id=character_id,
            name=_required_string(raw, "name", path),
            rarity=_required_string(raw, "rarity", path),
            description=_required_string(raw, "description", path),
            skills=tuple(raw_skills),
            tags=tuple(raw_tags),
        )

    gacha: dict[str, GachaDefinition] = {}
    for path, raw in _load_yaml_files(root / "gacha"):
        gacha_id = _required_string(raw, "id", path)
        if gacha_id in gacha:
            raise ContentError(f"{path}: duplicate gacha id {gacha_id!r}.")

        cost = raw.get("cost")
        if not isinstance(cost, int) or cost < 0:
            raise ContentError(f"{path}: cost must be an integer >= 0.")

        raw_entries = raw.get("entries")
        if not isinstance(raw_entries, list) or not raw_entries:
            raise ContentError(f"{path}: entries must be a non-empty list.")

        entries: list[GachaEntry] = []
        for index, entry in enumerate(raw_entries):
            if not isinstance(entry, dict):
                raise ContentError(f"{path}: entries[{index}] must be a mapping.")

            character_id = entry.get("character")
            if not isinstance(character_id, str) or character_id not in characters:
                raise ContentError(
                    f"{path}: entries[{index}] references unknown character "
                    f"{character_id!r}."
                )

            weight = entry.get("weight")
            if not isinstance(weight, (int, float)) or weight <= 0:
                raise ContentError(
                    f"{path}: entries[{index}].weight must be greater than 0."
                )

            entries.append(GachaEntry(character=character_id, weight=float(weight)))

        gacha[gacha_id] = GachaDefinition(
            id=gacha_id,
            name=_required_string(raw, "name", path),
            currency=_required_string(raw, "currency", path),
            cost=cost,
            entries=tuple(entries),
        )

    return ContentRegistry(skills=skills, characters=characters, gacha=gacha)
