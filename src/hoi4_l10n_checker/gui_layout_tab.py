from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import ttk
from typing import cast

from .models import Diagnostic
from .text_layout_checker import (
    FocusCheckMode,
    FocusPreviewPriorityMode,
    TextLayoutOptions,
    TextLayoutResult,
)

PREVIEW_PRIORITY_LABELS = {
    "auto_ru": "Авто; неизвестный язык → RU",
    "auto_en": "Авто; неизвестный язык → EN",
    "ru": "Всегда RU → EN",
    "en": "Всегда EN → RU",
}

ControlsChangedCallback = Callable[[object | None], str]
OpenDiagnosticCallback = Callable[[Diagnostic | None, tk.StringVar], str]
ExportCallback = Callable[[ttk.Treeview, str, tk.StringVar], None]


class TextLayoutTab:
    """Owns the text-length tab widgets and presentation state."""

    def __init__(
        self,
        *,
        root: tk.Tk,
        notebook: ttk.Notebook,
        options: TextLayoutOptions,
        on_choose_file: Callable[[], None],
        on_choose_folder: Callable[[], None],
        on_controls_changed: ControlsChangedCallback,
        on_select_context_mod: Callable[[], object],
        on_select_preview_cli: Callable[[], object],
        on_open_diagnostic: OpenDiagnosticCallback,
        on_export: ExportCallback,
    ) -> None:
        self.root = root
        self._on_open_diagnostic = on_open_diagnostic
        self._on_export = on_export
        self.busy = False
        self.diagnostics_by_item: dict[str, Diagnostic] = {}
        self.length_sort_descending = True

        self.frame = ttk.Frame(notebook, padding=12)
        notebook.add(self.frame, text="Длина текстов")

        controls = ttk.Frame(self.frame)
        controls.pack(fill=tk.X)
        self.file_button = ttk.Button(
            controls,
            text="Проверить файл",
            command=on_choose_file,
        )
        self.file_button.pack(side=tk.LEFT)
        self.folder_button = ttk.Button(
            controls,
            text="Проверить папку",
            command=on_choose_folder,
        )
        self.folder_button.pack(side=tk.LEFT, padx=(8, 0))
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
            value="Выберите .yml-файл или папку."
        )
        ttk.Label(controls, textvariable=self.summary_var).pack(
            side=tk.LEFT,
            padx=(18, 0),
        )

        checks = ttk.LabelFrame(
            self.frame,
            text="Что проверять",
            padding=(10, 8),
        )
        checks.pack(fill=tk.X, pady=(10, 0))
        for column in range(3):
            checks.columnconfigure(column, weight=1)

        focus_frame = ttk.LabelFrame(checks, text="Фокусы", padding=8)
        focus_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self.focus_enabled_var = tk.BooleanVar(value=options.focus_enabled)
        self.focus_enabled_button = ttk.Checkbutton(
            focus_frame,
            text="Проверять описания фокусов",
            variable=self.focus_enabled_var,
            command=on_controls_changed,
        )
        self.focus_enabled_button.grid(
            row=0,
            column=0,
            columnspan=4,
            sticky=tk.W,
        )
        self.focus_mode_var = tk.StringVar(value=options.focus_mode)
        self.focus_length_button = ttk.Radiobutton(
            focus_frame,
            text="Проверять только длину:",
            variable=self.focus_mode_var,
            value="length",
            command=on_controls_changed,
        )
        self.focus_length_button.grid(
            row=1,
            column=0,
            sticky=tk.W,
            pady=(6, 0),
        )
        self.focus_limit_var = tk.StringVar(value=str(options.focus_limit))
        self.focus_limit_entry = ttk.Entry(
            focus_frame,
            width=8,
            textvariable=self.focus_limit_var,
        )
        self.focus_limit_entry.grid(
            row=1,
            column=1,
            sticky=tk.W,
            padx=(6, 4),
            pady=(6, 0),
        )
        ttk.Label(focus_frame, text="символов").grid(
            row=1,
            column=2,
            sticky=tk.W,
            pady=(6, 0),
        )
        self.focus_newline_button = ttk.Radiobutton(
            focus_frame,
            text=r"Искать наличие \n",
            variable=self.focus_mode_var,
            value="newline",
            command=on_controls_changed,
        )
        self.focus_newline_button.grid(
            row=2,
            column=0,
            columnspan=4,
            sticky=tk.W,
            pady=(6, 0),
        )
        self.focus_exact_button = ttk.Radiobutton(
            focus_frame,
            text="Точная проверка вместимости",
            variable=self.focus_mode_var,
            value="exact",
            command=on_controls_changed,
        )
        self.focus_exact_button.grid(
            row=3,
            column=0,
            columnspan=4,
            sticky=tk.W,
            pady=(6, 0),
        )
        ttk.Label(focus_frame, text="Предварительный порог:").grid(
            row=4,
            column=0,
            sticky=tk.W,
            pady=(6, 0),
        )
        self.focus_exact_limit_entry = ttk.Entry(
            focus_frame,
            width=8,
            textvariable=self.focus_limit_var,
        )
        self.focus_exact_limit_entry.grid(
            row=4,
            column=1,
            sticky=tk.W,
            padx=(6, 4),
            pady=(6, 0),
        )
        ttk.Label(focus_frame, text="символов").grid(
            row=4,
            column=2,
            sticky=tk.W,
            pady=(6, 0),
        )

        events_frame = ttk.LabelFrame(checks, text="Ивенты", padding=8)
        events_frame.grid(row=0, column=1, sticky="nsew", padx=6)
        self.events_enabled_var = tk.BooleanVar(value=options.events_enabled)
        self.events_enabled_button = ttk.Checkbutton(
            events_frame,
            text="Проверять описания ивентов",
            variable=self.events_enabled_var,
            command=on_controls_changed,
        )
        self.events_enabled_button.grid(
            row=0,
            column=0,
            columnspan=3,
            sticky=tk.W,
        )
        ttk.Label(events_frame, text="Предупреждать после:").grid(
            row=1,
            column=0,
            sticky=tk.W,
            pady=(8, 0),
        )
        self.event_limit_var = tk.StringVar(value=str(options.event_limit))
        self.event_limit_entry = ttk.Entry(
            events_frame,
            width=8,
            textvariable=self.event_limit_var,
        )
        self.event_limit_entry.grid(
            row=1,
            column=1,
            sticky=tk.W,
            padx=(6, 4),
            pady=(8, 0),
        )
        ttk.Label(events_frame, text="символов").grid(
            row=1,
            column=2,
            sticky=tk.W,
            pady=(8, 0),
        )

        welcome_frame = ttk.LabelFrame(
            checks,
            text="Вступительные экраны",
            padding=8,
        )
        welcome_frame.grid(row=0, column=2, sticky="nsew", padx=(6, 0))
        self.welcome_enabled_var = tk.BooleanVar(
            value=options.welcome_enabled
        )
        self.welcome_enabled_button = ttk.Checkbutton(
            welcome_frame,
            text="Проверять основной текст",
            variable=self.welcome_enabled_var,
            command=on_controls_changed,
        )
        self.welcome_enabled_button.grid(
            row=0,
            column=0,
            columnspan=3,
            sticky=tk.W,
        )
        ttk.Label(welcome_frame, text="Предупреждать после:").grid(
            row=1,
            column=0,
            sticky=tk.W,
            pady=(8, 0),
        )
        self.welcome_limit_var = tk.StringVar(value=str(options.welcome_limit))
        self.welcome_limit_entry = ttk.Entry(
            welcome_frame,
            width=8,
            textvariable=self.welcome_limit_var,
        )
        self.welcome_limit_entry.grid(
            row=1,
            column=1,
            sticky=tk.W,
            padx=(6, 4),
            pady=(8, 0),
        )
        ttk.Label(welcome_frame, text="символов").grid(
            row=1,
            column=2,
            sticky=tk.W,
            pady=(8, 0),
        )

        for entry in (
            self.focus_limit_entry,
            self.focus_exact_limit_entry,
            self.event_limit_entry,
            self.welcome_limit_entry,
        ):
            entry.bind("<FocusOut>", on_controls_changed)
            entry.bind("<Return>", on_controls_changed)

        ttk.Label(
            checks,
            text=(
                "Памятка для русской локализации: описание фокуса — "
                "примерно 345–350 символов; описание ивента и основной "
                "текст вступительного экрана — примерно 3400."
            ),
            justify=tk.LEFT,
        ).grid(
            row=1,
            column=0,
            columnspan=3,
            sticky=tk.W,
            pady=(8, 0),
        )

        context_frame = ttk.Frame(checks)
        context_frame.grid(
            row=2,
            column=0,
            columnspan=3,
            sticky="ew",
            pady=(8, 0),
        )
        context_frame.columnconfigure(1, weight=1)
        ttk.Label(
            context_frame,
            text="Папка мода для определения типов текстов:",
        ).grid(row=0, column=0, sticky=tk.W)
        self.context_mod_var = tk.StringVar()
        ttk.Label(
            context_frame,
            textvariable=self.context_mod_var,
            anchor=tk.W,
        ).grid(row=0, column=1, sticky="ew", padx=(8, 8))
        self.context_mod_button = ttk.Button(
            context_frame,
            text="Выбрать…",
            command=on_select_context_mod,
        )
        self.context_mod_button.grid(row=0, column=2, sticky=tk.E)

        preview_frame = ttk.LabelFrame(
            self.frame,
            text="Точная проверка фокусов через EaW Focus Text Preview",
            padding=(10, 8),
        )
        preview_frame.pack(fill=tk.X, pady=(10, 0))
        preview_frame.columnconfigure(1, weight=1)
        ttk.Label(preview_frame, text="EaWFocusTextPreviewCLI.exe:").grid(
            row=0,
            column=0,
            sticky=tk.W,
        )
        self.preview_cli_var = tk.StringVar()
        ttk.Label(
            preview_frame,
            textvariable=self.preview_cli_var,
            anchor=tk.W,
        ).grid(row=0, column=1, sticky="ew", padx=(8, 8))
        self.preview_cli_button = ttk.Button(
            preview_frame,
            text="Выбрать…",
            command=on_select_preview_cli,
        )
        self.preview_cli_button.grid(row=0, column=2, sticky=tk.E)

        ttk.Label(preview_frame, text="Приоритет атласов:").grid(
            row=1,
            column=0,
            sticky=tk.W,
            pady=(8, 0),
        )
        self.preview_priority_var = tk.StringVar(
            value=PREVIEW_PRIORITY_LABELS[options.focus_preview_priority]
        )
        self.preview_priority_combo = ttk.Combobox(
            preview_frame,
            textvariable=self.preview_priority_var,
            values=tuple(PREVIEW_PRIORITY_LABELS.values()),
            state="readonly",
            width=35,
        )
        self.preview_priority_combo.grid(
            row=1,
            column=1,
            sticky=tk.W,
            padx=(8, 8),
            pady=(8, 0),
        )
        self.preview_priority_combo.bind(
            "<<ComboboxSelected>>",
            on_controls_changed,
        )
        ttk.Label(
            preview_frame,
            text=(
                "Проверяются все описания. В таблицу попадают только "
                "фокусы с красным статусом. Жёлтый статус всегда "
                "считается допустимым; зелёные и жёлтые результаты "
                "видны только в сводке."
            ),
            justify=tk.LEFT,
        ).grid(
            row=2,
            column=0,
            columnspan=3,
            sticky=tk.W,
            pady=(8, 0),
        )

        self.progress = ttk.Progressbar(self.frame, mode="determinate")
        self.progress.pack(fill=tk.X, pady=(10, 4))
        self.current_file_var = tk.StringVar(
            value="Настройте проверки и выберите файл или папку."
        )
        ttk.Label(
            self.frame,
            textvariable=self.current_file_var,
            anchor=tk.W,
        ).pack(fill=tk.X, pady=(0, 8))

        table_frame = ttk.Frame(self.frame)
        table_frame.pack(fill=tk.BOTH, expand=True)
        columns = (
            "code",
            "kind",
            "confidence",
            "evidence",
            "file",
            "line",
            "column",
            "key",
            "length",
            "limit",
            "preview_status",
            "preview_lines",
            "preview_height",
            "preview_overlap",
            "missing_glyphs",
            "message",
        )
        self.table = ttk.Treeview(
            table_frame,
            columns=columns,
            show="headings",
            selectmode="browse",
        )
        headings = {
            "code": "Проверка",
            "kind": "Тип текста",
            "confidence": "Надёжность роли",
            "evidence": "Основание роли",
            "file": "Файл",
            "line": "Строка",
            "column": "Столбец",
            "key": "Ключ",
            "length": "Длина",
            "limit": "Лимит",
            "preview_status": "Точный статус",
            "preview_lines": "Строк",
            "preview_height": "Высота, px",
            "preview_overlap": "Пересечение, px",
            "missing_glyphs": "Нет глифов",
            "message": "Описание",
        }
        widths = {
            "code": 150,
            "kind": 145,
            "confidence": 155,
            "evidence": 420,
            "file": 300,
            "line": 65,
            "column": 70,
            "key": 220,
            "length": 70,
            "limit": 70,
            "preview_status": 105,
            "preview_lines": 65,
            "preview_height": 90,
            "preview_overlap": 120,
            "missing_glyphs": 120,
            "message": 480,
        }
        for column in columns:
            self.table.heading(column, text=headings[column])
            self.table.column(
                column,
                width=widths[column],
                minwidth=50,
                stretch=column in {"file", "key", "message"},
                anchor=tk.W,
            )
        self.table.heading(
            "length",
            text="Длина ↕",
            command=self.sort_by_length,
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
        self.table.tag_configure("warning", foreground="#9A6700")
        self.table.tag_configure("preview_red", foreground="#B42318")

        detail_frame = ttk.LabelFrame(
            self.frame,
            text=(
                "Полное сообщение — двойной щелчок открывает строку "
                "в Notepad++"
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
        self.table.bind("<Double-1>", self._open_double_clicked_diagnostic)
        self.refresh_controls()

    @staticmethod
    def _positive_limit(value: str, label: str) -> int:
        try:
            parsed = int(value.strip())
        except ValueError as error:
            raise ValueError(
                f"Лимит для {label} должен быть целым числом."
            ) from error
        if parsed <= 0:
            raise ValueError(f"Лимит для {label} должен быть больше нуля.")
        return parsed

    def capture_options(self, preview_cli_path: str) -> TextLayoutOptions:
        focus_mode = cast(FocusCheckMode, self.focus_mode_var.get())
        if focus_mode not in {"length", "newline", "exact"}:
            raise ValueError("Выберите режим проверки фокусов.")

        preview_priority = next(
            (
                value
                for value, label in PREVIEW_PRIORITY_LABELS.items()
                if label == self.preview_priority_var.get()
            ),
            "",
        )
        if preview_priority not in {"auto_ru", "auto_en", "ru", "en"}:
            raise ValueError("Выберите приоритет атласов.")

        return TextLayoutOptions(
            focus_enabled=self.focus_enabled_var.get(),
            focus_mode=focus_mode,
            focus_limit=self._positive_limit(
                self.focus_limit_var.get(),
                "фокусов",
            ),
            focus_preview_cli_path=(
                Path(preview_cli_path) if preview_cli_path else None
            ),
            focus_preview_priority=cast(
                FocusPreviewPriorityMode,
                preview_priority,
            ),
            events_enabled=self.events_enabled_var.get(),
            event_limit=self._positive_limit(
                self.event_limit_var.get(),
                "ивентов",
            ),
            welcome_enabled=self.welcome_enabled_var.get(),
            welcome_limit=self._positive_limit(
                self.welcome_limit_var.get(),
                "вступительных экранов",
            ),
        )

    def restore_options(self, options: TextLayoutOptions) -> None:
        self.focus_enabled_var.set(options.focus_enabled)
        self.focus_mode_var.set(options.focus_mode)
        self.focus_limit_var.set(str(options.focus_limit))
        self.preview_priority_var.set(
            PREVIEW_PRIORITY_LABELS[options.focus_preview_priority]
        )
        self.events_enabled_var.set(options.events_enabled)
        self.event_limit_var.set(str(options.event_limit))
        self.welcome_enabled_var.set(options.welcome_enabled)
        self.welcome_limit_var.set(str(options.welcome_limit))

    def set_busy(self, busy: bool) -> None:
        self.busy = busy
        self.refresh_controls()
        self.refresh_export_control()

    def refresh_controls(self) -> None:
        base_state = tk.DISABLED if self.busy else tk.NORMAL
        for widget in (
            self.clear_button,
            self.context_mod_button,
            self.focus_enabled_button,
            self.events_enabled_button,
            self.welcome_enabled_button,
        ):
            widget.configure(state=base_state)
        any_check_enabled = (
            self.focus_enabled_var.get()
            or self.events_enabled_var.get()
            or self.welcome_enabled_var.get()
        )
        scan_state = (
            tk.NORMAL if not self.busy and any_check_enabled else tk.DISABLED
        )
        self.file_button.configure(state=scan_state)
        self.folder_button.configure(state=scan_state)

        focus_enabled = not self.busy and self.focus_enabled_var.get()
        focus_mode_state = tk.NORMAL if focus_enabled else tk.DISABLED
        self.focus_length_button.configure(state=focus_mode_state)
        self.focus_newline_button.configure(state=focus_mode_state)
        self.focus_exact_button.configure(state=focus_mode_state)
        self.focus_limit_entry.configure(
            state=(
                tk.NORMAL
                if focus_enabled and self.focus_mode_var.get() == "length"
                else tk.DISABLED
            )
        )
        self.focus_exact_limit_entry.configure(
            state=(
                tk.NORMAL
                if focus_enabled and self.focus_mode_var.get() == "exact"
                else tk.DISABLED
            )
        )
        preview_enabled = focus_enabled and self.focus_mode_var.get() == "exact"
        self.preview_cli_button.configure(
            state=tk.NORMAL if preview_enabled else tk.DISABLED
        )
        self.preview_priority_combo.configure(
            state="readonly" if preview_enabled else tk.DISABLED
        )
        self.event_limit_entry.configure(
            state=(
                tk.NORMAL
                if not self.busy and self.events_enabled_var.get()
                else tk.DISABLED
            )
        )
        self.welcome_limit_entry.configure(
            state=(
                tk.NORMAL
                if not self.busy and self.welcome_enabled_var.get()
                else tk.DISABLED
            )
        )

    def set_context_status(self, message: str) -> None:
        self.context_mod_var.set(message)

    def set_preview_cli_status(self, message: str) -> None:
        self.preview_cli_var.set(message)

    def set_status(self, message: str) -> None:
        self.current_file_var.set(message)

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
        self.diagnostics_by_item.clear()
        self.summary_var.set("Результаты очищены.")
        self.current_file_var.set(
            "Настройте проверки и выберите файл или папку."
        )
        self.detail_var.set("")
        self.progress.stop()
        self.progress.configure(mode="determinate", value=0, maximum=1)
        self.copy_key_button.configure(state=tk.DISABLED)
        self.refresh_export_control()

    def prepare_scan(self, target: Path, context_status: str) -> None:
        self.clear_results()
        self.summary_var.set(f"Проверяется: {target}")
        self.current_file_var.set(context_status)

    def update_progress(self, current: int, total: int, path: Path) -> None:
        self.progress.configure(maximum=total, value=current)
        self.current_file_var.set(str(path))

    def show_preview_started(self, total: int) -> None:
        self.progress.configure(mode="indeterminate")
        self.progress.start(12)
        self.current_file_var.set(
            "Точная проверка через EaW Focus Text Preview: "
            f"{total} описаний фокусов. Это может занять некоторое время…"
        )

    def show_failure(self) -> None:
        self.progress.stop()
        self.progress.configure(mode="determinate")
        self.summary_var.set("Проверка завершилась внутренней ошибкой.")

    def show_result(self, result: TextLayoutResult) -> None:
        self.progress.stop()
        self.progress.configure(mode="determinate")
        summary = (
            f"Файлов: {result.files_checked}; "
            f"фокусов: {result.focus_checked}; "
            f"ивентов: {result.events_checked}; "
            f"вступительных экранов: {result.welcome_checked}; "
            f"предупреждений: {result.warning_count}."
        )
        if result.preview_checked:
            summary += (
                f" Точно проверено: {result.preview_checked}; "
                f"зелёных: {result.preview_green}; "
                f"жёлтых: {result.preview_yellow}; "
                f"красных: {result.preview_red}; "
                f"ошибок CLI: {result.preview_errors}."
            )
        self.summary_var.set(summary)

        status = (
            f"Проверка завершена: {result.root}; "
            f"превышений длины: {result.length_warning_count}; "
            f"фокусов с \\n: {result.newline_warning_count}; "
            f"GUI-файлов: {result.context_gui_files}; "
            f"скриптовых файлов: {result.context_script_files}"
        )
        if result.preview_checked:
            status += (
                f"; красных точных результатов: "
                f"{result.exact_red_warning_count}; "
                f"EaW Preview: {result.preview_version or 'версия не указана'}"
            )
        self.current_file_var.set(status)
        self.progress.configure(
            maximum=max(result.files_checked, 1),
            value=result.files_checked,
        )
        for diagnostic in result.diagnostics:
            self._insert_diagnostic(diagnostic)
        if not result.diagnostics:
            self.detail_var.set("Проблем не обнаружено.")
        self.refresh_export_control()

    def _insert_diagnostic(self, diagnostic: Diagnostic) -> None:
        item = self.table.insert(
            "",
            tk.END,
            values=(
                diagnostic.code,
                diagnostic.text_kind,
                diagnostic.role_confidence,
                diagnostic.role_evidence,
                str(diagnostic.path),
                diagnostic.line,
                diagnostic.column,
                diagnostic.key,
                diagnostic.measured_length or "",
                diagnostic.limit or "",
                {
                    "green": "Зелёный",
                    "yellow": "Жёлтый",
                    "red": "Красный",
                }.get(diagnostic.preview_status, diagnostic.preview_status),
                diagnostic.preview_lines or "",
                diagnostic.preview_height_px or "",
                diagnostic.preview_overlap_px or "",
                diagnostic.missing_glyphs,
                diagnostic.message,
            ),
            tags=(
                (
                    "preview_red"
                    if diagnostic.code == "FOCUS_PREVIEW_RED"
                    else "warning"
                ),
            ),
        )
        self.diagnostics_by_item[item] = diagnostic

    def sort_by_length(self) -> None:
        descending = self.length_sort_descending
        rows = [
            (item, self.diagnostics_by_item.get(item))
            for item in self.table.get_children("")
        ]

        def sort_key(row: tuple[str, Diagnostic | None]) -> tuple[bool, int]:
            diagnostic = row[1]
            measured = (
                diagnostic.measured_length if diagnostic is not None else 0
            )
            return measured <= 0, -measured if descending else measured

        rows.sort(key=sort_key)
        for position, (item, _) in enumerate(rows):
            self.table.move(item, "", position)
        self.table.heading(
            "length",
            text="Длина ↓" if descending else "Длина ↑",
            command=self.sort_by_length,
        )
        self.length_sort_descending = not descending

    def selected_diagnostic(self) -> Diagnostic | None:
        selected = self.table.selection()
        if not selected:
            return None
        return self.diagnostics_by_item.get(selected[0])

    def show_selected_detail(self, _event: object | None = None) -> None:
        diagnostic = self.selected_diagnostic()
        self.copy_key_button.configure(
            state=(
                tk.NORMAL
                if diagnostic is not None and diagnostic.key
                else tk.DISABLED
            )
        )
        if diagnostic is None:
            return
        self.detail_var.set(
            f"{diagnostic.path}:{diagnostic.line}:{diagnostic.column} — "
            f"{diagnostic.message} Основание роли: "
            f"{diagnostic.role_evidence}"
        )

    def copy_selected_key(self, _event: object | None = None) -> str:
        diagnostic = self.selected_diagnostic()
        if diagnostic is None or not diagnostic.key:
            self.root.bell()
            return "break"
        self.root.clipboard_clear()
        self.root.clipboard_append(diagnostic.key)
        self.root.update_idletasks()
        self.current_file_var.set(f"Ключ скопирован: {diagnostic.key}")
        return "break"

    def _open_double_clicked_diagnostic(self, event: tk.Event) -> str:
        item = self.table.identify_row(event.y)
        if not item:
            return "break"
        self.table.selection_set(item)
        self.table.focus(item)
        return self._on_open_diagnostic(
            self.selected_diagnostic(),
            self.current_file_var,
        )

    def _export_results(self) -> None:
        self._on_export(self.table, "text_layout", self.current_file_var)
