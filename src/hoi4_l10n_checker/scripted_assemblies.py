"""Conservative recognition of flat assemblies; no focus processing."""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from .long_text import BYTE_LIMIT, _event_description_keys, expanded_byte_size
from .models import Diagnostic, LocalisationEntry
from .paradox_script import parse_blocks, tokenize_script

_CALL = re.compile(r"\[Root\.([A-Za-z_][A-Za-z0-9_]*)\]")


@dataclass(frozen=True, slots=True)
class ScriptBranch:
    tag: str
    key: str


@dataclass(frozen=True, slots=True)
class AssemblyVariant:
    label: str
    raw_value: str
    helpers: frozenset[str]


@dataclass(slots=True)
class AssemblyIndex:
    variants: dict[tuple[str, str], tuple[AssemblyVariant, ...]] = field(
        default_factory=dict
    )
    diagnostics: list[Diagnostic] = field(default_factory=list)
    getter_targets: dict[str, frozenset[str]] = field(default_factory=dict)
    primary_keys: set[str] = field(default_factory=set)

    def helpers_for(self, language: str, root: str) -> frozenset[str]:
        return frozenset(
            key for variant in self.variants.get((language, root), ())
            for key in variant.helpers
        )


def _definitions(
    root: Path,
) -> tuple[dict[str, list[ScriptBranch]], set[str], dict[str, frozenset[str]]]:
    definitions: dict[str, list[ScriptBranch]] = {}
    bad: set[str] = set()
    targets: dict[str, set[str]] = defaultdict(set)
    for path in (root / "common/scripted_localisation").rglob("*.txt"):
        text = path.read_text(encoding="utf-8-sig")
        depth = 0
        malformed = False
        for token in tokenize_script(text):
            if token == "{":
                depth += 1
            elif token == "}":
                depth -= 1
                malformed |= depth < 0
        malformed |= depth != 0
        blocks = parse_blocks(text, path)
        for owner in blocks:
            if owner.kind != "defined_text":
                continue
            names = owner.properties.get("name", [])
            if len(names) != 1:
                continue
            name = names[0]
            if malformed or set(owner.properties) != {"name"}:
                bad.add(name)
            if name in definitions:
                bad.add(name)
            branches: list[ScriptBranch] = []
            texts = [
                block for block in blocks
                if block.parent is owner and block.kind == "text"
            ]
            for block in texts:
                keys = block.properties.get("localization_key", [])
                targets[name].update(keys)
                triggers = [
                    child for child in blocks
                    if child.parent is block and child.kind == "trigger"
                ]
                if (
                    len(keys) != 1 or len(triggers) != 1
                    or set(block.properties) != {"localization_key"}
                    or any(
                        child.parent is block and child.kind != "trigger"
                        for child in blocks
                    )
                ):
                    bad.add(name)
                    continue
                trigger = triggers[0]
                if any(child.parent is trigger for child in blocks):
                    bad.add(name)
                    continue
                properties = dict(trigger.properties)
                if properties == {"always": ["yes"]}:
                    tag = ""
                elif (
                    set(properties) == {"original_tag"}
                    and len(properties["original_tag"]) == 1
                    and re.fullmatch(r"[A-Z0-9]{3}", properties["original_tag"][0])
                ):
                    tag = properties["original_tag"][0]
                else:
                    bad.add(name)
                    continue
                branches.append(ScriptBranch(tag, keys[0]))
            if (
                not branches or branches[-1].tag
                or len({branch.tag for branch in branches}) != len(branches)
                or any(not branch.tag for branch in branches[:-1])
            ):
                bad.add(name)
            definitions[name] = branches
    return definitions, bad, {
        name: frozenset(keys) for name, keys in targets.items()
    }


