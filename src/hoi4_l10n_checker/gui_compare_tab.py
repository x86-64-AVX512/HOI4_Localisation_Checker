from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import ttk

from .gui_compare_files import (
    ComparisonFileExclusions,
    ComparisonFilesDialog,
)
from .gui_requirements import RequirementIndicator
from .localisation_compare import (
    ComparisonIssue,
    ComparisonLanguage,
    LocalisationComparisonResult,
)

FILTER_LABELS = {
    "Все проблемы": "all",
    "Только отсутствующие ключи": "missing",
    "Нет в русской": "missing_russian",
    "Нет в английской": "missing_english",
    "Только дубли": "duplicates",
    "Только ошибки файлов": "parse_error",
}

SelectFolderCallback = Callable[[ComparisonLanguage], Path | None]
OpenLanguagesCallback = Callable[[tuple[ComparisonLanguage, ...]], str]
ExportCallback = Callable[[ttk.Treeview, str, tk.StringVar], None]


class ComparisonTab:
    """Owns the key-comparison tab widgets and presentation state."""

    def __init__(
        self,
        *,
        root: tk.Tk,
        notebook: ttk.Notebook,
        on_run: Callable[[], None],
        on_select_folder: SelectFolderCallback,
        on_open_languages: OpenLanguagesCallback,
        on_export: ExportCallback,
    ) -> None:
        self.root = root
        self._on_open_languages = on_open_languages
        self._on_export = on_export
        self.busy = False
        self.issues_by_item: dict[str, ComparisonIssue] = {}
        self.all_issues: list[ComparisonIssue] = []
        self.key_sort_descending = False
        self.comparison_roots: dict[ComparisonLanguage, Path | None] = {
            "english": None,
            "russian": None,
        }
        self.file_exclusions: ComparisonFileExclusions = {
            "english": set(),
            "russian": set(),
        }

        self.frame = ttk.Frame(notebook, padding=12)
        notebook.add(self.frame, text="Сравнение ключей")

        controls = ttk.Frame(self.frame)
        controls.pack(fill=tk.X)
        self.run_button = ttk.Button(
            controls,
            text="Сравнить локализации",
            command=on_run,
        )
        self.run_button.pack(side=tk.LEFT)
        self.clear_button = ttk.Button(
            controls,
            text="Очистить результаты",
            command=self.clear_results,
        )
        self.clear_button.pack(side=tk.LEFT, padx=(8, 0))
        self.copy_key_button = ttk.Button(
            controls,
            text="Копировать ключ",
            command=self.copy_selected_key,
            state=tk.DISABLED,
        )
        self.copy_key_button.pack(side=tk.LEFT, padx=(8, 0))
        self.export_button = ttk.Button(
            controls,
            text="Выгрузить результаты…",
            command=self._export_results,
            state=tk.DISABLED,
        )
        self.export_button.pack(side=tk.LEFT, padx=(8, 0))
        self.summary_var = tk.StringVar(
            value="Укажите папку мода и запустите сравнение."
        )
        ttk.Label(controls, textvariable=self.summary_var).pack(
            side=tk.LEFT,
            padx=(18, 0),
        )

        settings_frame = ttk.LabelFrame(
            self.frame,
            text="Сравнение английской и русской локализаций",
            padding=(10, 8),
        )
        settings_frame.pack(fill=tk.X, pady=(10, 0))
        settings_frame.columnconfigure(1, weight=1)
        ttk.Label(
            settings_frame,
            text="Папка английской локализации:",
        ).grid(row=0, column=0, sticky=tk.W)
        self.path_indicators: dict[
            ComparisonLanguage,
            RequirementIndicator,
        ] = {}
        self.english_path_indicator = RequirementIndicator(settings_frame)
        self.english_path_indicator.grid(
            row=0,
            column=1,
            sticky="ew",
            padx=(8, 8),
        )
        self.path_indicators["english"] = self.english_path_indicator
        self.english_path_button = ttk.Button(
            settings_frame,
            text="Выбрать…",
            command=lambda: on_select_folder("english"),
        )
        self.english_path_button.grid(row=0, column=2, sticky=tk.E)

        ttk.Label(
            settings_frame,
            text="Папка русской локализации:",
        ).grid(row=1, column=0, sticky=tk.W, pady=(8, 0))
        self.russian_path_indicator = RequirementIndicator(settings_frame)
        self.russian_path_indicator.grid(
            row=1,
            column=1,
            sticky="ew",
            padx=(8, 8),
            pady=(8, 0),
        )
        self.path_indicators["russian"] = self.russian_path_indicator
        self.russian_path_button = ttk.Button(
            settings_frame,
            text="Выбрать…",
            command=lambda: on_select_folder("russian"),
        )
        self.russian_path_button.grid(
            row=1,
            column=2,
            sticky=tk.E,
            pady=(8, 0),
        )
        ttk.Label(
            settings_frame,
            text="Файлы сравнения:",
        ).grid(row=2, column=0, sticky=tk.W, pady=(8, 0))
        self.file_exclusions_var = tk.StringVar()
        ttk.Label(
            settings_frame,
            textvariable=self.file_exclusions_var,
        ).grid(
            row=2,
            column=1,
            sticky=tk.W,
            padx=(8, 8),
            pady=(8, 0),
        )
        self.file_exclusions_button = ttk.Button(
            settings_frame,
            text="Настроить…",
            command=self.open_file_exclusions,
        )
        self.file_exclusions_button.grid(
            row=2,
            column=2,
            sticky=tk.E,
            pady=(8, 0),
        )
        ttk.Label(
            settings_frame,
            text=(
                "Обе папки проверяются рекурсивно. В английской части "
                "учитываются записи под l_english:, в русской — под "
                "l_russian:. Папки могут находиться где угодно. Исключения "
                "файлов действуют только в текущей сессии."
            ),
            justify=tk.LEFT,
        ).grid(
            row=3,
            column=0,
            columnspan=3,
            sticky=tk.W,
            pady=(8, 0),
        )

        filter_frame = ttk.Frame(self.frame)
        filter_frame.pack(fill=tk.X, pady=(10, 0))
        ttk.Label(filter_frame, text="Показывать:").pack(side=tk.LEFT)
        self.filter_var = tk.StringVar(value="Все проблемы")
        self.filter_combo = ttk.Combobox(
            filter_frame,
            textvariable=self.filter_var,
            values=tuple(FILTER_LABELS),
            state="readonly",
            width=30,
        )
        self.filter_combo.pack(side=tk.LEFT, padx=(8, 0))
        self.filter_combo.bind("<<ComboboxSelected>>", self.apply_filter)
        self.visible_var = tk.StringVar(value="")
        ttk.Label(filter_frame, textvariable=self.visible_var).pack(
            side=tk.LEFT,
            padx=(16, 0),
        )
        self.open_both_button = ttk.Button(
            filter_frame,
            text="Открыть оба",
            command=lambda: self._open_selected(("english", "russian")),
            state=tk.DISABLED,
        )
        self.open_both_button.pack(side=tk.RIGHT)
        self.open_russian_button = ttk.Button(
            filter_frame,
            text="Открыть русский",
            command=lambda: self._open_selected(("russian",)),
            state=tk.DISABLED,
        )
        self.open_russian_button.pack(side=tk.RIGHT, padx=(0, 8))
        self.open_english_button = ttk.Button(
            filter_frame,
            text="Открыть английский",
            command=lambda: self._open_selected(("english",)),
            state=tk.DISABLED,
        )
        self.open_english_button.pack(side=tk.RIGHT, padx=(0, 8))

        self.progress = ttk.Progressbar(self.frame, mode="determinate")
        self.progress.pack(fill=tk.X, pady=(10, 4))
        self.status_var = tk.StringVar(
            value="Сравнение ещё не запускалось."
        )
        ttk.Label(
            self.frame,
            textvariable=self.status_var,
            anchor=tk.W,
        ).pack(fill=tk.X, pady=(0, 8))

        table_frame = ttk.Frame(self.frame)
        table_frame.pack(fill=tk.BOTH, expand=True)
        columns = (
            "problem",
            "code",
            "key",
            "language",
            "file",
            "line",
            "column",
            "value",
            "message",
        )
        self.table = ttk.Treeview(
            table_frame,
            columns=columns,
            show="headings",
            selectmode="browse",
        )
        headings = {
            "problem": "Различие",
            "code": "Код",
            "key": "Ключ",
            "language": "Существующая запись",
            "file": "Файл",
            "line": "Строка",
            "column": "Столбец",
            "value": "Значение",
            "message": "Описание",
        }
        widths = {
            "problem": 155,
            "code": 190,
            "key": 240,
            "language": 150,
            "file": 340,
            "line": 65,
            "column": 70,
            "value": 320,
            "message": 480,
        }
        for column in columns:
            self.table.heading(column, text=headings[column])
            self.table.column(
                column,
                width=widths[column],
                minwidth=50,
                stretch=column in {"key", "file", "value", "message"},
                anchor=tk.W,
            )
        self.table.heading(
            "key",
            text="Ключ ↕",
            command=self.sort_by_key,
        )

        vertical = ttk.Scrollbar(
            table_frame,
            orient=tk.VERTICAL,
            command=self.table.yview,
        )
        horizontal = ttk.Scrollbar(
            table_frame,
            orient=tk.HORIZONTAL,
            command=self.table.xview,
        )
        self.table.configure(
            yscrollcommand=vertical.set,
            xscrollcommand=horizontal.set,
        )
        self.table.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)
        self.table.tag_configure("missing", foreground="#9A6700")
        self.table.tag_configure("duplicate", foreground="#7A4E00")
        self.table.tag_configure("error", foreground="#B00020")

        detail_frame = ttk.LabelFrame(
            self.frame,
            text=(
                "Полное сообщение — двойной щелчок позволяет выбрать "
                "английский, русский или оба файла"
            ),
            padding=6,
        )
        detail_frame.pack(fill=tk.X, pady=(10, 0))
        self.detail_var = tk.StringVar(value="")
        ttk.Label(
            detail_frame,
            textvariable=self.detail_var,
            anchor=tk.W,
            justify=tk.LEFT,
            wraplength=1120,
        ).pack(fill=tk.X)

        self.table.bind("<<TreeviewSelect>>", self.show_selected_detail)
        self.table.bind("<Control-c>", self.copy_selected_key)
        self.table.bind("<Control-C>", self.copy_selected_key)
        self.table.bind("<Double-1>", self._show_context_menu)
        self.table.bind("<Button-3>", self._show_context_menu)
        self.context_menu = tk.Menu(root, tearoff=False)
        self.context_menu.add_command(
            label="Открыть английский файл",
            command=lambda: self._open_selected(("english",)),
        )
        self.context_menu.add_command(
            label="Открыть русский файл",
            command=lambda: self._open_selected(("russian",)),
        )
        self.context_menu.add_command(
            label="Открыть оба файла",
            command=lambda: self._open_selected(("english", "russian")),
        )
        self.context_menu.add_separator()
        self.context_menu.add_command(
            label="Копировать ключ",
            command=self.copy_selected_key,
        )
        self._refresh_file_exclusions_status()
        self.refresh_controls()

    def set_paths(self, english_path: str, russian_path: str) -> None:
        for language, raw_path, indicator, label in (
            (
                "english",
                english_path,
                self.english_path_indicator,
                "английская",
            ),
            (
                "russian",
                russian_path,
                self.russian_path_indicator,
                "русская",
            ),
        ):
            if not raw_path:
                self._set_comparison_root(language, None)
                indicator.set(
                    False,
                    f"не выбрана — {label} папка обязательна",
                )
                continue
            path = Path(raw_path)
            valid = path.is_dir()
            self._set_comparison_root(
                language,
                path.resolve() if valid else None,
            )
            indicator.set(
                valid,
                str(path) if valid else f"папка недоступна: {path}",
            )
        self._refresh_file_exclusions_status()
        self.refresh_controls()

    def _set_comparison_root(
        self,
        language: ComparisonLanguage,
        root: Path | None,
    ) -> None:
        if self.comparison_roots[language] == root:
            return
        self.comparison_roots[language] = root
        self.file_exclusions[language].clear()

    def excluded_files(
        self,
        language: ComparisonLanguage,
    ) -> frozenset[Path]:
        return frozenset(self.file_exclusions[language])

    def replace_file_exclusions(
        self,
        exclusions: ComparisonFileExclusions,
    ) -> None:
        self.file_exclusions = {
            language: {path.resolve() for path in exclusions[language]}
            for language in ("english", "russian")
        }
        self._refresh_file_exclusions_status()

    def open_file_exclusions(self) -> None:
        roots = self._available_comparison_roots()
        if roots is None:
            self.root.bell()
            self.status_var.set(
                "Сначала выберите обе папки локализации."
            )
            return
        result = ComparisonFilesDialog(
            self.root,
            roots,
            self.file_exclusions,
        ).show()
        if result is None:
            return
        self.replace_file_exclusions(result)
        self.status_var.set(
            "Временный список файлов сравнения обновлён."
        )

    def _available_comparison_roots(
        self,
    ) -> dict[ComparisonLanguage, Path] | None:
        english = self.comparison_roots["english"]
        russian = self.comparison_roots["russian"]
        if english is None or russian is None:
            return None
        if not english.is_dir() or not russian.is_dir():
            return None
        return {"english": english, "russian": russian}

    def _refresh_file_exclusions_status(self) -> None:
        english = len(self.file_exclusions["english"])
        russian = len(self.file_exclusions["russian"])
        self.file_exclusions_var.set(
            f"временно исключено: EN — {english}, RU — {russian}"
        )

    def flash_path_requirement(
        self,
        language: ComparisonLanguage,
    ) -> None:
        self.path_indicators[language].flash()

    def set_busy(self, busy: bool) -> None:
        self.busy = busy
        self.refresh_controls()
        self.refresh_export_control()

    def refresh_controls(self) -> None:
        state = tk.DISABLED if self.busy else tk.NORMAL
        self.run_button.configure(state=state)
        self.clear_button.configure(state=state)
        self.english_path_button.configure(state=state)
        self.russian_path_button.configure(state=state)
        self.file_exclusions_button.configure(
            state=(
                tk.NORMAL
                if not self.busy
                and self._available_comparison_roots() is not None
                else tk.DISABLED
            )
        )
        self.filter_combo.configure(
            state=tk.DISABLED if self.busy else "readonly"
        )
        self._refresh_open_controls(self.selected_issue())

    def refresh_export_control(self) -> None:
        self.export_button.configure(
            state=(
                tk.NORMAL
                if not self.busy and self.table.get_children("")
                else tk.DISABLED
            )
        )

    def clear_results(self) -> None:
        for item in self.table.get_children():
            self.table.delete(item)
        self.issues_by_item.clear()
        self.all_issues.clear()
        self.summary_var.set("Результаты очищены.")
        self.visible_var.set("")
        self.status_var.set("Укажите папку мода и запустите сравнение.")
        self.detail_var.set("")
        self.progress.configure(value=0, maximum=1)
        self.copy_key_button.configure(state=tk.DISABLED)
        self._refresh_open_controls(None)
        self.refresh_export_control()

    def prepare_comparison(self, english_root: Path, russian_root: Path) -> None:
        self.clear_results()
        self.summary_var.set("Чтение файлов локализации…")
        excluded = sum(len(paths) for paths in self.file_exclusions.values())
        suffix = f"; временно исключено: {excluded}" if excluded else ""
        self.status_var.set(
            f"EN: {english_root}; RU: {russian_root}{suffix}"
        )

    def update_progress(self, current: int, total: int, path: Path) -> None:
        self.progress.configure(maximum=total, value=current)
        self.status_var.set(str(path))

    def show_result(self, result: LocalisationComparisonResult) -> None:
        self.summary_var.set(
            f"Файлов: {result.files_checked} "
            f"(EN: {result.english_files}, RU: {result.russian_files}); "
            f"исключено: {result.files_excluded} "
            f"(EN: {result.english_files_excluded}, "
            f"RU: {result.russian_files_excluded}); "
            f"уникальных ключей EN: {result.english_keys}, "
            f"RU: {result.russian_keys}; совпадают: {result.common_keys}."
        )
        self.status_var.set(
            f"Сравнение завершено: нет в русской — "
            f"{result.missing_russian}; нет в английской — "
            f"{result.missing_english}; дублей — "
            f"{result.duplicate_count}; ошибок разбора — "
            f"{result.parse_errors}."
        )
        self.progress.configure(
            maximum=max(result.files_checked, 1),
            value=result.files_checked,
        )
        self.all_issues = list(result.issues)
        self.apply_filter()

    def show_failure(self) -> None:
        self.summary_var.set("Сравнение завершилось внутренней ошибкой.")

    @staticmethod
    def issue_matches(issue: ComparisonIssue, selected_filter: str) -> bool:
        if selected_filter == "all":
            return True
        if selected_filter == "missing":
            return issue.category in {"missing_russian", "missing_english"}
        if selected_filter == "duplicates":
            return issue.category in {"duplicate_english", "duplicate_russian"}
        return issue.category == selected_filter

    def apply_filter(self, _event: object | None = None) -> str:
        selected_filter = FILTER_LABELS.get(self.filter_var.get(), "all")
        for item in self.table.get_children():
            self.table.delete(item)
        self.issues_by_item.clear()
        self.copy_key_button.configure(state=tk.DISABLED)
        self._refresh_open_controls(None)
        self.detail_var.set("")

        visible = [
            issue
            for issue in self.all_issues
            if self.issue_matches(issue, selected_filter)
        ]
        for issue in visible:
            self._insert_issue(issue)
        self.visible_var.set(
            f"Показано: {len(visible)} из {len(self.all_issues)}"
        )
        if not visible and self.all_issues:
            self.detail_var.set("Для выбранного фильтра результатов нет.")
        elif not self.all_issues:
            self.detail_var.set(
                "Различий, дублей и ошибок разбора не обнаружено."
            )
        self.refresh_export_control()
        return "break"

    @staticmethod
    def _value_preview(value: str) -> str:
        normalized = value.replace("\r", " ").replace("\n", " ")
        if len(normalized) <= 180:
            return normalized
        return normalized[:177] + "…"

    def _insert_issue(self, issue: ComparisonIssue) -> None:
        if issue.category == "parse_error":
            tag = "error"
        elif issue.category.startswith("duplicate_"):
            tag = "duplicate"
        else:
            tag = "missing"
        item = self.table.insert(
            "",
            tk.END,
            values=(
                issue.label,
                issue.code,
                issue.key,
                issue.language,
                str(issue.path),
                issue.line,
                issue.column,
                self._value_preview(issue.raw_value),
                issue.message,
            ),
            tags=(tag,),
        )
        self.issues_by_item[item] = issue

    def sort_by_key(self) -> None:
        descending = self.key_sort_descending
        rows = [
            (item, self.issues_by_item.get(item))
            for item in self.table.get_children("")
        ]

        def sort_key(
            row: tuple[str, ComparisonIssue | None],
        ) -> tuple[str, str, int]:
            issue = row[1]
            if issue is None:
                return "", "", 0
            return (
                issue.key.casefold(),
                str(issue.path).casefold(),
                issue.line,
            )

        rows.sort(key=sort_key, reverse=descending)
        rows.sort(key=lambda row: not bool(row[1] is not None and row[1].key))
        for position, (item, _) in enumerate(rows):
            self.table.move(item, "", position)
        self.table.heading(
            "key",
            text="Ключ ↓" if descending else "Ключ ↑",
            command=self.sort_by_key,
        )
        self.key_sort_descending = not descending

    def selected_issue(self) -> ComparisonIssue | None:
        selected = self.table.selection()
        if not selected:
            return None
        return self.issues_by_item.get(selected[0])

    def show_selected_detail(self, _event: object | None = None) -> None:
        issue = self.selected_issue()
        self.copy_key_button.configure(
            state=tk.NORMAL if issue is not None and issue.key else tk.DISABLED
        )
        self._refresh_open_controls(issue)
        if issue is None:
            return
        value = f" Значение: {issue.raw_value}" if issue.raw_value else ""
        self.detail_var.set(
            f"{issue.path}:{issue.line}:{issue.column} — "
            f"{issue.message}{value}"
        )

    def copy_selected_key(self, _event: object | None = None) -> str:
        issue = self.selected_issue()
        if issue is None or not issue.key:
            self.root.bell()
            return "break"
        self.root.clipboard_clear()
        self.root.clipboard_append(issue.key)
        self.root.update_idletasks()
        self.status_var.set(f"Ключ скопирован: {issue.key}")
        return "break"

    @staticmethod
    def language_available(
        issue: ComparisonIssue | None,
        language: ComparisonLanguage,
    ) -> bool:
        if issue is None:
            return False
        diagnostic = issue.diagnostic_for(language)
        return diagnostic is not None and diagnostic.path.is_file()

    def _refresh_open_controls(self, issue: ComparisonIssue | None) -> None:
        english_available = (
            not self.busy and self.language_available(issue, "english")
        )
        russian_available = (
            not self.busy and self.language_available(issue, "russian")
        )
        self.open_english_button.configure(
            state=tk.NORMAL if english_available else tk.DISABLED
        )
        self.open_russian_button.configure(
            state=tk.NORMAL if russian_available else tk.DISABLED
        )
        self.open_both_button.configure(
            state=(
                tk.NORMAL
                if english_available and russian_available
                else tk.DISABLED
            )
        )

    def _show_context_menu(self, event: tk.Event) -> str:
        item = self.table.identify_row(event.y)
        if not item:
            return "break"
        self.table.selection_set(item)
        self.table.focus(item)
        issue = self.issues_by_item.get(item)
        self.show_selected_detail()
        english_available = (
            not self.busy and self.language_available(issue, "english")
        )
        russian_available = (
            not self.busy and self.language_available(issue, "russian")
        )
        self.context_menu.entryconfigure(
            "Открыть английский файл",
            state=tk.NORMAL if english_available else tk.DISABLED,
        )
        self.context_menu.entryconfigure(
            "Открыть русский файл",
            state=tk.NORMAL if russian_available else tk.DISABLED,
        )
        self.context_menu.entryconfigure(
            "Открыть оба файла",
            state=(
                tk.NORMAL
                if english_available and russian_available
                else tk.DISABLED
            ),
        )
        self.context_menu.entryconfigure(
            "Копировать ключ",
            state=tk.NORMAL if issue is not None and issue.key else tk.DISABLED,
        )
        try:
            self.context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.context_menu.grab_release()
        return "break"

    def _open_selected(
        self,
        languages: tuple[ComparisonLanguage, ...],
    ) -> str:
        return self._on_open_languages(languages)

    def _export_results(self) -> None:
        self._on_export(self.table, "key_comparison", self.status_var)
