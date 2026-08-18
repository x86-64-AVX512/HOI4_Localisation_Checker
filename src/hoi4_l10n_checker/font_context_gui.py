from __future__ import annotations

import re
from typing import Iterable

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
    ROLE_WELCOME_TEXT,
    ROLE_WELCOME_TITLE,
    RoleEvidence,
    record_role_evidence,
)
from .paradox_script import (
    ParsedBlock,
    ancestor_names,
    block_name,
    font_names,
    localisation_calls,
)

__all__ = ["index_gui_blocks", "merge_tooltip_roles"]

_DIRECT_TEXT_PROPERTIES = frozenset({"text", "buttontext"})
_TOOLTIP_PROPERTIES = frozenset(
    {
        "context_aware_tooltip",
        "pdx_tooltip",
        "pdx_tooltip_delayed",
        "tooltip",
    }
)
_EQUIPMENT_WIDGET_NAMES = frozenset(
    {
        "equipment_name",
        "equipment_type",
        "equipment_variant",
        "ship_type",
        "variant_name",
    }
)


def index_gui_blocks(
    blocks: Iterable[ParsedBlock],
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
        fonts = font_names(block)
        name = block_name(block).casefold()
        ancestors = frozenset(ancestor_names(block))
        welcome_context = any(
            "welcome_screen" in candidate or "_ws_" in f"_{candidate}_"
            for candidate in ancestors
        )
        welcome_body = (
            welcome_context and re.fullmatch(r"tab_\d+_text", name) is not None
        )
        welcome_title = welcome_context and "header" in name

        if welcome_body:
            role_fonts[ROLE_WELCOME_TEXT].update(fonts)
            for property_name in _DIRECT_TEXT_PROPERTIES:
                for text in block.properties.get(property_name, []):
                    if text in localisation_keys:
                        key_roles[text].add(ROLE_WELCOME_TEXT)
                        record_role_evidence(
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
                    for function_name in localisation_calls(text):
                        dynamic_function_roles[function_name].add(ROLE_WELCOME_TEXT)

        if welcome_title:
            role_fonts[ROLE_WELCOME_TITLE].update(fonts)
            for property_name in _DIRECT_TEXT_PROPERTIES:
                for text in block.properties.get(property_name, []):
                    if text in localisation_keys:
                        key_roles[text].add(ROLE_WELCOME_TITLE)
                        record_role_evidence(
                            role_evidence,
                            text,
                            ROLE_WELCOME_TITLE,
                            "confirmed",
                            (
                                "Ключ напрямую назначен заголовку "
                                "вступительного экрана."
                            ),
                            block=block,
                            property_name=property_name,
                            property_value=text,
                        )
                    for function_name in localisation_calls(text):
                        dynamic_function_roles[function_name].add(
                            ROLE_WELCOME_TITLE
                        )

        if fonts:
            for property_name in _DIRECT_TEXT_PROPERTIES:
                for text in block.properties.get(property_name, []):
                    if text in localisation_keys:
                        destination[text].update(fonts)
                    for function_name in localisation_calls(text):
                        dynamic_function_fonts[function_name].update(fonts)

        for property_name in _TOOLTIP_PROPERTIES:
            for key in block.properties.get(property_name, []):
                if key in localisation_keys:
                    tooltip_keys.add(key)

        if not fonts or not name:
            continue

        if name == "tooltip":
            role_fonts[ROLE_TOOLTIP].update(fonts)

        text_values = {
            value.casefold()
            for property_name in _DIRECT_TEXT_PROPERTIES
            for value in block.properties.get(property_name, [])
        }
        if name == "operation_name" and "battleplantools_window" in ancestors:
            role_fonts[ROLE_BATTLEPLAN_NAME].update(fonts)
        if name == "text" and ancestors.intersection(
            {"victory_point_mapicon", "capital_mapicon"}
        ):
            role_fonts[ROLE_VICTORY_POINT_NAME].update(fonts)
        if name == "party_name" or "party name" in text_values:
            role_fonts[ROLE_PARTY_NAME].update(fonts)
        if "country_name" in name or "country name" in text_values:
            role_fonts[ROLE_COUNTRY_NAME].update(fonts)
        if name in {"state_name", "state name"}:
            role_fonts[ROLE_STATE_NAME].update(fonts)
        if name == "cost_and_timer_text":
            role_fonts[ROLE_DECISION_COST].update(fonts)
        if "mio name" in text_values:
            role_fonts[ROLE_MIO_NAME].update(fonts)

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
            role_fonts[ROLE_CHARACTER_NAME].update(fonts)
        if (
            character_context
            and not event_context
            and (
                name in {"desc", "description"}
                or name.endswith(("_desc", "_description"))
            )
        ):
            role_fonts[ROLE_CHARACTER_DESCRIPTION].update(fonts)

        in_event_window = any(
            ancestor.startswith("eventwindow") for ancestor in ancestors
        )
        if in_event_window and name == "title":
            role_fonts[ROLE_EVENT_TITLE].update(fonts)
        if in_event_window and name == "description":
            role_fonts[ROLE_EVENT_DESCRIPTION].update(fonts)
        if name == "name" and "event_option_entry" in ancestors:
            role_fonts[ROLE_EVENT_OPTION].update(fonts)
        if name == "name_text" and "event_item" in ancestors:
            role_fonts[ROLE_EVENT_TITLE].update(fonts)

        if name == "name" and ancestors.intersection(focus_name_templates):
            role_fonts[ROLE_FOCUS_NAME].update(fonts)
        if name == "desc" and ancestors.intersection(focus_description_templates):
            role_fonts[ROLE_FOCUS_DESCRIPTION].update(fonts)

        if name == "name" and any(
            ancestor.startswith("political_selectable_idea_entry")
            for ancestor in ancestors
        ):
            role_fonts[ROLE_IDEA_SELECTABLE_NAME].update(fonts)

        if name == "name_text" and ancestors.intersection(decision_templates):
            role_fonts[ROLE_DECISION_NAME].update(fonts)
        if name == "name_text" and "category_header" in ancestors:
            role_fonts[ROLE_DECISION_CATEGORY_NAME].update(fonts)
        if (
            name in {"full_text", "short_text"}
            and "decision_category_desc" in ancestors
        ):
            role_fonts[ROLE_DECISION_CATEGORY_DESCRIPTION].update(fonts)

        if name == "tech_info_title":
            role_fonts[ROLE_TECHNOLOGY_NAME].update(fonts)
        if name == "tech_info_description":
            role_fonts[ROLE_TECHNOLOGY_DESCRIPTION].update(fonts)
        if name == "name" and any(
            ancestor.startswith("techtree_") and ancestor.endswith("_item")
            for ancestor in ancestors
        ):
            role_fonts[ROLE_TECHNOLOGY_NAME].update(fonts)

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
                equipment_roles = (ROLE_EQUIPMENT_AIR_NAME,)
            elif "stat_equipment_entry_naval" in ancestors:
                equipment_roles = (ROLE_EQUIPMENT_NAVAL_NAME,)
            elif "stat_equipment_entry_railway_gun" in ancestors:
                equipment_roles = (ROLE_EQUIPMENT_RAILWAY_NAME,)
            elif "stat_equipment_entry" in ancestors:
                equipment_roles = (ROLE_EQUIPMENT_LAND_NAME,)
            else:
                equipment_roles = (
                    ROLE_EQUIPMENT_LAND_NAME,
                    ROLE_EQUIPMENT_AIR_NAME,
                    ROLE_EQUIPMENT_NAVAL_NAME,
                    ROLE_EQUIPMENT_RAILWAY_NAME,
                )
            for role in equipment_roles:
                role_fonts[role].update(fonts)


def merge_tooltip_roles(role_fonts: dict[str, set[str]]) -> None:
    tooltip_fonts = role_fonts[ROLE_TOOLTIP]
    for role in (
        ROLE_IDEA_SPIRIT_NAME,
        ROLE_IDEA_SELECTABLE_NAME,
        ROLE_IDEA_DESCRIPTION,
        ROLE_FOCUS_NAME,
        ROLE_FOCUS_DESCRIPTION,
        ROLE_DECISION_NAME,
        ROLE_DECISION_DESCRIPTION,
        ROLE_TECHNOLOGY_NAME,
        ROLE_TECHNOLOGY_DESCRIPTION,
        ROLE_EQUIPMENT_LAND_NAME,
        ROLE_EQUIPMENT_AIR_NAME,
        ROLE_EQUIPMENT_NAVAL_NAME,
        ROLE_EQUIPMENT_RAILWAY_NAME,
        ROLE_EQUIPMENT_DESCRIPTION,
        ROLE_CHARACTER_NAME,
        ROLE_CHARACTER_DESCRIPTION,
        ROLE_MIO_NAME,
    ):
        role_fonts[role].update(tooltip_fonts)