def analyse_assemblies(
    root: Path,
    entries: list[LocalisationEntry],
) -> AssemblyIndex:
    result = AssemblyIndex()
    by_language: dict[str, dict[str, list[LocalisationEntry]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for entry in entries:
        by_language[entry.language][entry.key].append(entry)
    try:
        definitions, bad, targets = _definitions(root)
        event_keys = _event_description_keys(root)
    except (OSError, UnicodeError) as error:
        result.diagnostics.append(Diagnostic(
            "error", "ASSEMBLY_INDEX_ERROR", root, 1, 1,
            f"Не удалось проверить сборки: {error}",
        ))
        return result
    result.primary_keys = event_keys | {"EAW_WS_TAB_1_TXT"}
    result.getter_targets = targets

    for language, keys in by_language.items():
        values = {
            key: occurrences[0].raw_value
            for key, occurrences in keys.items() if len(occurrences) == 1
        }
        for key, occurrences in keys.items():
            if key not in event_keys and key != "EAW_WS_TAB_1_TXT":
                continue
            if len(occurrences) != 1:
                continue
            entry = occurrences[0]
            calls = _CALL.findall(entry.raw_value)
            if not calls or _CALL.sub("", entry.raw_value):
                continue
            # Ordinary GetCountryIntro/GetName are not automatically assemblies.
            if not (
                (len(calls) >= 2 and all(name in definitions for name in calls))
                or any(re.search(r"Part\d+$", name) for name in calls)
            ):
                continue
            errors: list[str] = []
            if len(calls) != len(set(calls)):
                errors.append("Один getter повторён в сборке.")
            for name in calls:
                if name not in definitions:
                    errors.append(f"Нет определения getter {name}.")
                elif name in bad:
                    errors.append(
                        f"Getter {name}: конфликт или неподдерживаемая структура "
                        "условий; сборка не признана безопасной."
                    )
                elif key in event_keys and any(
                    branch.tag for branch in definitions[name]
                ):
                    errors.append(
                        "Шаблон ивента поддерживает безусловные части."
                    )
            if errors:
                result.diagnostics.append(_issue(entry, errors))
                continue
            all_helpers = {
                branch.key for name in calls for branch in definitions[name]
            }
            for helper in all_helpers:
                if helper == key:
                    errors.append("Сборка ссылается сама на себя.")
                if helper not in keys:
                    errors.append(f"Нет ключа части «{helper}» в {language}.")
                elif len(keys[helper]) != 1:
                    errors.append(f"Неоднозначный ключ части «{helper}».")
                else:
                    raw = values[helper]
                    is_welcome_fallback = (
                        key == "EAW_WS_TAB_1_TXT"
                        and raw == "[Root.GetCountryIntro]"
                    )
                    if not is_welcome_fallback and any(
                        name in definitions for name in _CALL.findall(raw)
                    ):
                        errors.append(
                            f"Вложенная scripted-сборка в «{helper}»: "
                            "обход для неё не подтверждён."
                        )
                    try:
                        references = list(re.findall(r"\$([^$\n]+)\$", raw))
                        visited_refs: set[str] = set()
                        while references:
                            reference = references.pop()
                            if reference == key:
                                raise ValueError(
                                    f"Часть «{helper}» ссылается на свою сборку."
                                )
                            if reference in visited_refs:
                                continue
                            visited_refs.add(reference)
                            referenced = values.get(reference, "")
                            if any(
                                name in calls for name in _CALL.findall(referenced)
                            ):
                                raise ValueError("Цикл через ссылку $KEY$ и getter.")
                            references.extend(re.findall(
                                r"\$([^$\n]+)\$", referenced
                            ))
                        size = expanded_byte_size(raw, values)
                        if size is not None and size >= BYTE_LIMIT:
                            errors.append(
                                f"Часть «{helper}» достигает {size} байт."
                            )
                    except ValueError as error:
                        errors.append(str(error))
            if len(entry.raw_value.encode("utf-8")) >= BYTE_LIMIT:
                errors.append("Строка сборки достигает 6144 байт.")
            if key == "EAW_WS_TAB_1_TXT":
                for number, name in enumerate(calls):
                    fallback = definitions[name][-1].key
                    expected = "[Root.GetCountryIntro]" if number == 0 else ""
                    if values.get(fallback) != expected:
                        errors.append(
                            "Возврат прежнего описания должен быть только "
                            "у первой части; остальные возвращают пустой ключ."
                        )
            if errors:
                result.diagnostics.append(_issue(entry, errors))
                continue
            tags = sorted({
                branch.tag for name in calls for branch in definitions[name]
                if branch.tag
            })
            variants = []
            for tag in tags or [""]:
                raw_parts = []
                for name in calls:
                    branches = definitions[name]
                    selected = next(
                        (branch for branch in branches if branch.tag == tag),
                        branches[-1],
                    )
                    raw_parts.append(values[selected.key])
                variants.append(AssemblyVariant(
                    tag or "Ивент", "".join(raw_parts), frozenset(all_helpers)
                ))
            result.variants[(language, key)] = tuple(variants)
    return result


def _issue(entry: LocalisationEntry, errors: list[str]) -> Diagnostic:
    return Diagnostic(
        "error", "INVALID_SCRIPTED_ASSEMBLY",
        entry.path, entry.line, entry.value_column,
        " ".join(sorted(set(errors))), key=entry.key,
    )


def comparison_helpers(
    index: AssemblyIndex,
    values_by_language: dict[str, dict[str, str]],
) -> dict[str, set[str]]:
    """Omit helpers only when the opposite root exists and does not need them."""
    ignored: dict[str, set[str]] = defaultdict(set)
    for (language, key), variants in index.variants.items():
        other = "l_english" if language == "l_russian" else "l_russian"
        other_values = values_by_language.get(other, {})
        if key not in other_values:
            continue
        helpers = set().union(*(variant.helpers for variant in variants))
        # Search all opposite-language roots, not just the paired key.
        used = {
            name for raw in other_values.values() for name in _CALL.findall(raw)
        }
        own_calls = set(_CALL.findall(values_by_language[language][key]))
        if used & own_calls:
            continue
        opposite_dependencies: set[str] = set()
        pending_calls = list(used)
        visited: set[str] = set()
        while pending_calls:
            name = pending_calls.pop()
            if name in visited:
                continue
            visited.add(name)
            for target in index.getter_targets.get(name, ()):
                opposite_dependencies.add(target)
                pending_calls.extend(_CALL.findall(other_values.get(target, "")))
        for raw in other_values.values():
            opposite_dependencies.update(re.findall(r"\$([^$|\n]+)(?:\|[^$]+)?\$", raw))
        ignored[language].update(
            helpers - opposite_dependencies - index.primary_keys
        )
    return ignored
