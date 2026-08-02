from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal, Protocol

from .font_context import (
    ROLE_EVENT_DESCRIPTION,
    ROLE_FOCUS_DESCRIPTION,
    ROLE_WELCOME_TEXT,
    FontContextIndex,
    RoleEvidence,
    build_font_context,
)
from .focus_preview_cli import (
    FocusPreviewBatchResult,
    FocusPreviewClient,
    FocusPreviewRequestItem,
    FocusPreviewResult,
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
    def exact_red_warning_count(self) -> int:
        return sum(
            item.code == "FOCUS_PREVIEW_RED"
            for item in self.diagnostics
        )


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
        game_root: Path | None = None,
        progress: ProgressCallback | None = None,
        preview_started: PreviewStartCallback | None = None,
    ) -> TextLayoutResult:
        options.validate()
        target = target.resolve()
        files = _collect_files(target)
        entries: list[LocalisationEntry] = []

        for index, path in enumerate(files, start=1):
            if progress is not None:
                progress(index, len(files), path)
            entries.extend(parse_localisation_file(path).entries)

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
                    columns = _newline_escape_columns(entry)
                    if columns:
                        diagnostics.append(
                            Diagnostic(
                                severity="warning",
                                code="FOCUS_NEWLINE",
                                path=entry.path,
                                line=entry.line,
                                column=columns[0],
                                message=(
                                    "Описание фокуса содержит "
                                    f"{len(columns)} перенос(а) \\n."
                                ),
                                key=entry.key,
                                character="\\n",
                                text_kind="Фокус",
                                selection_length=2,
                                role_confidence=confidence,
                                role_evidence=evidence,
                            )
                        )
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
