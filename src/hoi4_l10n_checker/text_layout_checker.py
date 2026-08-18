from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Literal, Protocol

from .focus_preview_cli import (
    FocusPreviewBatchResult,
    FocusPreviewClient,
    FocusPreviewRequestItem,
    FocusPreviewResult,
)
from .font_context import (
    ROLE_EVENT_DESCRIPTION,
    ROLE_EVENT_TITLE,
    ROLE_FOCUS_DESCRIPTION,
    ROLE_FOCUS_NAME,
    ROLE_WELCOME_TEXT,
    ROLE_WELCOME_TITLE,
    FontContextIndex,
    RoleEvidence,
    build_font_context,
)
from .models import Diagnostic, LocalisationEntry
from .parser import iter_rendered_characters, parse_localisation_file

FocusCheckMode = Literal["length", "newline", "exact"]
FocusPreviewPriorityMode = Literal["auto_ru", "auto_en", "ru", "en"]
ProgressCallback = Callable[[int, int, Path], None]
PreviewStartCallback = Callable[[int], None]
_FOCUS_MODES = frozenset({"length", "newline", "exact"})
_FOCUS_PREVIEW_PRIORITY_MODES = frozenset(
    {"auto_ru", "auto_en", "ru", "en"}
)
_DYNAMIC_VALUE = re.compile(r"\[[^\]\r\n]+\]|\$[^$\r\n]+\$")


class FocusPreviewRunner(Protocol):
    def check(
        self,
        items: list[FocusPreviewRequestItem],
        *,
        policy: Literal["visual"],
    ) -> FocusPreviewBatchResult: ...


FocusPreviewFactory = Callable[[Path], FocusPreviewRunner]


@dataclass(frozen=True, slots=True)
class TextLayoutOptions:
    focus_enabled: bool = True
    focus_mode: FocusCheckMode = "length"
    focus_limit: int = 350
    focus_preview_cli_path: Path | None = None
    focus_preview_priority: FocusPreviewPriorityMode = "auto_ru"
    events_enabled: bool = True
    event_limit: int = 3400
    welcome_enabled: bool = True
    welcome_limit: int = 3400
    title_newline_enabled: bool = False

    def validate(self) -> None:
        if self.focus_mode not in _FOCUS_MODES:
            raise ValueError("Неизвестный режим проверки фокусов.")
        if self.focus_enabled and self.focus_mode == "length":
            _validate_limit(self.focus_limit, "фокусов")
        if self.focus_enabled and self.focus_mode == "exact":
            _validate_limit(self.focus_limit, "фокусов")
            if self.focus_preview_cli_path is None:
                raise ValueError(
                    "Для точной проверки укажите "
                    "EaWFocusTextPreviewCLI.exe."
                )
            if (
                self.focus_preview_priority
                not in _FOCUS_PREVIEW_PRIORITY_MODES
            ):
                raise ValueError(
                    "Неизвестный приоритет шрифтов точной проверки."
                )
        if self.events_enabled:
            _validate_limit(self.event_limit, "ивентов")
        if self.welcome_enabled:
            _validate_limit(
                self.welcome_limit,
                "вступительных экранов",
            )
        if not (
            self.focus_enabled
            or self.events_enabled
            or self.welcome_enabled
            or self.title_newline_enabled
        ):
            raise ValueError("Нужно включить хотя бы одну проверку.")


