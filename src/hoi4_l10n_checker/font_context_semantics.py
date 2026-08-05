from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Iterator

from .font_context_paths import effective_data_files
from .font_context_types import (
    ROLE_BATTLEPLAN_NAME,
    ROLE_CHARACTER_DESCRIPTION,
    ROLE_CHARACTER_NAME,
    ROLE_COUNTRY_NAME,
    ROLE_DECISION_CATEGORY_DESCRIPTION,
    ROLE_DECISION_CATEGORY_NAME,
    ROLE_DECISION_COST,
    ROLE_DECISION_DESCRIPTION,
    ROLE_DECISION_NAME,
    ROLE_EQUIPMENT_AIR_NAME,
    ROLE_EQUIPMENT_DESCRIPTION,
    ROLE_EQUIPMENT_LAND_NAME,
    ROLE_EQUIPMENT_NAVAL_NAME,
    ROLE_EQUIPMENT_RAILWAY_NAME,
    ROLE_EVENT_DESCRIPTION,
    ROLE_EVENT_OPTION,
    ROLE_EVENT_TITLE,
    ROLE_FOCUS_DESCRIPTION,
    ROLE_FOCUS_NAME,
    ROLE_IDEA_DESCRIPTION,
    ROLE_IDEA_SELECTABLE_NAME,
    ROLE_IDEA_SPIRIT_NAME,
    ROLE_MIO_NAME,
    ROLE_PARTY_NAME,
    ROLE_STATE_NAME,
    ROLE_TECHNOLOGY_DESCRIPTION,
    ROLE_TECHNOLOGY_NAME,
    ROLE_TOOLTIP,
    ROLE_VICTORY_POINT_NAME,
    RoleEvidence,
    record_role_evidence,
)
from .paradox_script import (
    ParsedBlock,
    has_ancestor_kind,
    read_script_blocks,
    token_value,
    tokenize_script,
)

__all__ = [
    "collect_semantic_context",
]

_PARTY_KEY = re.compile(r"(?:^|_)party(?:_|$)", re.IGNORECASE)
_CHARACTER_ROLE_BLOCKS = frozenset(
    {
        "add_advisor_role",
        "add_corps_commander_role",
        "add_country_leader_role",
        "add_field_marshal_role",
        "add_naval_commander_role",
        "create_corps_commander",
        "create_country_leader",
        "create_field_marshal",
        "create_navy_leader",
        "generate_character",
        "promote_character",
        "set_country_leader_description",
    }
)
_SCRIPT_TOOLTIP_PROPERTIES = frozenset(
    {
        "custom_effect_tooltip",
        "custom_trigger_tooltip",
        "tooltip",
    }
)
_EVENT_BLOCKS = frozenset(
    {
        "border_event",
        "country_event",
        "news_event",
        "operative_leader_event",
        "state_event",
        "unit_leader_event",
    }
)
_FOCUS_BLOCKS = frozenset({"focus", "shared_focus", "joint_focus"})
_SPIRIT_IDEA_CATEGORIES = frozenset({"country", "hidden_ideas"})
_DATABASE_WRAPPERS = frozenset({"equipments", "technologies"})


def _description_keys_by_owner(
    localisation_keys: frozenset[str],
) -> dict[str, set[str]]:
    result: dict[str, set[str]] = defaultdict(set)
    dlc_suffixes = (
        "_aat",
        "_bba",
        "_dod",
        "_got",
        "_lar",
        "_mtg",
        "_nsb",
        "_toa",
        "_wtt",
    )
    for key in localisation_keys:
        if not key.casefold().endswith("_desc"):
            continue
        owner = key[:-5]
        result[owner].add(key)
        owner_folded = owner.casefold()
        for suffix in dlc_suffixes:
            if owner_folded.endswith(suffix):
                result[owner[: -len(suffix)]].add(key)
    return result


def _database_keys_by_identifier(
    localisation_keys: frozenset[str],
) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    names: dict[str, set[str]] = defaultdict(set)
    descriptions: dict[str, set[str]] = defaultdict(set)
    for key in localisation_keys:
        folded = key.casefold()
        is_description = folded.endswith("_desc")
        core = key[:-5] if is_description else key
        if core.casefold().endswith("_short"):
            core = core[:-6]

        candidates = {core}
        if len(core) > 4 and core[3] == "_" and core[:3].isalnum():
            candidates.add(core[4:])

        destination = descriptions if is_description else names
        for candidate in candidates:
            destination[candidate].add(key)
    return names, descriptions


