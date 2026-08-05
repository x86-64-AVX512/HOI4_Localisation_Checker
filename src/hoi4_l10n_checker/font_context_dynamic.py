from __future__ import annotations

import re
from collections import defaultdict, deque
from pathlib import Path
from typing import Iterable, Mapping

from .font_context_paths import effective_data_files
from .font_context_types import RoleEvidence, record_role_evidence
from .paradox_script import (
    ParsedBlock,
    localisation_calls,
    property_line,
    read_script_blocks,
)

__all__ = ["collect_scripted_localisation_context"]


def _defined_text_owner(block: ParsedBlock) -> ParsedBlock | None:
    current: ParsedBlock | None = block
    while current is not None:
        if current.kind.casefold() == "defined_text":
            return current
        current = current.parent
    return None


def collect_scripted_localisation_context(
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
    for path in effective_data_files(
        mod_root,
        game_root,
        "common/scripted_localisation",
    ):
        files_checked += 1
        blocks = read_script_blocks(path, read_errors)
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
                                property_line(
                                    block,
                                    "localization_key",
                                    raw_key,
                                ),
                            )
                        )

    calls_by_key: dict[str, frozenset[str]] = {}
    for key, values in localisation_values.items():
        calls = {call for value in values for call in localisation_calls(value)}
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
                    record_role_evidence(
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
