from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Iterable, Literal

from .font_context import FontContextIndex, build_font_context
from .font_profile import CoverageMode, FontProfile
from .models import Diagnostic, LocalisationEntry
from .parser import iter_rendered_characters, parse_localisation_file

ProgressCallback = Callable[[int, int, Path], None]
GlyphMode = Literal["soft", "strict", "contextual"]
_LIKELY_CYRILLIC_MOJIBAKE = re.compile(r"(?:[РС][\u0400-\u04FF]){2,}")
_LIKELY_WESTERN_MOJIBAKE = re.compile(r"(?:Ã.|Â.|â.|Ð.|Ñ.)")
_MARKUP_CHARACTERS = frozenset({"§", "£", "$", "[", "]", "@"})


@dataclass(slots=True)
class ScanResult:
    root: Path
    files_checked: int
    entries_checked: int
    diagnostics: list[Diagnostic]
    context_mod_root: Path | None = None
    context_game_root: Path | None = None
    context_gui_files: int = 0
    context_script_files: int = 0
    context_resolved_keys: int = 0
    context_semantic_keys: int = 0
    contextual_filtered_warnings: int = 0
    contextual_unresolved_warnings: int = 0

    @property
    def error_count(self) -> int:
        return sum(item.severity == "error" for item in self.diagnostics)

    @property
    def warning_count(self) -> int:
        return sum(item.severity == "warning" for item in self.diagnostics)


def _collect_files(target: Path) -> list[Path]:
    if target.is_file():
        return [target] if target.suffix.casefold() == ".yml" else []
    if target.is_dir():
        return sorted(
            (
                path
                for path in target.rglob("*")
                if path.is_file() and path.suffix.casefold() == ".yml"
            ),
            key=lambda path: str(path).casefold(),
        )
    return []


def _possible_mojibake(text: str) -> bool:
    if not (
        _LIKELY_CYRILLIC_MOJIBAKE.search(text)
        or _LIKELY_WESTERN_MOJIBAKE.search(text)
    ):
        return False
    if sum(not character.isascii() for character in text) < 2:
        return False

    for encoding in ("cp1251", "cp1252", "latin-1"):
        try:
            repaired = text.encode(encoding).decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
        if repaired != text and any(character.isalpha() for character in repaired):
            return True
    return False


def _display_character(character: str) -> str:
    if character == "\u00a0":
        return "неразрывный пробел"
    if character == "\u200b":
        return "пробел нулевой ширины"
    if character.isprintable():
        return f"«{character}»"
    return "непечатный символ"