@dataclass(slots=True)
class TextLayoutResult:
    root: Path
    files_checked: int
    entries_checked: int
    focus_checked: int
    events_checked: int
    welcome_checked: int
    diagnostics: list[Diagnostic]
    titles_checked: int = 0
    english_root: Path | None = None
    english_files_checked: int = 0
    english_entries_checked: int = 0
    english_locations: dict[str, Diagnostic] = field(default_factory=dict)
    english_fallback_paths: dict[Path, Path] = field(default_factory=dict)
    context_gui_files: int = 0
    context_script_files: int = 0
    preview_checked: int = 0
    preview_green: int = 0
    preview_yellow: int = 0
    preview_red: int = 0
    preview_errors: int = 0
    preview_version: str = ""
    preview_error_messages: tuple[str, ...] = ()

    @property
    def warning_count(self) -> int:
        return len(self.diagnostics)

    @property
    def length_warning_count(self) -> int:
        return sum(
            item.code == "TEXT_TOO_LONG"
            for item in self.diagnostics
        )

    @property
    def newline_warning_count(self) -> int:
        return sum(
            item.code == "FOCUS_NEWLINE"
            for item in self.diagnostics
        )

    @property
    def title_newline_warning_count(self) -> int:
        return sum(
            item.code == "TITLE_NEWLINE"
            for item in self.diagnostics
        )

    @property
    def exact_red_warning_count(self) -> int:
        return sum(
            item.code == "FOCUS_PREVIEW_RED"
            for item in self.diagnostics
        )

    def issue_for(self, diagnostic: Diagnostic) -> TextLayoutIssue:
        english = self.english_locations.get(diagnostic.key)
        if english is None:
            fallback_path = self.english_fallback_paths.get(
                diagnostic.path.resolve()
            )
            if fallback_path is not None:
                english = Diagnostic(
                    severity="warning",
                    code="TEXT_LAYOUT_REFERENCE_FALLBACK",
                    path=fallback_path,
                    line=diagnostic.line,
                    column=diagnostic.column,
                    message=(
                        "Английская пара ключа не найдена; открыта "
                        "соответствующая строка парного файла."
                    ),
                    key=diagnostic.key,
                )
        return TextLayoutIssue(
            russian=diagnostic,
            english=english,
        )


@dataclass(frozen=True, slots=True)
class TextLayoutIssue:
    russian: Diagnostic
    english: Diagnostic | None = None

    def diagnostic_for(
        self,
        language: Literal["english", "russian"],
    ) -> Diagnostic | None:
        return self.english if language == "english" else self.russian


@dataclass(frozen=True, slots=True)
class _ExactFocusCandidate:
    request_id: int
    entry: LocalisationEntry
    measured_length: int
    role_confidence: str
    role_evidence: str


def _validate_limit(value: int, label: str) -> None:
    if isinstance(value, bool) or value <= 0:
        raise ValueError(
            f"Лимит для {label} должен быть положительным целым числом."
        )


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


def _neutral_localisation_name(path: Path) -> str:
    return (
        path.name.casefold()
        .replace("_l_russian", "_l_language")
        .replace("_l_english", "_l_language")
    )


def _pair_reference_files(
    target: Path,
    files: list[Path],
    english_target: Path | None,
    english_files: list[Path],
) -> dict[Path, Path]:
    if english_target is None or not files or not english_files:
        return {}
    if target.is_file() and english_target.is_file():
        return {target.resolve(): english_target.resolve()}

    english_by_relative: dict[str, Path] = {}
    english_by_name: dict[str, list[Path]] = defaultdict(list)
    for path in english_files:
        relative = path.relative_to(english_target)
        neutral_relative = relative.with_name(
            _neutral_localisation_name(relative)
        ).as_posix().casefold()
        english_by_relative[neutral_relative] = path
        english_by_name[_neutral_localisation_name(path)].append(path)

    paired: dict[Path, Path] = {}
    for path in files:
        relative = path.relative_to(target)
        neutral_relative = relative.with_name(
            _neutral_localisation_name(relative)
        ).as_posix().casefold()
        reference = english_by_relative.get(neutral_relative)
        if reference is None:
            matches = english_by_name.get(
                _neutral_localisation_name(path),
                [],
            )
            if len(matches) == 1:
                reference = matches[0]
        if reference is not None:
            paired[path.resolve()] = reference.resolve()
    return paired


def _visible_length(entry: LocalisationEntry) -> int:
    return sum(1 for _ in iter_rendered_characters(entry))


def _newline_escape_columns(entry: LocalisationEntry) -> list[int]:
    result: list[int] = []
    cursor = 0
    value = entry.raw_value
    while cursor < len(value):
        if value[cursor] == "\\" and cursor + 1 < len(value):
            if value[cursor + 1] == "n":
                result.append(entry.value_column + cursor)
            cursor += 2
            continue
        cursor += 1
    return result


