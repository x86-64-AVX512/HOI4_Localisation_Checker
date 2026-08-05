from __future__ import annotations

import re
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Mapping

from .font_context_paths import (
    effective_data_files as _effective_data_files,
)
from .font_context_paths import (
    effective_gui_files as _effective_gui_files,
)
from .font_context_paths import (
    find_hoi4_install,
    find_mod_root,
    is_context_root,
    mod_display_name,
)
from .paradox_script import (
    ParsedBlock as _ParsedBlock,
)
from .paradox_script import (
    ancestor_names as _ancestor_names,
)
from .paradox_script import (
    block_name as _block_name,
)
from .paradox_script import (
    font_names as _font_names,
)
from .paradox_script import (
    has_ancestor_kind as _has_ancestor_kind,
)
from .paradox_script import (
    localisation_calls as _localisation_calls,
)
from .paradox_script import (
    parse_blocks as _parse_blocks,
)
from .paradox_script import (
    property_line as _property_line,
)
from .paradox_script import (
    token_value as _token_value,
)
from .paradox_script import (
    tokenize_script as _tokenize_script,
)

__all__ = [
    "FontContextIndex",
    "ROLE_EVENT_DESCRIPTION",
    "ROLE_FOCUS_DESCRIPTION",
    "ROLE_WELCOME_TEXT",
    "RoleEvidence",
    "build_font_context",
    "find_hoi4_install",
    "find_mod_root",
    "is_context_root",
    "mod_display_name",
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
_DIRECT_TEXT_PROPERTIES = frozenset({"text", "buttontext"})
_TOOLTIP_PROPERTIES = frozenset(
    {
        "context_aware_tooltip",
        "pdx_tooltip",
        "pdx_tooltip_delayed",
        "tooltip",
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
_EQUIPMENT_WIDGET_NAMES = frozenset(
    {
        "equipment_name",
        "equipment_type",
        "equipment_variant",
        "ship_type",
        "variant_name",
    }
)

_ROLE_TOOLTIP = "tooltip"
_ROLE_IDEA_SPIRIT_NAME = "idea_spirit_name"
_ROLE_IDEA_SELECTABLE_NAME = "idea_selectable_name"
_ROLE_IDEA_DESCRIPTION = "idea_description"
_ROLE_FOCUS_NAME = "focus_name"
_ROLE_FOCUS_DESCRIPTION = "focus_description"
_ROLE_EVENT_TITLE = "event_title"
_ROLE_EVENT_DESCRIPTION = "event_description"
_ROLE_EVENT_OPTION = "event_option"
_ROLE_DECISION_NAME = "decision_name"
_ROLE_DECISION_DESCRIPTION = "decision_description"
_ROLE_DECISION_CATEGORY_NAME = "decision_category_name"
_ROLE_DECISION_CATEGORY_DESCRIPTION = "decision_category_description"
_ROLE_TECHNOLOGY_NAME = "technology_name"
_ROLE_TECHNOLOGY_DESCRIPTION = "technology_description"
_ROLE_EQUIPMENT_LAND_NAME = "equipment_land_name"
_ROLE_EQUIPMENT_AIR_NAME = "equipment_air_name"
_ROLE_EQUIPMENT_NAVAL_NAME = "equipment_naval_name"
_ROLE_EQUIPMENT_RAILWAY_NAME = "equipment_railway_name"
_ROLE_EQUIPMENT_DESCRIPTION = "equipment_description"
_ROLE_BATTLEPLAN_NAME = "battleplan_name"
_ROLE_VICTORY_POINT_NAME = "victory_point_name"
_ROLE_COUNTRY_NAME = "country_name"
_ROLE_PARTY_NAME = "party_name"
_ROLE_STATE_NAME = "state_name"
_ROLE_CHARACTER_NAME = "character_name"
_ROLE_CHARACTER_DESCRIPTION = "character_description"
_ROLE_DECISION_COST = "decision_cost"
_ROLE_MIO_NAME = "mio_name"
ROLE_FOCUS_DESCRIPTION = _ROLE_FOCUS_DESCRIPTION
ROLE_EVENT_DESCRIPTION = _ROLE_EVENT_DESCRIPTION
ROLE_WELCOME_TEXT = "welcome_text"


@dataclass(frozen=True, slots=True)
class RoleEvidence:
    role: str
    confidence: str
    source_path: Path | None
    line: int
    rule: str

    def sort_key(self) -> tuple[int, str, int, str]:
        confidence_order = {
            "confirmed": 0,
            "structural": 1,
            "probable": 2,
        }
        return (
            confidence_order.get(self.confidence, 9),
            str(self.source_path or "").casefold(),
            self.line,
            self.rule.casefold(),
        )


@dataclass(frozen=True, slots=True)
class FontContextIndex:
    mod_root: Path
    game_root: Path | None
    key_fonts: dict[str, frozenset[str]]
    key_roles: dict[str, frozenset[str]]
    role_evidence: dict[tuple[str, str], tuple[RoleEvidence, ...]]
    gui_files_checked: int
    script_files_checked: int = 0
    semantic_keys: frozenset[str] = frozenset()
    read_errors: tuple[str, ...] = ()

    def fonts_for_key(self, key: str) -> frozenset[str]:
        return self.key_fonts.get(key, frozenset())

    def roles_for_key(self, key: str) -> frozenset[str]:
        return self.key_roles.get(key, frozenset())

    def evidence_for_role(
        self,
        key: str,
        role: str,
    ) -> tuple[RoleEvidence, ...]:
        return self.role_evidence.get((key, role), ())

    @property
    def resolved_key_count(self) -> int:
        return len(self.key_fonts)

    @property
    def semantic_resolved_key_count(self) -> int:
        return len(self.semantic_keys)


def _record_role_evidence(
    destination: dict[tuple[str, str], set[RoleEvidence]],
    key: str,
    role: str,
    confidence: str,
    rule: str,
    block: _ParsedBlock | None = None,
    property_name: str = "",
    property_value: str = "",
    source_path: Path | None = None,
    line: int = 0,
) -> None:
    if block is not None:
        source_path = block.source_path
        line = (
            _property_line(block, property_name, property_value)
            if property_name
            else block.line
        )
    destination[(key, role)].add(
        RoleEvidence(
            role=role,
            confidence=confidence,
            source_path=source_path,
            line=max(line, 0),
            rule=rule,
        )
    )


def _index_gui_blocks(
    blocks: Iterable[_ParsedBlock],
    localisation_keys: frozenset[str],
    destination: dict[str, set[str]],
    key_roles: dict[str, set[str]],
    role_evidence: dict[tuple[str, str], set[RoleEvidence]],
    role_fonts: dict[str, set[str]],
    tooltip_keys: set[str],
    dynamic_function_fonts: dict[str, set[str]],
    dynamic_function_roles: dict[str, set[str]],
) -> None:
    decision_templates = frozenset(
        {
            "decision_item",
            "on_map_decision_locator_item",
            "targeted_decision_item",
            "timed_decision_item",
        }
    )
    focus_name_templates = frozenset(
        {
            "coninuous_focus_detail_view",
            "continuous_national_focus_item",
            "focus_tree_shortcut_item",
            "national_focus_detail_view",
            "national_focus_item",
        }
    )
    focus_description_templates = frozenset(
        {
            "coninuous_focus_detail_view",
            "continuous_national_focus_item",
            "national_focus_detail_view",
        }
    )

    for block in blocks:
        fonts = _font_names(block)
        name = _block_name(block).casefold()
        ancestors = frozenset(_ancestor_names(block))
        welcome_context = any(
            "welcome_screen" in candidate or "_ws_" in f"_{candidate}_"
            for candidate in ancestors
        )
        welcome_body = (
            welcome_context and re.fullmatch(r"tab_\d+_text", name) is not None
        )

        if welcome_body:
            role_fonts[ROLE_WELCOME_TEXT].update(fonts)
            for property_name in _DIRECT_TEXT_PROPERTIES:
                for text in block.properties.get(property_name, []):
                    if text in localisation_keys:
                        key_roles[text].add(ROLE_WELCOME_TEXT)
                        _record_role_evidence(
                            role_evidence,
                            text,
                            ROLE_WELCOME_TEXT,
                            "confirmed",
                            (
                                "Ключ напрямую назначен основному текстовому "
                                "полю вступительного экрана."
                            ),
                            block=block,
                            property_name=property_name,
                            property_value=text,
                        )
                    for function_name in _localisation_calls(text):
                        dynamic_function_roles[function_name].add(ROLE_WELCOME_TEXT)

        if fonts:
            for property_name in _DIRECT_TEXT_PROPERTIES:
                for text in block.properties.get(property_name, []):
                    if text in localisation_keys:
                        destination[text].update(fonts)
                    for function_name in _localisation_calls(text):
                        dynamic_function_fonts[function_name].update(fonts)

        for property_name in _TOOLTIP_PROPERTIES:
            for key in block.properties.get(property_name, []):
                if key in localisation_keys:
                    tooltip_keys.add(key)

        if not fonts or not name:
            continue

        if name == "tooltip":
            role_fonts[_ROLE_TOOLTIP].update(fonts)

        text_values = {
            value.casefold()
            for property_name in _DIRECT_TEXT_PROPERTIES
            for value in block.properties.get(property_name, [])
        }
        if name == "operation_name" and "battleplantools_window" in ancestors:
            role_fonts[_ROLE_BATTLEPLAN_NAME].update(fonts)
        if name == "text" and ancestors.intersection(
            {"victory_point_mapicon", "capital_mapicon"}
        ):
            role_fonts[_ROLE_VICTORY_POINT_NAME].update(fonts)
        if name == "party_name" or "party name" in text_values:
            role_fonts[_ROLE_PARTY_NAME].update(fonts)
        if "country_name" in name or "country name" in text_values:
            role_fonts[_ROLE_COUNTRY_NAME].update(fonts)
        if name in {"state_name", "state name"}:
            role_fonts[_ROLE_STATE_NAME].update(fonts)
        if name == "cost_and_timer_text":
            role_fonts[_ROLE_DECISION_COST].update(fonts)
        if "mio name" in text_values:
            role_fonts[_ROLE_MIO_NAME].update(fonts)

        character_markers = (
            "advisor",
            "character",
            "commander",
            "leader",
            "operative",
        )
        character_context = any(
            marker in candidate
            for candidate in (name, *ancestors)
            for marker in character_markers
        )
        event_context = any(
            "eventwindow" in ancestor or "event_window" in ancestor
            for ancestor in ancestors
        )
        if (
            character_context
            and not event_context
            and (
                name == "name"
                or name.endswith("_name")
                or any("name" in value for value in text_values)
            )
        ):
            role_fonts[_ROLE_CHARACTER_NAME].update(fonts)
        if (
            character_context
            and not event_context
            and (
                name in {"desc", "description"}
                or name.endswith(("_desc", "_description"))
            )
        ):
            role_fonts[_ROLE_CHARACTER_DESCRIPTION].update(fonts)

        in_event_window = any(
            ancestor.startswith("eventwindow") for ancestor in ancestors
        )
        if in_event_window and name == "title":
            role_fonts[_ROLE_EVENT_TITLE].update(fonts)
        if in_event_window and name == "description":
            role_fonts[_ROLE_EVENT_DESCRIPTION].update(fonts)
        if name == "name" and "event_option_entry" in ancestors:
            role_fonts[_ROLE_EVENT_OPTION].update(fonts)
        if name == "name_text" and "event_item" in ancestors:
            role_fonts[_ROLE_EVENT_TITLE].update(fonts)

        if name == "name" and ancestors.intersection(focus_name_templates):
            role_fonts[_ROLE_FOCUS_NAME].update(fonts)
        if name == "desc" and ancestors.intersection(focus_description_templates):
            role_fonts[_ROLE_FOCUS_DESCRIPTION].update(fonts)

        if name == "name" and any(
            ancestor.startswith("political_selectable_idea_entry")
            for ancestor in ancestors
        ):
            role_fonts[_ROLE_IDEA_SELECTABLE_NAME].update(fonts)

        if name == "name_text" and ancestors.intersection(decision_templates):
            role_fonts[_ROLE_DECISION_NAME].update(fonts)
        if name == "name_text" and "category_header" in ancestors:
            role_fonts[_ROLE_DECISION_CATEGORY_NAME].update(fonts)
        if (
            name in {"full_text", "short_text"}
            and "decision_category_desc" in ancestors
        ):
            role_fonts[_ROLE_DECISION_CATEGORY_DESCRIPTION].update(fonts)

        if name == "tech_info_title":
            role_fonts[_ROLE_TECHNOLOGY_NAME].update(fonts)
        if name == "tech_info_description":
            role_fonts[_ROLE_TECHNOLOGY_DESCRIPTION].update(fonts)
        if name == "name" and any(
            ancestor.startswith("techtree_") and ancestor.endswith("_item")
            for ancestor in ancestors
        ):
            role_fonts[_ROLE_TECHNOLOGY_NAME].update(fonts)

        is_equipment_name = name in _EQUIPMENT_WIDGET_NAMES or (
            name == "name"
            and any(
                marker in ancestor
                for ancestor in ancestors
                for marker in (
                    "designer_equipment_entry",
                    "equipment_archetype_entry",
                    "equipment_entry",
                    "equipment_info_entry",
                    "equipment_list_item",
                    "equipment_stockpile",
                    "production_military_line_entry",
                    "production_naval_line_entry",
                    "production_railway_gun_line_entry",
                    "production_ship_refit_line_entry",
                )
            )
        )
        if is_equipment_name:
            if "stat_equipment_entry_large" in ancestors or any(
                "air_wing" in ancestor for ancestor in ancestors
            ):
                equipment_roles = (_ROLE_EQUIPMENT_AIR_NAME,)
            elif "stat_equipment_entry_naval" in ancestors:
                equipment_roles = (_ROLE_EQUIPMENT_NAVAL_NAME,)
            elif "stat_equipment_entry_railway_gun" in ancestors:
                equipment_roles = (_ROLE_EQUIPMENT_RAILWAY_NAME,)
            elif "stat_equipment_entry" in ancestors:
                equipment_roles = (_ROLE_EQUIPMENT_LAND_NAME,)
            else:
                equipment_roles = (
                    _ROLE_EQUIPMENT_LAND_NAME,
                    _ROLE_EQUIPMENT_AIR_NAME,
                    _ROLE_EQUIPMENT_NAVAL_NAME,
                    _ROLE_EQUIPMENT_RAILWAY_NAME,
                )
            for role in equipment_roles:
                role_fonts[role].update(fonts)


def _merge_tooltip_roles(role_fonts: dict[str, set[str]]) -> None:
    tooltip_fonts = role_fonts[_ROLE_TOOLTIP]
    for role in (
        _ROLE_IDEA_SPIRIT_NAME,
        _ROLE_IDEA_SELECTABLE_NAME,
        _ROLE_IDEA_DESCRIPTION,
        _ROLE_FOCUS_NAME,
        _ROLE_FOCUS_DESCRIPTION,
        _ROLE_DECISION_NAME,
        _ROLE_DECISION_DESCRIPTION,
        _ROLE_TECHNOLOGY_NAME,
        _ROLE_TECHNOLOGY_DESCRIPTION,
        _ROLE_EQUIPMENT_LAND_NAME,
        _ROLE_EQUIPMENT_AIR_NAME,
        _ROLE_EQUIPMENT_NAVAL_NAME,
        _ROLE_EQUIPMENT_RAILWAY_NAME,
        _ROLE_EQUIPMENT_DESCRIPTION,
        _ROLE_CHARACTER_NAME,
        _ROLE_CHARACTER_DESCRIPTION,
        _ROLE_MIO_NAME,
    ):
        role_fonts[role].update(tooltip_fonts)


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


def _read_script_blocks(
    path: Path,
    read_errors: list[str],
) -> list[_ParsedBlock]:
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError as error:
        read_errors.append(f"Не удалось прочитать {path}: {error}")
        return []
    return _parse_blocks(text, source_path=path)


def _equipment_name_role(
    identifier: str,
    block: _ParsedBlock | None = None,
) -> str:
    hints = [identifier.casefold()]
    if block is not None:
        for property_name in ("archetype", "type"):
            hints.extend(
                value.casefold() for value in block.properties.get(property_name, [])
            )
    combined = " ".join(hints)

    if "railway_gun" in combined:
        return _ROLE_EQUIPMENT_RAILWAY_NAME
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
        return _ROLE_EQUIPMENT_AIR_NAME
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
        return _ROLE_EQUIPMENT_NAVAL_NAME
    return _ROLE_EQUIPMENT_LAND_NAME


def _collect_semantic_context(
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
        block: _ParsedBlock | None = None,
        property_name: str = "",
        property_value: str = "",
        source_path: Path | None = None,
        line: int = 0,
    ) -> None:
        if key not in localisation_keys:
            return
        key_roles[key].add(role)
        if confidence and rule:
            _record_role_evidence(
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
        block: _ParsedBlock | None = None,
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

    def blocks_for(relative_root: str) -> Iterator[list[_ParsedBlock]]:
        nonlocal script_files_checked
        for path in _effective_data_files(
            mod_root,
            game_root,
            relative_root,
        ):
            script_files_checked += 1
            blocks = _read_script_blocks(path, read_errors)
            for block in blocks:
                kind = block.kind.casefold()
                for property_name in _SCRIPT_TOOLTIP_PROPERTIES:
                    for key in block.properties.get(property_name, []):
                        bind(key, _ROLE_TOOLTIP)
                if kind == "set_province_name":
                    for key in block.properties.get("name", []):
                        bind(key, _ROLE_VICTORY_POINT_NAME)
                if kind == "set_state_name":
                    for key in block.properties.get("name", []):
                        bind(key, _ROLE_STATE_NAME)
                for key in block.properties.get("set_character_name", []):
                    bind(key, _ROLE_CHARACTER_NAME)
                for key in block.properties.get("custom_cost_text", []):
                    for candidate in (
                        key,
                        f"{key}_blocked",
                        f"{key}_tooltip",
                    ):
                        bind(candidate, _ROLE_DECISION_COST)
                in_character_role = (
                    kind in _CHARACTER_ROLE_BLOCKS
                    or _has_ancestor_kind(block, _CHARACTER_ROLE_BLOCKS)
                )
                if in_character_role:
                    for key in block.properties.get("name", []):
                        bind(key, _ROLE_CHARACTER_NAME)
                    for key in block.properties.get("desc", []):
                        bind(key, _ROLE_CHARACTER_DESCRIPTION)
                if kind == "set_party_name":
                    for property_name in ("name", "long_name"):
                        for key in block.properties.get(property_name, []):
                            bind(key, _ROLE_PARTY_NAME)
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
                _ROLE_IDEA_SPIRIT_NAME
                if category in _SPIRIT_IDEA_CATEGORIES
                else _ROLE_IDEA_SELECTABLE_NAME
            )
            bind(idea_id, name_role)
            bind_descriptions(idea_id, _ROLE_IDEA_DESCRIPTION)
            for key in block.properties.get("name", []):
                bind(key, name_role)
                bind_descriptions(key, _ROLE_IDEA_DESCRIPTION)

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
                            _ROLE_FOCUS_NAME,
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
                            _ROLE_FOCUS_DESCRIPTION,
                            confidence="structural",
                            rule=(
                                "Описание связано с существующим фокусом "
                                f"id = {focus_id} по правилу id + _desc."
                            ),
                            block=block,
                            property_name="id",
                            property_value=focus_id,
                        )
                if _has_ancestor_kind(block, _FOCUS_BLOCKS):
                    for key in block.properties.get("localization_key", []):
                        bind(
                            key,
                            _ROLE_FOCUS_NAME,
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
                bind(block.kind, _ROLE_DECISION_CATEGORY_NAME)
                bind_descriptions(
                    block.kind,
                    _ROLE_DECISION_CATEGORY_DESCRIPTION,
                )
                continue
            if block.parent.parent is None:
                bind(block.kind, _ROLE_DECISION_NAME)
                bind_descriptions(
                    block.kind,
                    _ROLE_DECISION_DESCRIPTION,
                )

    for blocks in blocks_for("common/characters"):
        for block in blocks:
            for key in block.properties.get("name", []):
                bind(key, _ROLE_CHARACTER_NAME)
                bind_descriptions(key, _ROLE_CHARACTER_DESCRIPTION)
            for key in block.properties.get("desc", []):
                bind(key, _ROLE_CHARACTER_DESCRIPTION)
            for key in block.properties.get("idea_token", []):
                bind(key, _ROLE_CHARACTER_NAME)
                bind_descriptions(key, _ROLE_CHARACTER_DESCRIPTION)

    for blocks in blocks_for("common/country_leader"):
        for block in blocks:
            bind(block.kind, _ROLE_TOOLTIP)
            bind_descriptions(block.kind, _ROLE_TOOLTIP)
            for key in block.properties.get("name", []):
                bind(key, _ROLE_CHARACTER_NAME)
                bind_descriptions(key, _ROLE_CHARACTER_DESCRIPTION)
            for key in block.properties.get("desc", []):
                bind(key, _ROLE_CHARACTER_DESCRIPTION)

    for blocks in blocks_for("common/unit_leader"):
        for block in blocks:
            bind(block.kind, _ROLE_TOOLTIP)
            bind_descriptions(block.kind, _ROLE_TOOLTIP)

    for blocks in blocks_for("common/military_industrial_organization/organizations"):
        for block in blocks:
            bind(block.kind, _ROLE_MIO_NAME)
            for key in block.properties.get("name", []):
                bind(key, _ROLE_MIO_NAME)

    for blocks in blocks_for("common/technologies"):
        for block in blocks:
            if block.parent is None or block.parent.kind.casefold() != "technologies":
                continue
            technology_id = block.kind
            for key in database_names.get(technology_id, ()):
                bind(key, _ROLE_TECHNOLOGY_NAME)
            for key in database_descriptions.get(technology_id, ()):
                bind(key, _ROLE_TECHNOLOGY_DESCRIPTION)

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
                bind(key, _ROLE_EQUIPMENT_DESCRIPTION)

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
                        _ROLE_EVENT_TITLE,
                        confidence="confirmed",
                        rule=(f"Ключ явно указан в title блока {block.kind}."),
                        block=block,
                        property_name="title",
                    )
                for key in block.properties.get("desc", []):
                    bind(
                        key,
                        _ROLE_EVENT_DESCRIPTION,
                        confidence="confirmed",
                        rule=(f"Ключ явно указан в desc блока {block.kind}."),
                        block=block,
                        property_name="desc",
                    )
                continue
            if not _has_ancestor_kind(block, _EVENT_BLOCKS):
                continue
            if kind == "desc":
                for key in block.properties.get("text", []):
                    bind(
                        key,
                        _ROLE_EVENT_DESCRIPTION,
                        confidence="confirmed",
                        rule=("Ключ явно указан в text условного описания ивента."),
                        block=block,
                        property_name="text",
                    )
            if kind == "option":
                for key in block.properties.get("name", []):
                    bind(
                        key,
                        _ROLE_EVENT_OPTION,
                        confidence="confirmed",
                        rule=("Ключ явно указан в name варианта ответа ивента."),
                        block=block,
                        property_name="name",
                    )

    for key in localisation_keys:
        if key.casefold().startswith("victory_points_"):
            bind(key, _ROLE_VICTORY_POINT_NAME)
        if _PARTY_KEY.search(key):
            bind(key, _ROLE_PARTY_NAME)

    for path in _effective_data_files(
        mod_root,
        game_root,
        "common/names",
    ):
        script_files_checked += 1
        try:
            tokens = _tokenize_script(
                path.read_text(encoding="utf-8-sig", errors="replace")
            )
        except OSError as error:
            read_errors.append(f"Не удалось прочитать {path}: {error}")
            continue
        for token in tokens:
            key = _token_value(token)
            if key in localisation_keys:
                bind(key, _ROLE_BATTLEPLAN_NAME)

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
                bind(f"{base}{suffix}", _ROLE_COUNTRY_NAME)

    return script_files_checked, frozenset(semantic_keys)


def _defined_text_owner(block: _ParsedBlock) -> _ParsedBlock | None:
    current: _ParsedBlock | None = block
    while current is not None:
        if current.kind.casefold() == "defined_text":
            return current
        current = current.parent
    return None


def _collect_scripted_localisation_context(
    mod_root: Path,
    game_root: Path | None,
    localisation_keys: frozenset[str],
    localisation_values: Mapping[str, Iterable[str]],
    destination: dict[str, set[str]],
    key_roles: dict[str, set[str]],
    role_evidence: dict[tuple[str, str], set[RoleEvidence]],
    dynamic_function_fonts: dict[str, set[str]],
    dynamic_function_roles: dict[str, set[str]],
    read_errors: list[str],
) -> tuple[int, frozenset[str]]:
    definitions: dict[str, set[str]] = defaultdict(set)
    definition_sources: dict[
        tuple[str, str],
        set[tuple[Path | None, int]],
    ] = defaultdict(set)

    def expand_key(raw_key: str) -> set[str]:
        if raw_key in localisation_keys:
            return {raw_key}
        if "[" not in raw_key:
            return set()
        parts = re.split(r"\[[^\]]+\]", raw_key)
        if sum(len(part) for part in parts) < 4:
            return set()
        pattern = re.compile("^" + ".+".join(re.escape(part) for part in parts) + "$")
        return {key for key in localisation_keys if pattern.fullmatch(key)}

    files_checked = 0
    for path in _effective_data_files(
        mod_root,
        game_root,
        "common/scripted_localisation",
    ):
        files_checked += 1
        blocks = _read_script_blocks(path, read_errors)
        for block in blocks:
            owner = _defined_text_owner(block)
            if owner is None:
                continue
            names = owner.properties.get("name", [])
            if not names:
                continue
            for raw_key in block.properties.get("localization_key", []):
                matching_keys = expand_key(raw_key)
                for name in names:
                    definitions[name].update(matching_keys)
                    for key in matching_keys:
                        definition_sources[(name, key)].add(
                            (
                                block.source_path,
                                _property_line(
                                    block,
                                    "localization_key",
                                    raw_key,
                                ),
                            )
                        )

    calls_by_key: dict[str, frozenset[str]] = {}
    for key, values in localisation_values.items():
        calls = {call for value in values for call in _localisation_calls(value)}
        if calls:
            calls_by_key[key] = frozenset(calls)

    function_fonts: dict[str, set[str]] = defaultdict(set)
    function_queue: deque[str] = deque()
    queued: set[str] = set()

    def queue_function(name: str, fonts: Iterable[str]) -> None:
        before = len(function_fonts[name])
        function_fonts[name].update(fonts)
        if len(function_fonts[name]) == before or name in queued:
            return
        queued.add(name)
        function_queue.append(name)

    for name, fonts in dynamic_function_fonts.items():
        queue_function(name, fonts)
    for key, calls in calls_by_key.items():
        fonts = destination.get(key, set())
        if not fonts:
            continue
        for call in calls:
            queue_function(call, fonts)

    processed_fonts: dict[str, set[str]] = defaultdict(set)
    semantic_keys: set[str] = set()
    while function_queue:
        function_name = function_queue.popleft()
        queued.discard(function_name)
        new_fonts = function_fonts[function_name] - processed_fonts[function_name]
        if not new_fonts:
            continue
        processed_fonts[function_name].update(new_fonts)

        for key in definitions.get(function_name, ()):
            before = len(destination[key])
            destination[key].update(new_fonts)
            semantic_keys.add(key)
            if len(destination[key]) == before:
                continue
            for nested_call in calls_by_key.get(key, ()):
                queue_function(nested_call, destination[key])

    dynamic_function_fonts.clear()
    dynamic_function_fonts.update(function_fonts)

    function_roles: dict[str, set[str]] = defaultdict(set)
    role_queue: deque[str] = deque()
    queued_roles: set[str] = set()

    def queue_function_roles(name: str, roles: Iterable[str]) -> None:
        before = len(function_roles[name])
        function_roles[name].update(roles)
        if len(function_roles[name]) == before or name in queued_roles:
            return
        queued_roles.add(name)
        role_queue.append(name)

    for name, roles in dynamic_function_roles.items():
        queue_function_roles(name, roles)
    for key, calls in calls_by_key.items():
        roles = key_roles.get(key, set())
        if not roles:
            continue
        for call in calls:
            queue_function_roles(call, roles)

    processed_roles: dict[str, set[str]] = defaultdict(set)
    while role_queue:
        function_name = role_queue.popleft()
        queued_roles.discard(function_name)
        new_roles = function_roles[function_name] - processed_roles[function_name]
        if not new_roles:
            continue
        processed_roles[function_name].update(new_roles)

        for key in definitions.get(function_name, ()):
            before = len(key_roles[key])
            key_roles[key].update(new_roles)
            for role in new_roles:
                sources = definition_sources.get(
                    (function_name, key),
                    {(None, 0)},
                )
                for source_path, line in sources:
                    _record_role_evidence(
                        role_evidence,
                        key,
                        role,
                        "confirmed",
                        (
                            f"Ключ возвращается scripted localisation "
                            f"{function_name}, вызванной из контекста роли."
                        ),
                        source_path=source_path,
                        line=line,
                    )
            if len(key_roles[key]) == before:
                continue
            for nested_call in calls_by_key.get(key, ()):
                queue_function_roles(nested_call, key_roles[key])

    dynamic_function_roles.clear()
    dynamic_function_roles.update(function_roles)
    return files_checked, frozenset(semantic_keys)


def build_font_context(
    mod_root: Path,
    localisation_keys: Iterable[str],
    game_root: Path | None = None,
    localisation_values: Mapping[str, Iterable[str]] | None = None,
) -> FontContextIndex:
    mod_root = mod_root.resolve()
    resolved_game = game_root.resolve() if game_root is not None else None
    keys = frozenset(localisation_keys)
    key_fonts: dict[str, set[str]] = defaultdict(set)
    key_roles: dict[str, set[str]] = defaultdict(set)
    role_evidence: dict[
        tuple[str, str],
        set[RoleEvidence],
    ] = defaultdict(set)
    role_fonts: dict[str, set[str]] = defaultdict(set)
    tooltip_keys: set[str] = set()
    dynamic_function_fonts: dict[str, set[str]] = defaultdict(set)
    dynamic_function_roles: dict[str, set[str]] = defaultdict(set)
    read_errors: list[str] = []
    gui_files = _effective_gui_files(mod_root, resolved_game)

    for path in gui_files:
        try:
            text = path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError as error:
            read_errors.append(f"Не удалось прочитать {path}: {error}")
            continue
        _index_gui_blocks(
            _parse_blocks(text, source_path=path),
            keys,
            key_fonts,
            key_roles,
            role_evidence,
            role_fonts,
            tooltip_keys,
            dynamic_function_fonts,
            dynamic_function_roles,
        )

    role_fonts[_ROLE_COUNTRY_NAME].add("tahoma_60")
    role_fonts[_ROLE_STATE_NAME].add("tahoma_60")
    _merge_tooltip_roles(role_fonts)
    for key in tooltip_keys:
        key_fonts[key].update(role_fonts[_ROLE_TOOLTIP])

    script_files_checked, semantic_keys = _collect_semantic_context(
        mod_root,
        resolved_game,
        keys,
        role_fonts,
        key_fonts,
        key_roles,
        role_evidence,
        read_errors,
    )
    dynamic_files_checked, dynamic_keys = _collect_scripted_localisation_context(
        mod_root,
        resolved_game,
        keys,
        localisation_values or {},
        key_fonts,
        key_roles,
        role_evidence,
        dynamic_function_fonts,
        dynamic_function_roles,
        read_errors,
    )
    script_files_checked += dynamic_files_checked
    semantic_keys = semantic_keys | dynamic_keys

    return FontContextIndex(
        mod_root=mod_root,
        game_root=resolved_game,
        key_fonts={key: frozenset(fonts) for key, fonts in key_fonts.items()},
        key_roles={key: frozenset(roles) for key, roles in key_roles.items()},
        role_evidence={
            key_role: tuple(sorted(evidence, key=RoleEvidence.sort_key))
            for key_role, evidence in role_evidence.items()
        },
        gui_files_checked=len(gui_files),
        script_files_checked=script_files_checked,
        semantic_keys=semantic_keys,
        read_errors=tuple(read_errors),
    )