def _glyph_diagnostics(
    entries: Iterable[LocalisationEntry],
    profile: FontProfile,
    mode: CoverageMode,
    excluded_characters: frozenset[str],
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    safe_characters: dict[str, frozenset[str]] = {}

    for entry in entries:
        coverage = profile.coverage_for(entry.language, mode=mode)
        if coverage is None:
            continue
        if entry.language not in safe_characters:
            safe_characters[entry.language] = frozenset(
                chr(codepoint) for codepoint in coverage
            ) | _MARKUP_CHARACTERS | excluded_characters
        fast_safe = safe_characters[entry.language]
        if set(entry.raw_value).issubset(fast_safe):
            continue

        seen_on_line: set[str] = set()
        for rendered in iter_rendered_characters(entry):
            character = rendered.character
            if character == " " or character in {"\ufffd", "\ufeff"}:
                continue
            if character in seen_on_line:
                continue
            seen_on_line.add(character)

            codepoint = ord(character)
            if codepoint in coverage:
                continue

            unicode_name = unicodedata.name(character, "UNNAMED CHARACTER")
            diagnostics.append(
                Diagnostic(
                    severity="warning",
                    code="UNSAFE_GLYPH",
                    path=entry.path,
                    line=entry.line,
                    column=rendered.column,
                    message=(
                        f"Небезопасный символ {_display_character(character)} "
                        f"(U+{codepoint:04X}, {unicode_name})."
                    ),
                    key=entry.key,
                    character=character,
                )
            )

    return diagnostics


@dataclass(frozen=True, slots=True)
class _ContextualGlyphResult:
    diagnostics: list[Diagnostic]
    filtered_count: int
    unresolved_count: int


def _contextual_glyph_diagnostics(
    entries: Iterable[LocalisationEntry],
    profile: FontProfile,
    excluded_characters: frozenset[str],
    context: FontContextIndex,
    show_unknown_context_warnings: bool,
) -> _ContextualGlyphResult:
    entry_list = list(entries)
    classic = _glyph_diagnostics(
        entry_list,
        profile,
        mode="strict",
        excluded_characters=excluded_characters,
    )
    entries_by_location = {
        (entry.path, entry.line, entry.key): entry
        for entry in entry_list
    }
    kept: list[Diagnostic] = []
    filtered_count = 0
    unresolved_count = 0

    for diagnostic in classic:
        entry = entries_by_location.get(
            (diagnostic.path, diagnostic.line, diagnostic.key)
        )
        fonts = context.fonts_for_key(diagnostic.key)
        if entry is None or not fonts:
            unresolved_count += 1
            if show_unknown_context_warnings:
                kept.append(
                    replace(
                        diagnostic,
                        code="UNKNOWN_FONT_CONTEXT",
                        message=(
                            f"Не удалось определить шрифт для символа "
                            f"{_display_character(diagnostic.character)} "
                            f"(U+{ord(diagnostic.character):04X}). "
                            "Отсутствие глифа не подтверждено."
                        ),
                    )
                )
            continue

        codepoint = ord(diagnostic.character)
        missing_fonts: list[str] = []
        unknown_fonts: list[str] = []
        for font_name in sorted(fonts, key=str.casefold):
            coverage = profile.coverage_for_family(
                entry.language,
                font_name,
            )
            if coverage is None:
                unknown_fonts.append(font_name)
            elif codepoint not in coverage:
                missing_fonts.append(font_name)

        if missing_fonts:
            kept.append(
                replace(
                    diagnostic,
                    message=(
                        f"{diagnostic.message} Отсутствует в контекстном "
                        f"шрифте: {', '.join(missing_fonts)}."
                    ),
                )
            )
            continue
        if unknown_fonts:
            unresolved_count += 1
            if show_unknown_context_warnings:
                kept.append(
                    replace(
                        diagnostic,
                        code="UNKNOWN_FONT_CONTEXT",
                        message=(
                            f"Не удалось проверить символ "
                            f"{_display_character(diagnostic.character)} "
                            f"(U+{ord(diagnostic.character):04X}) "
                            "в контекстном шрифте: "
                            f"{', '.join(unknown_fonts)}. "
                            "Отсутствие глифа не подтверждено."
                        ),
                    )
                )
            continue

        filtered_count += 1

    return _ContextualGlyphResult(
        diagnostics=kept,
        filtered_count=filtered_count,
        unresolved_count=unresolved_count,
    )


def _duplicate_diagnostics(
    entries: Iterable[LocalisationEntry],
) -> list[Diagnostic]:
    groups: dict[tuple[str, str], list[LocalisationEntry]] = defaultdict(list)
    for entry in entries:
        groups[(entry.language, entry.key)].append(entry)

    diagnostics: list[Diagnostic] = []
    for (language, key), occurrences in groups.items():
        if len(occurrences) < 2:
            continue
        locations = [f"{entry.path}:{entry.line}" for entry in occurrences]
        for index, entry in enumerate(occurrences):
            other_locations = locations[:index] + locations[index + 1 :]
            diagnostics.append(
                Diagnostic(
                    severity="error",
                    code="DUPLICATE_KEY",
                    path=entry.path,
                    line=entry.line,
                    column=1,
                    message=(
                        f"Ключ «{key}» повторяется для языка {language}. "
                        f"Другие определения: {'; '.join(other_locations)}"
                    ),
                    key=key,
                )
            )
    return diagnostics


def _russian_straight_quote_diagnostics(
    entries: Iterable[LocalisationEntry],
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    for entry in entries:
        if entry.language.casefold() != "l_russian":
            continue
        for offset, character in enumerate(entry.raw_value):
            if character != '"':
                continue
            diagnostics.append(
                Diagnostic(
                    severity="warning",
                    code="STRAIGHT_QUOTE",
                    path=entry.path,
                    line=entry.line,
                    column=entry.value_column + offset,
                    message=(
                        "В русском тексте обнаружена прямая кавычка "
                        '«"» (U+0022).'
                    ),
                    key=entry.key,
                    character='"',
                    selection_length=1,
                )
            )
    return diagnostics


class LocalisationChecker:
    def __init__(self, font_profile: FontProfile | None) -> None:
        self.font_profile = font_profile

    def scan(
        self,
        target: Path,
        progress: ProgressCallback | None = None,
        glyph_mode: GlyphMode = "soft",
        excluded_characters: frozenset[str] = frozenset(),
        context_mod_root: Path | None = None,
        context_game_root: Path | None = None,
        show_unknown_context_warnings: bool = False,
        check_russian_straight_quotes: bool = True,
    ) -> ScanResult:
        target = target.resolve()
        files = _collect_files(target)
        diagnostics: list[Diagnostic] = []
        entries: list[LocalisationEntry] = []

        if not files:
            diagnostics.append(
                Diagnostic(
                    severity="error",
                    code="NO_LOCALISATION_FILES",
                    path=target,
                    line=1,
                    column=1,
                    message="Не найдено ни одного файла с расширением .yml.",
                )
            )
            return ScanResult(
                root=target,
                files_checked=0,
                entries_checked=0,
                diagnostics=diagnostics,
            )

        total = len(files)
        for index, path in enumerate(files, start=1):
            if progress is not None:
                progress(index, total, path)
            parsed = parse_localisation_file(path)
            diagnostics.extend(parsed.diagnostics)
            entries.extend(parsed.entries)

            for entry in parsed.entries:
                if _possible_mojibake(entry.raw_value):
                    diagnostics.append(
                        Diagnostic(
                            severity="warning",
                            code="POSSIBLE_MOJIBAKE",
                            path=entry.path,
                            line=entry.line,
                            column=entry.value_column,
                            message="Возможно, текст был повреждён повторным перекодированием.",
                            key=entry.key,
                        )
                    )

        diagnostics.extend(_duplicate_diagnostics(entries))
        if check_russian_straight_quotes:
            diagnostics.extend(
                _russian_straight_quote_diagnostics(entries)
            )
        context: FontContextIndex | None = None
        contextual_filtered = 0
        contextual_unresolved = 0
        if glyph_mode == "contextual" and context_mod_root is not None:
            localisation_values: dict[str, list[str]] = defaultdict(list)
            for entry in entries:
                localisation_values[entry.key].append(entry.raw_value)
            context = build_font_context(
                context_mod_root,
                (entry.key for entry in entries),
                game_root=context_game_root,
                localisation_values=localisation_values,
            )

        if self.font_profile is not None:
            if glyph_mode == "contextual" and context is not None:
                contextual = _contextual_glyph_diagnostics(
                    entries,
                    self.font_profile,
                    excluded_characters=excluded_characters,
                    context=context,
                    show_unknown_context_warnings=(
                        show_unknown_context_warnings
                    ),
                )
                diagnostics.extend(contextual.diagnostics)
                contextual_filtered = contextual.filtered_count
                contextual_unresolved = contextual.unresolved_count
            else:
                coverage_mode: CoverageMode = (
                    "soft" if glyph_mode == "soft" else "strict"
                )
                diagnostics.extend(
                    _glyph_diagnostics(
                        entries,
                        self.font_profile,
                        mode=coverage_mode,
                        excluded_characters=excluded_characters,
                    )
                )
            for message in self.font_profile.runtime_errors:
                diagnostics.append(
                    Diagnostic(
                        severity="error",
                        code="FONT_PROFILE_ERROR",
                        path=target,
                        line=1,
                        column=1,
                        message=message,
                    )
                )

        diagnostics.sort(key=Diagnostic.sort_key)
        return ScanResult(
            root=target,
            files_checked=len(files),
            entries_checked=len(entries),
            diagnostics=diagnostics,
            context_mod_root=context.mod_root if context is not None else None,
            context_game_root=context.game_root if context is not None else None,
            context_gui_files=context.gui_files_checked if context is not None else 0,
            context_script_files=(
                context.script_files_checked if context is not None else 0
            ),
            context_resolved_keys=(
                context.resolved_key_count if context is not None else 0
            ),
            context_semantic_keys=(
                context.semantic_resolved_key_count
                if context is not None
                else 0
            ),
            contextual_filtered_warnings=contextual_filtered,
            contextual_unresolved_warnings=contextual_unresolved,
        )