def _newline_diagnostic(
    entry: LocalisationEntry,
    *,
    code: str,
    text_kind: str,
    message_label: str,
    role_confidence: str,
    role_evidence: str,
) -> Diagnostic | None:
    columns = _newline_escape_columns(entry)
    if not columns:
        return None
    return Diagnostic(
        severity="warning",
        code=code,
        path=entry.path,
        line=entry.line,
        column=columns[0],
        message=(
            f"{message_label} содержит {len(columns)} перенос(а) \\n."
        ),
        key=entry.key,
        character="\\n",
        text_kind=text_kind,
        selection_length=2,
        role_confidence=role_confidence,
        role_evidence=role_evidence,
    )


def _length_diagnostic(
    entry: LocalisationEntry,
    text_kind: str,
    limit: int,
    role_confidence: str,
    role_evidence: str,
) -> Diagnostic | None:
    measured = _visible_length(entry)
    if measured <= limit:
        return None
    dynamic_note = (
        " Значение содержит динамическую вставку; указана длина "
        "статической части."
        if _DYNAMIC_VALUE.search(entry.raw_value)
        else ""
    )
    over = measured - limit
    return Diagnostic(
        severity="warning",
        code="TEXT_TOO_LONG",
        path=entry.path,
        line=entry.line,
        column=entry.value_column,
        message=(
            f"{text_kind}: {measured} видимых символов при лимите "
            f"{limit}; превышение на {over}.{dynamic_note}"
        ),
        key=entry.key,
        text_kind=text_kind,
        measured_length=measured,
        limit=limit,
        role_confidence=role_confidence,
        role_evidence=role_evidence,
    )


def _role_explanation(
    context: FontContextIndex,
    key: str,
    role: str,
) -> tuple[str, str]:
    evidence = context.evidence_for_role(key, role)
    if not evidence:
        return "Не определено", "Источник назначения роли не записан."

    confidence_labels = {
        "confirmed": "Подтверждено",
        "structural": "Определено по структуре",
        "probable": "Предположительно",
    }

    def format_evidence(item: RoleEvidence) -> str:
        if item.source_path is None:
            location = "движковое правило"
        elif item.line > 0:
            location = f"{item.source_path}:{item.line}"
        else:
            location = str(item.source_path)
        return f"{location} — {item.rule}"

    shown = evidence[:3]
    explanation = " | ".join(
        format_evidence(item)
        for item in shown
    )
    if len(evidence) > len(shown):
        explanation += f" | ещё источников: {len(evidence) - len(shown)}"
    return (
        confidence_labels.get(
            evidence[0].confidence,
            evidence[0].confidence,
        ),
        explanation,
    )


def _preview_priority(
    language: str,
    mode: FocusPreviewPriorityMode,
) -> Literal["ru", "en"]:
    if mode in {"ru", "en"}:
        return mode
    normalized = language.casefold()
    if normalized == "l_russian":
        return "ru"
    if normalized == "l_english":
        return "en"
    return "en" if mode == "auto_en" else "ru"


def _exact_focus_diagnostic(
    candidate: _ExactFocusCandidate,
    result: FocusPreviewResult,
    limit: int,
) -> Diagnostic:
    measured = candidate.measured_length
    if measured > limit:
        threshold_note = (
            f"предварительный порог {limit} превышен на "
            f"{measured - limit}"
        )
    else:
        threshold_note = f"предварительный порог {limit} не превышен"

    if result.panel_overlap_px > 0:
        reason = (
            "описание пересекает панель «Эффект» на "
            f"{result.panel_overlap_px} px"
        )
    else:
        reason = "текст не помещается по точной визуальной проверке"
    glyph_note = ""
    if result.missing_glyphs:
        glyph_note = (
            " Отсутствуют в обоих атласах: "
            + " ".join(result.missing_glyphs)
            + "."
        )

    return Diagnostic(
        severity="warning",
        code="FOCUS_PREVIEW_RED",
        path=candidate.entry.path,
        line=candidate.entry.line,
        column=candidate.entry.value_column,
        message=(
            "Точный статус: красный. "
            f"{measured} видимых символов; {threshold_note}. "
            f"Строк: {result.description_lines}; высота: "
            f"{result.description_height_px} px; {reason}."
            f"{glyph_note}"
        ),
        key=candidate.entry.key,
        text_kind="Фокус",
        measured_length=measured,
        limit=limit,
        role_confidence=candidate.role_confidence,
        role_evidence=candidate.role_evidence,
        preview_status=result.status,
        preview_lines=result.description_lines,
        preview_height_px=result.description_height_px,
        preview_overlap_px=result.panel_overlap_px,
        missing_glyphs=" ".join(result.missing_glyphs),
    )


