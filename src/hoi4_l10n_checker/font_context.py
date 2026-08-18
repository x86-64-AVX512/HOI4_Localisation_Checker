from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Iterable, Mapping

from .font_context_dynamic import collect_scripted_localisation_context
from .font_context_gui import index_gui_blocks, merge_tooltip_roles
from .font_context_paths import (
    effective_gui_files,
    find_hoi4_install,
    find_mod_root,
    is_context_root,
    mod_display_name,
)
from .font_context_semantics import collect_semantic_context
from .font_context_types import (
    ROLE_COUNTRY_NAME,
    ROLE_EVENT_DESCRIPTION,
    ROLE_EVENT_TITLE,
    ROLE_FOCUS_DESCRIPTION,
    ROLE_FOCUS_NAME,
    ROLE_STATE_NAME,
    ROLE_TOOLTIP,
    ROLE_WELCOME_TEXT,
    ROLE_WELCOME_TITLE,
    FontContextIndex,
    RoleEvidence,
)
from .paradox_script import parse_blocks

__all__ = [
    "FontContextIndex",
    "ROLE_EVENT_DESCRIPTION",
    "ROLE_EVENT_TITLE",
    "ROLE_FOCUS_DESCRIPTION",
    "ROLE_FOCUS_NAME",
    "ROLE_WELCOME_TITLE",
    "ROLE_WELCOME_TEXT",
    "RoleEvidence",
    "build_font_context",
    "find_hoi4_install",
    "find_mod_root",
    "is_context_root",
    "mod_display_name",
]


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
    gui_files = effective_gui_files(mod_root, resolved_game)

    for path in gui_files:
        try:
            text = path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError as error:
            read_errors.append(f"Не удалось прочитать {path}: {error}")
            continue
        index_gui_blocks(
            parse_blocks(text, source_path=path),
            keys,
            key_fonts,
            key_roles,
            role_evidence,
            role_fonts,
            tooltip_keys,
            dynamic_function_fonts,
            dynamic_function_roles,
        )

    role_fonts[ROLE_COUNTRY_NAME].add("tahoma_60")
    role_fonts[ROLE_STATE_NAME].add("tahoma_60")
    merge_tooltip_roles(role_fonts)
    for key in tooltip_keys:
        key_fonts[key].update(role_fonts[ROLE_TOOLTIP])

    script_files_checked, semantic_keys = collect_semantic_context(
        mod_root,
        resolved_game,
        keys,
        role_fonts,
        key_fonts,
        key_roles,
        role_evidence,
        read_errors,
    )
    dynamic_files_checked, dynamic_keys = collect_scripted_localisation_context(
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