def _equipment_name_role(
    identifier: str,
    block: ParsedBlock | None = None,
) -> str:
    hints = [identifier.casefold()]
    if block is not None:
        for property_name in ("archetype", "type"):
            hints.extend(
                value.casefold() for value in block.properties.get(property_name, [])
            )
    combined = " ".join(hints)

    if "railway_gun" in combined:
        return ROLE_EQUIPMENT_RAILWAY_NAME
    if any(
        marker in combined
        for marker in (
            "airframe",
            "bomber",
            "fighter",
            "interceptor",
            "plane",
        )
    ):
        return ROLE_EQUIPMENT_AIR_NAME
    if any(
        marker in combined
        for marker in (
            "battleship",
            "carrier",
            "cruiser",
            "destroyer",
            "ship_hull",
            "submarine",
        )
    ):
        return ROLE_EQUIPMENT_NAVAL_NAME
    return ROLE_EQUIPMENT_LAND_NAME


def collect_semantic_context(
    mod_root: Path,
    game_root: Path | None,
    localisation_keys: frozenset[str],
    role_fonts: dict[str, set[str]],
    destination: dict[str, set[str]],
    key_roles: dict[str, set[str]],
    role_evidence: dict[tuple[str, str], set[RoleEvidence]],
    read_errors: list[str],
) -> tuple[int, frozenset[str]]:
    semantic_keys: set[str] = set()
    description_owners = _description_keys_by_owner(localisation_keys)
    database_names, database_descriptions = _database_keys_by_identifier(
        localisation_keys
    )
    script_files_checked = 0

    def bind(
        key: str,
        role: str,
        *,
        confidence: str = "",
        rule: str = "",
        block: ParsedBlock | None = None,
        property_name: str = "",
        property_value: str = "",
        source_path: Path | None = None,
        line: int = 0,
    ) -> None:
        if key not in localisation_keys:
            return
        key_roles[key].add(role)
        if confidence and rule:
            record_role_evidence(
                role_evidence,
                key,
                role,
                confidence,
                rule,
                block=block,
                property_name=property_name,
                property_value=property_value or key,
                source_path=source_path,
                line=line,
            )
        fonts = role_fonts.get(role, set())
        if not fonts:
            return
        destination[key].update(fonts)
        semantic_keys.add(key)

    def bind_descriptions(
        identifier: str,
        role: str,
        *,
        confidence: str = "",
        rule: str = "",
        block: ParsedBlock | None = None,
        property_name: str = "",
        property_value: str = "",
    ) -> None:
        for key in description_owners.get(identifier, ()):
            bind(
                key,
                role,
                confidence=confidence,
                rule=rule,
                block=block,
                property_name=property_name,
                property_value=property_value,
            )

    def blocks_for(relative_root: str) -> Iterator[list[ParsedBlock]]:
        nonlocal script_files_checked
        for path in effective_data_files(
            mod_root,
            game_root,
            relative_root,
        ):
            script_files_checked += 1
            blocks = read_script_blocks(path, read_errors)
            for block in blocks:
                kind = block.kind.casefold()
                for property_name in _SCRIPT_TOOLTIP_PROPERTIES:
                    for key in block.properties.get(property_name, []):
                        bind(key, ROLE_TOOLTIP)
                if kind == "set_province_name":
                    for key in block.properties.get("name", []):
                        bind(key, ROLE_VICTORY_POINT_NAME)
                if kind == "set_state_name":
                    for key in block.properties.get("name", []):
                        bind(key, ROLE_STATE_NAME)
                for key in block.properties.get("set_character_name", []):
                    bind(key, ROLE_CHARACTER_NAME)
                for key in block.properties.get("custom_cost_text", []):
                    for candidate in (
                        key,
                        f"{key}_blocked",
                        f"{key}_tooltip",
                    ):
                        bind(candidate, ROLE_DECISION_COST)
                in_character_role = kind in _CHARACTER_ROLE_BLOCKS or has_ancestor_kind(
                    block, _CHARACTER_ROLE_BLOCKS
                )
                if in_character_role:
                    for key in block.properties.get("name", []):
                        bind(key, ROLE_CHARACTER_NAME)
                    for key in block.properties.get("desc", []):
                        bind(key, ROLE_CHARACTER_DESCRIPTION)
                if kind == "set_party_name":
                    for property_name in ("name", "long_name"):
                        for key in block.properties.get(property_name, []):
                            bind(key, ROLE_PARTY_NAME)
            yield blocks

    for blocks in blocks_for("common/ideas"):
        for block in blocks:
            parent = block.parent
            if (
                parent is None
                or parent.parent is None
                or parent.parent.kind.casefold() != "ideas"
            ):
                continue
            idea_id = block.kind
            category = parent.kind.casefold()
            name_role = (
                ROLE_IDEA_SPIRIT_NAME
                if category in _SPIRIT_IDEA_CATEGORIES
                else ROLE_IDEA_SELECTABLE_NAME
            )
            bind(idea_id, name_role)
            bind_descriptions(idea_id, ROLE_IDEA_DESCRIPTION)
            for key in block.properties.get("name", []):
                bind(key, name_role)
                bind_descriptions(key, ROLE_IDEA_DESCRIPTION)

    for relative_root in (
        "common/national_focus",
        "common/continuous_focus",
    ):
        for blocks in blocks_for(relative_root):
            for block in blocks:
                if block.kind.casefold() in _FOCUS_BLOCKS:
                    for focus_id in block.properties.get("id", []):
                        bind(
                            focus_id,
                            ROLE_FOCUS_NAME,
                            confidence="confirmed",
                            rule=(
                                f"Ключ совпадает с id существующего блока {block.kind}."
                            ),
                            block=block,
                            property_name="id",
                            property_value=focus_id,
                        )
                        bind_descriptions(
                            focus_id,
                            ROLE_FOCUS_DESCRIPTION,
                            confidence="structural",
                            rule=(
                                "Описание связано с существующим фокусом "
                                f"id = {focus_id} по правилу id + _desc."
                            ),
                            block=block,
                            property_name="id",
                            property_value=focus_id,
                        )
                if has_ancestor_kind(block, _FOCUS_BLOCKS):
                    for key in block.properties.get("localization_key", []):
                        bind(
                            key,
                            ROLE_FOCUS_NAME,
                            confidence="confirmed",
                            rule=(
                                "Ключ явно указан в localization_key "
                                "внутри блока фокуса."
                            ),
                            block=block,
                            property_name="localization_key",
                        )

    for blocks in blocks_for("common/decisions"):
        for block in blocks:
            if block.parent is None:
                bind(block.kind, ROLE_DECISION_CATEGORY_NAME)
                bind_descriptions(
                    block.kind,
                    ROLE_DECISION_CATEGORY_DESCRIPTION,
                )
                continue
            if block.parent.parent is None:
                bind(block.kind, ROLE_DECISION_NAME)
                bind_descriptions(
                    block.kind,
                    ROLE_DECISION_DESCRIPTION,
                )

    for blocks in blocks_for("common/characters"):
        for block in blocks:
            for key in block.properties.get("name", []):
                bind(key, ROLE_CHARACTER_NAME)
                bind_descriptions(key, ROLE_CHARACTER_DESCRIPTION)
            for key in block.properties.get("desc", []):
                bind(key, ROLE_CHARACTER_DESCRIPTION)
            for key in block.properties.get("idea_token", []):
                bind(key, ROLE_CHARACTER_NAME)
                bind_descriptions(key, ROLE_CHARACTER_DESCRIPTION)

    for blocks in blocks_for("common/country_leader"):
        for block in blocks:
            bind(block.kind, ROLE_TOOLTIP)
            bind_descriptions(block.kind, ROLE_TOOLTIP)
            for key in block.properties.get("name", []):
                bind(key, ROLE_CHARACTER_NAME)
                bind_descriptions(key, ROLE_CHARACTER_DESCRIPTION)
            for key in block.properties.get("desc", []):
                bind(key, ROLE_CHARACTER_DESCRIPTION)

    for blocks in blocks_for("common/unit_leader"):
        for block in blocks:
            bind(block.kind, ROLE_TOOLTIP)
            bind_descriptions(block.kind, ROLE_TOOLTIP)

    for blocks in blocks_for("common/military_industrial_organization/organizations"):
        for block in blocks:
            bind(block.kind, ROLE_MIO_NAME)
            for key in block.properties.get("name", []):
                bind(key, ROLE_MIO_NAME)

    for blocks in blocks_for("common/technologies"):
        for block in blocks:
            if block.parent is None or block.parent.kind.casefold() != "technologies":
                continue
            technology_id = block.kind
            for key in database_names.get(technology_id, ()):
                bind(key, ROLE_TECHNOLOGY_NAME)
            for key in database_descriptions.get(technology_id, ()):
                bind(key, ROLE_TECHNOLOGY_DESCRIPTION)

    equipment_ids: set[str] = set()
    for blocks in blocks_for("common/units/equipment"):
        for block in blocks:
            if block.parent is None or block.parent.kind.casefold() != "equipments":
                continue
            equipment_id = block.kind
            equipment_ids.add(equipment_id)
            name_role = _equipment_name_role(equipment_id, block)
            for key in database_names.get(equipment_id, ()):
                bind(key, name_role)
            for key in database_descriptions.get(equipment_id, ()):
                bind(key, ROLE_EQUIPMENT_DESCRIPTION)

    for equipment_id in database_names:
        if equipment_id in equipment_ids:
            continue
        folded = equipment_id.casefold()
        if "_equipment_" not in folded and "_airframe_" not in folded:
            continue
        for key in database_names[equipment_id]:
            bind(key, _equipment_name_role(equipment_id))

    for blocks in blocks_for("events"):
        for block in blocks:
            kind = block.kind.casefold()
            if kind in _EVENT_BLOCKS:
                for key in block.properties.get("title", []):
                    bind(
                        key,
                        ROLE_EVENT_TITLE,
                        confidence="confirmed",
                        rule=(f"Ключ явно указан в title блока {block.kind}."),
                        block=block,
                        property_name="title",
                    )
                for key in block.properties.get("desc", []):
                    bind(
                        key,
                        ROLE_EVENT_DESCRIPTION,
                        confidence="confirmed",
                        rule=(f"Ключ явно указан в desc блока {block.kind}."),
                        block=block,
                        property_name="desc",
                    )
                continue
            if not has_ancestor_kind(block, _EVENT_BLOCKS):
                continue
            if kind == "desc":
                for key in block.properties.get("text", []):
                    bind(
                        key,
                        ROLE_EVENT_DESCRIPTION,
                        confidence="confirmed",
                        rule=("Ключ явно указан в text условного описания ивента."),
                        block=block,
                        property_name="text",
                    )
            if kind == "option":
                for key in block.properties.get("name", []):
                    bind(
                        key,
                        ROLE_EVENT_OPTION,
                        confidence="confirmed",
                        rule=("Ключ явно указан в name варианта ответа ивента."),
                        block=block,
                        property_name="name",
                    )

    for key in localisation_keys:
        if key.casefold().startswith("victory_points_"):
            bind(key, ROLE_VICTORY_POINT_NAME)
        if _PARTY_KEY.search(key):
            bind(key, ROLE_PARTY_NAME)

    for path in effective_data_files(
        mod_root,
        game_root,
        "common/names",
    ):
        script_files_checked += 1
        try:
            tokens = tokenize_script(
                path.read_text(encoding="utf-8-sig", errors="replace")
            )
        except OSError as error:
            read_errors.append(f"Не удалось прочитать {path}: {error}")
            continue
        for token in tokens:
            key = token_value(token)
            if key in localisation_keys:
                bind(key, ROLE_BATTLEPLAN_NAME)

    country_tags: set[str] = set()
    for blocks in blocks_for("common/countries"):
        country_tags.update(block.kind for block in blocks if block.parent is None)
    for tag in country_tags:
        for ideology in (
            "communism",
            "democratic",
            "fascism",
            "neutrality",
        ):
            base = f"{tag}_{ideology}"
            for suffix in ("", "_DEF", "_ADJ"):
                bind(f"{base}{suffix}", ROLE_COUNTRY_NAME)

    return script_files_checked, frozenset(semantic_keys)
