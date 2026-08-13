from __future__ import annotations

import threading
import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Protocol

from .background_tasks import BackgroundTaskRunner, TaskNotice
from .localisation_compare import (
    ComparisonIssue,
    ComparisonLanguage,
)
from .models import GLYPH_DIAGNOSTIC_CODES, Diagnostic
from .notepad_plus_plus import (
    NotepadPlusPlusError,
    OpenResult,
    find_notepad_plus_plus,
    open_location,
)

ExecutableFinder = Callable[[str], Path | None]
LocationOpener = Callable[..., OpenResult]
WorkerStarter = Callable[[Callable[[], None]], None]

_LANGUAGE_LABELS: dict[ComparisonLanguage, str] = {
    "english": "английский",
    "russian": "русский",
}


class LanguageDiagnosticSource(Protocol):
    def diagnostic_for(
        self,
        language: ComparisonLanguage,
    ) -> Diagnostic | None: ...


@dataclass(frozen=True, slots=True)
class OpenedComparisonFile:
    language: ComparisonLanguage
    diagnostic: Diagnostic
    result: OpenResult


@dataclass(frozen=True, slots=True)
class EditorOpenedNotice:
    diagnostic: Diagnostic
    result: OpenResult
    status_var: tk.StringVar


@dataclass(frozen=True, slots=True)
class EditorFailureNotice:
    error: Exception
    status_var: tk.StringVar


@dataclass(frozen=True, slots=True)
class ComparisonOpenedNotice:
    opened: tuple[OpenedComparisonFile, ...]
    status_var: tk.StringVar


@dataclass(frozen=True, slots=True)
class ComparisonFailureNotice:
    error: Exception
    opened: tuple[OpenedComparisonFile, ...]
    status_var: tk.StringVar