class TextLayoutChecker:
    def __init__(
        self,
        preview_factory: FocusPreviewFactory | None = None,
    ) -> None:
        self.preview_factory = preview_factory or FocusPreviewClient

    def scan(
        self,
        target: Path,
        mod_root: Path,
        options: TextLayoutOptions,
        english_target: Path | None = None,
        game_root: Path | None = None,
        progress: ProgressCallback | None = None,
        preview_started: PreviewStartCallback | None = None,
    ) -> TextLayoutResult:
        options.validate()
        target = target.resolve()
        files = _collect_files(target)
        english_root = (
            english_target.resolve()
            if english_target is not None
            else None
        )
        english_files = (
            _collect_files(english_root)
            if english_root is not None
            else []
        )
        entries: list[LocalisationEntry] = []
        english_entries: list[LocalisationEntry] = []
        total_files = len(files) + len(english_files)

        for index, path in enumerate(files, start=1):
            if progress is not None:
                progress(index, total_files, path)
            entries.extend(parse_localisation_file(path).entries)
        for offset, path in enumerate(english_files, start=1):
            if progress is not None:
                progress(len(files) + offset, total_files, path)
            english_entries.extend(parse_localisation_file(path).entries)

        english_locations: dict[str, Diagnostic] = {}
        for entry in english_entries:
            if entry.language.casefold() != "l_english":
                continue
            english_locations.setdefault(
                entry.key,
                Diagnostic(
                    severity="warning",
                    code="TEXT_LAYOUT_REFERENCE",
                    path=entry.path,
                    line=entry.line,
                    column=entry.value_column,
                    message="Английская запись для сопоставления.",
                    key=entry.key,
                ),
            )
        english_fallback_paths = _pair_reference_files(
            target,
            files,
            english_root,
            english_files,
        )

        localisation_values: dict[str, list[str]] = defaultdict(list)
        for entry in entries:
            localisation_values[entry.key].append(entry.raw_value)
        context = build_font_context(
            mod_root,
            (entry.key for entry in entries),
            game_root=game_root,
            localisation_values=localisation_values,
        )

        focus_checked = 0
        events_checked = 0
        welcome_checked = 0
        titles_checked = 0
        diagnostics: list[Diagnostic] = []
        exact_candidates: list[_ExactFocusCandidate] = []

        for entry in entries:
            roles = context.roles_for_key(entry.key)

            if options.focus_enabled and ROLE_FOCUS_DESCRIPTION in roles:
                focus_checked += 1
                confidence, evidence = _role_explanation(
                    context,
                    entry.key,
                    ROLE_FOCUS_DESCRIPTION,
                )
                if options.focus_mode == "newline":
                    diagnostic = _newline_diagnostic(
                        entry,
                        code="FOCUS_NEWLINE",
                        text_kind="Фокус",
                        message_label="Описание фокуса",
                        role_confidence=confidence,
                        role_evidence=evidence,
                    )
                    if diagnostic is not None:
                        diagnostics.append(diagnostic)
                elif options.focus_mode == "length":
                    diagnostic = _length_diagnostic(
                        entry,
                        "Фокус",
                        options.focus_limit,
                        confidence,
                        evidence,
                    )
                    if diagnostic is not None:
                        diagnostics.append(diagnostic)
                else:
                    exact_candidates.append(
                        _ExactFocusCandidate(
                            request_id=len(exact_candidates) + 1,
                            entry=entry,
                            measured_length=_visible_length(entry),
                            role_confidence=confidence,
                            role_evidence=evidence,
                        )
                    )

            if options.events_enabled and ROLE_EVENT_DESCRIPTION in roles:
                events_checked += 1
                confidence, evidence = _role_explanation(
                    context,
                    entry.key,
                    ROLE_EVENT_DESCRIPTION,
                )
                diagnostic = _length_diagnostic(
                    entry,
                    "Ивент",
                    options.event_limit,
                    confidence,
                    evidence,
                )
                if diagnostic is not None:
                    diagnostics.append(diagnostic)

            if options.title_newline_enabled:
                title_roles = (
                    (ROLE_FOCUS_NAME, "Заголовок фокуса"),
                    (ROLE_EVENT_TITLE, "Заголовок ивента"),
                    (
                        ROLE_WELCOME_TITLE,
                        "Заголовок вступительного экрана",
                    ),
                )
                for role, text_kind in title_roles:
                    if role not in roles:
                        continue
                    titles_checked += 1
                    confidence, evidence = _role_explanation(
                        context,
                        entry.key,
                        role,
                    )
                    diagnostic = _newline_diagnostic(
                        entry,
                        code="TITLE_NEWLINE",
                        text_kind=text_kind,
                        message_label=text_kind,
                        role_confidence=confidence,
                        role_evidence=evidence,
                    )
                    if diagnostic is not None:
                        diagnostics.append(diagnostic)

            if options.welcome_enabled and ROLE_WELCOME_TEXT in roles:
                welcome_checked += 1
                confidence, evidence = _role_explanation(
                    context,
                    entry.key,
                    ROLE_WELCOME_TEXT,
                )
                diagnostic = _length_diagnostic(
                    entry,
                    "Вступительный экран",
                    options.welcome_limit,
                    confidence,
                    evidence,
                )
                if diagnostic is not None:
                    diagnostics.append(diagnostic)

        preview_checked = 0
        preview_green = 0
        preview_yellow = 0
        preview_red = 0
        preview_errors = 0
        preview_version = ""
        preview_error_messages: tuple[str, ...] = ()
        if exact_candidates:
            if preview_started is not None:
                preview_started(len(exact_candidates))
            cli_path = options.focus_preview_cli_path
            if cli_path is None:
                raise ValueError(
                    "Для точной проверки не указан путь к CLI."
                )
            preview = self.preview_factory(cli_path).check(
                [
                    FocusPreviewRequestItem(
                        request_id=candidate.request_id,
                        key=candidate.entry.key,
                        description=candidate.entry.raw_value,
                        glyph_priority=_preview_priority(
                            candidate.entry.language,
                            options.focus_preview_priority,
                        ),
                    )
                    for candidate in exact_candidates
                ],
                policy="visual",
            )
            preview_checked = preview.total
            preview_green = preview.green
            preview_yellow = preview.yellow
            preview_red = preview.red
            preview_errors = len(preview.errors)
            preview_version = preview.version
            preview_error_messages = tuple(
                f"{item.key}: {item.code}: {item.message}"
                for item in preview.errors
            )
            candidates_by_id = {
                candidate.request_id: candidate
                for candidate in exact_candidates
            }
            for exact_result in preview.results:
                if exact_result.status != "red":
                    continue
                candidate = candidates_by_id.get(exact_result.request_id)
                if candidate is None:
                    raise ValueError(
                        "CLI вернул результат для неизвестного id "
                        f"{exact_result.request_id}."
                    )
                diagnostics.append(
                    _exact_focus_diagnostic(
                        candidate,
                        exact_result,
                        options.focus_limit,
                    )
                )

        diagnostics.sort(key=Diagnostic.sort_key)
        return TextLayoutResult(
            root=target,
            files_checked=len(files),
            entries_checked=len(entries),
            focus_checked=focus_checked,
            events_checked=events_checked,
            welcome_checked=welcome_checked,
            diagnostics=diagnostics,
            titles_checked=titles_checked,
            english_root=english_root,
            english_files_checked=len(english_files),
            english_entries_checked=len(english_entries),
            english_locations=english_locations,
            english_fallback_paths=english_fallback_paths,
            context_gui_files=context.gui_files_checked,
            context_script_files=context.script_files_checked,
            preview_checked=preview_checked,
            preview_green=preview_green,
            preview_yellow=preview_yellow,
            preview_red=preview_red,
            preview_errors=preview_errors,
            preview_version=preview_version,
            preview_error_messages=preview_error_messages,
        )
