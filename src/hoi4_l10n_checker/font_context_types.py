from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .paradox_script import ParsedBlock, property_line

__all__ = [
    "FontContextIndex",
    "ROLE_TOOLTIP",
    "ROLE_IDEA_SPIRIT_NAME",
    "ROLE_IDEA_SELECTABLE_NAME",
    "ROLE_IDEA_DESCRIPTION",
    "ROLE_FOCUS_NAME",
    "ROLE_FOCUS_DESCRIPTION",
    "ROLE_EVENT_TITLE",
    "ROLE_EVENT_DESCRIPTION",
    "ROLE_EVENT_OPTION",
    "ROLE_DECISION_NAME",
    "ROLE_DECISION_DESCRIPTION",
    "ROLE_DECISION_CATEGORY_NAME",
    "ROLE_DECISION_CATEGORY_DESCRIPTION",
    "ROLE_TECHNOLOGY_NAME",
    "ROLE_TECHNOLOGY_DESCRIPTION",
    "ROLE_EQUIPMENT_LAND_NAME",
    "ROLE_EQUIPMENT_AIR_NAME",
    "ROLE_EQUIPMENT_NAVAL_NAME",
    "ROLE_EQUIPMENT_RAILWAY_NAME",
    "ROLE_EQUIPMENT_DESCRIPTION",
    "ROLE_BATTLEPLAN_NAME",
    "ROLE_VICTORY_POINT_NAME",
    "ROLE_COUNTRY_NAME",
    "ROLE_PARTY_NAME",
    "ROLE_STATE_NAME",
    "ROLE_CHARACTER_NAME",
    "ROLE_CHARACTER_DESCRIPTION",
    "ROLE_DECISION_COST",
    "ROLE_MIO_NAME",
    "ROLE_WELCOME_TITLE",
    "ROLE_WELCOME_TEXT",
    "RoleEvidence",
    "record_role_evidence",
]

ROLE_TOOLTIP = "tooltip"
ROLE_IDEA_SPIRIT_NAME = "idea_spirit_name"
ROLE_IDEA_SELECTABLE_NAME = "idea_selectable_name"
ROLE_IDEA_DESCRIPTION = "idea_description"
ROLE_FOCUS_NAME = "focus_name"
ROLE_FOCUS_DESCRIPTION = "focus_description"
ROLE_EVENT_TITLE = "event_title"
ROLE_EVENT_DESCRIPTION = "event_description"
ROLE_EVENT_OPTION = "event_option"
ROLE_DECISION_NAME = "decision_name"
ROLE_DECISION_DESCRIPTION = "decision_description"
ROLE_DECISION_CATEGORY_NAME = "decision_category_name"
ROLE_DECISION_CATEGORY_DESCRIPTION = "decision_category_description"
ROLE_TECHNOLOGY_NAME = "technology_name"
ROLE_TECHNOLOGY_DESCRIPTION = "technology_description"
ROLE_EQUIPMENT_LAND_NAME = "equipment_land_name"
ROLE_EQUIPMENT_AIR_NAME = "equipment_air_name"
ROLE_EQUIPMENT_NAVAL_NAME = "equipment_naval_name"
ROLE_EQUIPMENT_RAILWAY_NAME = "equipment_railway_name"
ROLE_EQUIPMENT_DESCRIPTION = "equipment_description"
ROLE_BATTLEPLAN_NAME = "battleplan_name"
ROLE_VICTORY_POINT_NAME = "victory_point_name"
ROLE_COUNTRY_NAME = "country_name"
ROLE_PARTY_NAME = "party_name"
ROLE_STATE_NAME = "state_name"
ROLE_CHARACTER_NAME = "character_name"
ROLE_CHARACTER_DESCRIPTION = "character_description"
ROLE_DECISION_COST = "decision_cost"
ROLE_MIO_NAME = "mio_name"
ROLE_WELCOME_TITLE = "welcome_title"
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


def record_role_evidence(
    destination: dict[tuple[str, str], set[RoleEvidence]],
    key: str,
    role: str,
    confidence: str,
    rule: str,
    block: ParsedBlock | None = None,
    property_name: str = "",
    property_value: str = "",
    source_path: Path | None = None,
    line: int = 0,
) -> None:
    if block is not None:
        source_path = block.source_path
        line = (
            property_line(block, property_name, property_value)
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