class NotepadPlusPlusController:
    """Coordinates Notepad++ discovery, background opening, and GUI feedback."""

    def __init__(
        self,
        root: tk.Misc,
        tasks: BackgroundTaskRunner,
        configured_path: Callable[[], str],
        remember_executable: Callable[[Path], None],
        fullscreen: Callable[[], bool],
        *,
        executable_finder: ExecutableFinder = find_notepad_plus_plus,
        location_opener: LocationOpener = open_location,
        worker_starter: WorkerStarter | None = None,
        executable_selector: Callable[[], str] | None = None,
        show_error: Callable[[str, str], object] | None = None,
    ) -> None:
        self.root = root
        self.tasks = tasks
        self._configured_path = configured_path
        self._remember_executable = remember_executable
        self._fullscreen = fullscreen
        self._executable_finder = executable_finder
        self._location_opener = location_opener
        self._worker_starter = worker_starter or self._start_worker
        self._executable_selector = executable_selector or self._select_executable
        self._show_error = show_error or messagebox.showerror

    def open_diagnostic(
        self,
        diagnostic: Diagnostic | None,
        status_var: tk.StringVar,
    ) -> str:
        if diagnostic is None:
            self.root.bell()
            return "break"
        if not diagnostic.path.is_file():
            self._show_error(
                "Файл не найден",
                f"Нельзя открыть файл диагностики:\n{diagnostic.path}",
            )
            return "break"

        executable = self.resolve_executable()
        if executable is None:
            status_var.set("Открытие в Notepad++ отменено.")
            return "break"

        selection_length = diagnostic.selection_length
        if (
            selection_length <= 0
            and diagnostic.code in GLYPH_DIAGNOSTIC_CODES
            and diagnostic.character
        ):
            selection_length = 1
        fullscreen = self._fullscreen()
        status_var.set(
            "Открывается в Notepad++: "
            f"{diagnostic.path}:{diagnostic.line}:{diagnostic.column}"
        )

        def work() -> None:
            try:
                result = self._location_opener(
                    executable=executable,
                    file_path=diagnostic.path,
                    line=diagnostic.line,
                    column=diagnostic.column,
                    selection_length=selection_length,
                    fullscreen=fullscreen,
                )
            except NotepadPlusPlusError as error:
                self.tasks.post_notice(
                    "editor",
                    "failure",
                    EditorFailureNotice(error, status_var),
                )
                return
            self.tasks.post_notice(
                "editor",
                "opened",
                EditorOpenedNotice(diagnostic, result, status_var),
            )

        self._worker_starter(work)
        return "break"

    def open_comparison(
        self,
        issue: ComparisonIssue | LanguageDiagnosticSource | None,
        languages: tuple[ComparisonLanguage, ...],
        status_var: tk.StringVar,
    ) -> str:
        diagnostics: list[tuple[ComparisonLanguage, Diagnostic]] = []
        if issue is not None:
            for language in languages:
                diagnostic = issue.diagnostic_for(language)
                if diagnostic is not None and diagnostic.path.is_file():
                    diagnostics.append((language, diagnostic))
        if not diagnostics:
            self.root.bell()
            return "break"

        executable = self.resolve_executable()
        if executable is None:
            status_var.set("Открытие в Notepad++ отменено.")
            return "break"

        requested = " и ".join(
            _LANGUAGE_LABELS[language]
            for language, _diagnostic in diagnostics
        )
        status_var.set(f"Открывается {requested} файл в Notepad++…")
        fullscreen = self._fullscreen()

        def work() -> None:
            opened: list[OpenedComparisonFile] = []
            try:
                for language, diagnostic in diagnostics:
                    result = self._location_opener(
                        executable=executable,
                        file_path=diagnostic.path,
                        line=diagnostic.line,
                        column=diagnostic.column,
                        selection_length=0,
                        fullscreen=fullscreen,
                    )
                    opened.append(
                        OpenedComparisonFile(language, diagnostic, result)
                    )
            except NotepadPlusPlusError as error:
                self.tasks.post_notice(
                    "compare_editor",
                    "failure",
                    ComparisonFailureNotice(
                        error,
                        tuple(opened),
                        status_var,
                    ),
                )
                return
            self.tasks.post_notice(
                "compare_editor",
                "opened",
                ComparisonOpenedNotice(tuple(opened), status_var),
            )

        self._worker_starter(work)
        return "break"

    def resolve_executable(self) -> Path | None:
        configured_path = self._configured_path()
        executable = self._executable_finder(configured_path)
        if executable is not None:
            if str(executable) != configured_path:
                self._remember_executable(executable)
            return executable

        selected = self._executable_selector()
        if not selected:
            return None

        executable = Path(selected)
        if not executable.is_file():
            self._show_error(
                "Notepad++ не найден",
                f"Указанный файл не существует:\n{executable}",
            )
            return None
        executable = executable.resolve()
        self._remember_executable(executable)
        return executable

    def handle_notice(self, event: TaskNotice) -> bool:
        if event.source == "editor":
            if event.kind == "opened" and isinstance(
                event.payload,
                EditorOpenedNotice,
            ):
                self._show_editor_result(event.payload)
            elif event.kind == "failure" and isinstance(
                event.payload,
                EditorFailureNotice,
            ):
                event.payload.status_var.set(
                    "Файл в Notepad++ открыть не удалось."
                )
                self._show_error(
                    "Не удалось открыть Notepad++",
                    str(event.payload.error),
                )
            return True

        if event.source == "compare_editor":
            if event.kind == "opened" and isinstance(
                event.payload,
                ComparisonOpenedNotice,
            ):
                self._show_comparison_result(event.payload)
            elif event.kind == "failure" and isinstance(
                event.payload,
                ComparisonFailureNotice,
            ):
                self._show_comparison_failure(event.payload)
            return True
        return False

    def _select_executable(self) -> str:
        return filedialog.askopenfilename(
            parent=self.root,
            title="Укажите notepad++.exe",
            filetypes=[
                ("Notepad++", "notepad++.exe"),
                ("Исполняемые файлы", "*.exe"),
                ("Все файлы", "*.*"),
            ],
        )

    @staticmethod
    def _start_worker(work: Callable[[], None]) -> None:
        threading.Thread(
            target=work,
            daemon=True,
            name="hoi4-l10n-notepad",
        ).start()

    @staticmethod
    def _show_editor_result(notice: EditorOpenedNotice) -> None:
        diagnostic = notice.diagnostic
        result = notice.result
        location = f"{diagnostic.path}:{diagnostic.line}:{diagnostic.column}"
        if result.character_selected:
            notice.status_var.set(
                f"Открыто в Notepad++; фрагмент выделен: {location}"
            )
        elif result.exact_position_set:
            notice.status_var.set(
                f"Открыто в Notepad++ на позиции: {location}"
            )
        else:
            notice.status_var.set(
                "Файл открыт в Notepad++ через строку и столбец: "
                f"{location}. Точное позиционирование через редактор "
                "не подтверждено."
            )

    @staticmethod
    def _show_comparison_result(notice: ComparisonOpenedNotice) -> None:
        opened = notice.opened
        if not opened:
            notice.status_var.set("Notepad++ не открыл ни одного файла.")
            return
        opened_labels = " и ".join(
            _LANGUAGE_LABELS[item.language] for item in opened
        )
        if len(opened) == 1:
            item = opened[0]
            diagnostic = item.diagnostic
            location = (
                f"{diagnostic.path}:"
                f"{diagnostic.line}:{diagnostic.column}"
            )
            if item.result.exact_position_set:
                notice.status_var.set(
                    f"Открыт {opened_labels} файл в Notepad++ "
                    f"на позиции: {location}"
                )
            else:
                notice.status_var.set(
                    f"Открыт {opened_labels} файл в Notepad++: "
                    f"{location}. Точная позиция не подтверждена."
                )
            return
        active = opened[-1]
        active_diagnostic = active.diagnostic
        notice.status_var.set(
            f"Открыты {opened_labels} файлы в Notepad++; "
            f"активен {_LANGUAGE_LABELS[active.language]}: "
            f"{active_diagnostic.path}:"
            f"{active_diagnostic.line}:{active_diagnostic.column}"
        )

    def _show_comparison_failure(
        self,
        notice: ComparisonFailureNotice,
    ) -> None:
        if notice.opened:
            notice.status_var.set(
                f"Открыто файлов: {len(notice.opened)}; "
                "следующий файл открыть не удалось."
            )
        else:
            notice.status_var.set(
                "Файлы в Notepad++ открыть не удалось."
            )
        self._show_error(
            "Не удалось открыть файл сравнения в Notepad++",
            str(notice.error),
        )
