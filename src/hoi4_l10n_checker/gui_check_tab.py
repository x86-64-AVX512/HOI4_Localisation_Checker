from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import ttk
from typing import cast

from .checker import GlyphMode, ScanResult
from .models import GLYPH_DIAGNOSTIC_CODES, Diagnostic

OpenDiagnosticCallback = Callable[[Diagnostic | None, tk.StringVar], str]
ExportCallback = Callable[[ttk.Treeview, str, tk.StringVar], None]


class LocalisationCheckTab:
    """Owns the main localisation-check tab and its presentation state."""

    def __init__(
        self,
        *,
        root: tk.Tk,
        notebook: ttk.Notebook,
        font_available: bool,
        font_status: str,
        show_unknown_context: bool,
        check_russian_straight_quotes: bool,
        notepad_fullscreen: bool,
        on_choose_file: Callable[[], None],
        on_choose_folder: Callable[[], None],
        on_open_exceptions: Callable[[], None],
        on_select_context_mod: Callable[[], Path | None],
        on_unknown_context_changed: Callable[[], None],
        on_russian_quotes_changed: Callable[[], None],
        on_notepad_mode_changed: Callable[[], None],
        on_open_diagnostic: OpenDiagnosticCallback,
        on_add_selected_exception: Callable[[], None],
        is_character_excluded: Callable[[str], bool],
        on_export: ExportCallback,
    ) -> None:
        self.root = root
        self.font_available = font_available
        self.font_status = font_status
        self._on_open_diagnostic = on_open_diagnostic
        self._on_add_selected_exception = on_add_selected_exception
        self._is_character_excluded = is_character_excluded
        self._on_export = on_export
        self.busy = False
        self.diagnostics_by_item: dict[str, Diagnostic] = {}

        self.frame = ttk.Frame(notebook, padding=12)
        notebook.add(self.frame, text="Проверка локализации")

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
        self.copy_character_button = ttk.Button(
            controls,
            text="Копировать символ",
            command=self.copy_selected_character,
            state=tk.DISABLED,
        )
        self.copy_character_button.pack(side=tk.LEFT, padx=(8, 0))
        self.export_button = ttk.Button(
            controls,
            text="Выгрузить результаты…",
            command=self._export_results,
            state=tk.DISABLED,
        )
        self.export_button.pack(side=tk.LEFT, padx=(8, 0))
        self.summary_var = tk.StringVar(value="Выберите .yml-файл или папку.")
        ttk.Label(controls, textvariable=self.summary_var).pack(
            side=tk.LEFT,
            padx=(18, 0),
        )

        mode_frame = ttk.LabelFrame(
            self.frame,
            text="Режим проверки символов",
            padding=(10, 6),
        )
        mode_frame.pack(fill=tk.X, pady=(10, 0))
        for column in range(3):
            mode_frame.columnconfigure(column, weight=1)

        self.glyph_mode_var = tk.StringVar(value="soft")
        initial_mode_state = tk.NORMAL if font_available else tk.DISABLED
        self.soft_mode_button = ttk.Radiobutton(
            mode_frame,
            text="Мягкий",
            variable=self.glyph_mode_var,
            value="soft",
            state=initial_mode_state,
        )
        self.soft_mode_button.grid(row=0, column=0, sticky=tk.W)
        ttk.Label(
            mode_frame,
            text=(
                "Для быстрой проверки. Символ допустим, если он есть хотя бы "
                "в одном шрифте. Может пропустить много неподдерживаемых символов."
            ),
            justify=tk.LEFT,
            wraplength=350,
        ).grid(row=1, column=0, sticky="ew", padx=(22, 14))

        self.strict_mode_button = ttk.Radiobutton(
            mode_frame,
            text="Жёсткий — классический",
            variable=self.glyph_mode_var,
            value="strict",
            state=initial_mode_state,
        )
        self.strict_mode_button.grid(row=0, column=1, sticky=tk.W)
        ttk.Label(
            mode_frame,
            text=(
                "Символ допустим, только если он есть в каждом используемом "
                "семействе шрифтов. Возможно много ложных срабатываний."
            ),
            justify=tk.LEFT,
            wraplength=350,
        ).grid(row=1, column=1, sticky="ew", padx=(22, 0))

        self.contextual_mode_button = ttk.Radiobutton(
            mode_frame,
            text="Жёсткий — контекстный",
            variable=self.glyph_mode_var,
            value="contextual",
            state=initial_mode_state,
        )
        self.contextual_mode_button.grid(
            row=0,
            column=2,
            sticky=tk.W,
            padx=(14, 0),
        )
        ttk.Label(
            mode_frame,
            text=(
                "Перепроверяет классические предупреждения по шрифту, "
                "назначенному ключу в интерфейсе. По умолчанию показывает "
                "только подтверждённое отсутствие глифа."
            ),
            justify=tk.LEFT,
            wraplength=350,
        ).grid(row=1, column=2, sticky="ew", padx=(36, 0))
        ttk.Label(
            mode_frame,
            text=(
                "Режим влияет только на предупреждения UNSAFE_GLYPH. "
                "Ошибки и остальные проверки одинаковы."
            ),
        ).grid(
            row=2,
            column=0,
            columnspan=2,
            sticky=tk.W,
            pady=(6, 0),
        )

        self.exceptions_button = ttk.Button(
            mode_frame,
            command=on_open_exceptions,
        )
        self.exceptions_button.grid(
            row=2,
            column=2,
            sticky=tk.E,
            pady=(6, 0),
        )

        context_path_frame = ttk.Frame(mode_frame)
        context_path_frame.grid(
            row=3,
            column=0,
            columnspan=3,
            sticky="ew",
            pady=(8, 0),
        )
        context_path_frame.columnconfigure(1, weight=1)
        ttk.Label(
            context_path_frame,
            text="Папка мода для контекстного режима:",
        ).grid(row=0, column=0, sticky=tk.W)
        self.context_mod_var = tk.StringVar()
        ttk.Label(
            context_path_frame,
            textvariable=self.context_mod_var,
            anchor=tk.W,
        ).grid(row=0, column=1, sticky="ew", padx=(8, 8))
        self.context_mod_button = ttk.Button(
            context_path_frame,
            text="Выбрать…",
            command=on_select_context_mod,
        )
        self.context_mod_button.grid(row=0, column=2, sticky=tk.E)

        self.show_unknown_context_var = tk.BooleanVar(value=show_unknown_context)
        self.show_unknown_context_button = ttk.Checkbutton(
            mode_frame,
            text=(
                "Показывать неопределённый контекст "
                "(может вернуть много ложных срабатываний)"
            ),
            variable=self.show_unknown_context_var,
            command=on_unknown_context_changed,
        )
        self.show_unknown_context_button.grid(
            row=4,
            column=0,
            columnspan=3,
            sticky=tk.W,
            pady=(7, 0),
        )

        additional_checks_frame = ttk.LabelFrame(
            self.frame,
            text="Дополнительные проверки",
            padding=(10, 6),
        )
        additional_checks_frame.pack(fill=tk.X, pady=(10, 0))
        self.russian_straight_quotes_var = tk.BooleanVar(
            value=check_russian_straight_quotes
        )
        self.russian_straight_quotes_button = ttk.Checkbutton(
            additional_checks_frame,
            text='Предупреждать о прямых кавычках "…" в русской локализации',
            variable=self.russian_straight_quotes_var,
            command=on_russian_quotes_changed,
        )
        self.russian_straight_quotes_button.pack(side=tk.LEFT)
        ttk.Label(
            additional_checks_frame,
            text=(
                "Проверяется только текст под l_russian:; "
                "служебные кавычки вокруг значения не учитываются."
            ),
        ).pack(side=tk.LEFT, padx=(16, 0))

        editor_frame = ttk.LabelFrame(
            self.frame,
            text="Открытие в Notepad++",
            padding=(10, 6),
        )
        editor_frame.pack(fill=tk.X, pady=(10, 0))
        self.notepad_fullscreen_var = tk.BooleanVar(value=notepad_fullscreen)
        self.notepad_fullscreen_button = ttk.Checkbutton(
            editor_frame,
            text="Открывать Notepad++ в полноэкранном режиме (F11)",
            variable=self.notepad_fullscreen_var,
            command=on_notepad_mode_changed,
        )
        self.notepad_fullscreen_button.pack(side=tk.LEFT)
        ttk.Label(
            editor_frame,
            text="Настройка сохраняется в settings.json рядом с программой.",
        ).pack(side=tk.LEFT, padx=(16, 0))

        self.progress = ttk.Progressbar(self.frame, mode="determinate")
        self.progress.pack(fill=tk.X, pady=(10, 4))
        self.current_file_var = tk.StringVar(value=font_status)
        ttk.Label(
            self.frame,
            textvariable=self.current_file_var,
            anchor=tk.W,
        ).pack(fill=tk.X, pady=(0, 8))

        table_frame = ttk.Frame(self.frame)
        table_frame.pack(fill=tk.BOTH, expand=True)
        columns = (
            "severity",
            "code",
            "file",
            "line",
            "column",
            "key",
            "message",
        )
        self.table = ttk.Treeview(
            table_frame,
            columns=columns,
            show="headings",
            selectmode="browse",
        )
        headings = {
            "severity": "Уровень",
            "code": "Проверка",
            "file": "Файл",
            "line": "Строка",
            "column": "Столбец",
            "key": "Ключ",
            "message": "Описание",
        }
        widths = {
            "severity": 80,
            "code": 190,
            "file": 310,
            "line": 65,
            "column": 70,
            "key": 210,
            "message": 520,
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
        self.table.tag_configure("error", foreground="#B00020")
        self.table.tag_configure("warning", foreground="#9A6700")

        detail_frame = ttk.LabelFrame(
            self.frame,
            text=("Полное сообщение — двойной щелчок открывает строку в Notepad++"),
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
        self.table.bind("<Button-3>", self._show_context_menu)

        self.context_menu = tk.Menu(root, tearoff=False)
        self.context_menu.add_command(
            label="Открыть в Notepad++",
            command=self.open_selected_diagnostic,
        )
        self.context_menu.add_separator()
        self.context_menu.add_command(
            label="Копировать ключ",
            command=self.copy_selected_key,
        )
        self.context_menu.add_command(
            label="Копировать символ",
            command=self.copy_selected_character,
        )
        self.context_menu.add_separator()
        self.context_menu.add_command(
            label="Добавить символ в исключения",
            command=self._on_add_selected_exception,
        )

    def glyph_mode(self) -> GlyphMode:
        return cast(GlyphMode, self.glyph_mode_var.get())

    def set_busy(self, busy: bool) -> None:
        self.busy = busy
        state = tk.DISABLED if busy else tk.NORMAL
        for widget in (
            self.file_button,
            self.folder_button,
            self.clear_button,
            self.exceptions_button,
            self.context_mod_button,
            self.show_unknown_context_button,
            self.russian_straight_quotes_button,
        ):
            widget.configure(state=state)
        mode_state = tk.NORMAL if not busy and self.font_available else tk.DISABLED
        self.soft_mode_button.configure(state=mode_state)
        self.strict_mode_button.configure(state=mode_state)
        self.contextual_mode_button.configure(state=mode_state)
        self.refresh_export_control()

    def refresh_export_control(self) -> None:
        self.export_button.configure(
            state=(
                tk.NORMAL
                if not self.busy and self.table.get_children("")
                else tk.DISABLED
            )
        )

    def set_exceptions_count(self, count: int) -> None:
        self.exceptions_button.configure(text=f"Исключения… ({count})")

    def set_context_status(self, message: str) -> None:
        self.context_mod_var.set(message)

    def set_status(self, message: str) -> None:
        self.current_file_var.set(message)

    def clear_results(self) -> None:
        for item in self.table.get_children():
            self.table.delete(item)
        self.diagnostics_by_item.clear()
        self.summary_var.set("Результаты очищены.")
        self.current_file_var.set(self.font_status)
        self.detail_var.set("")
        self.progress.configure(value=0, maximum=1)
        self.copy_key_button.configure(state=tk.DISABLED)
        self.copy_character_button.configure(state=tk.DISABLED)
        self.refresh_export_control()

    def prepare_scan(self, target: Path, status: str) -> None:
        self.clear_results()
        self.summary_var.set(f"Проверяется: {target}")
        self.current_file_var.set(status)

    def update_progress(self, current: int, total: int, path: Path) -> None:
        self.progress.configure(maximum=total, value=current)
        self.current_file_var.set(str(path))

    def show_failure(self) -> None:
        self.summary_var.set("Проверка завершилась внутренней ошибкой.")

    def show_result(self, result: ScanResult, glyph_mode: GlyphMode) -> None:
        self.summary_var.set(
            f"Файлов: {result.files_checked}; ключей: {result.entries_checked}; "
            f"ошибок: {result.error_count}; предупреждений: {result.warning_count}."
        )
        mode_name = {
            "soft": "мягкий",
            "strict": "жёсткий — классический",
            "contextual": "жёсткий — контекстный",
        }[glyph_mode]
        status = f"Проверка завершена ({mode_name}): {result.root}"
        if glyph_mode == "contextual":
            status += (
                f"; контекстных GUI-файлов: {result.context_gui_files}; "
                f"скриптовых файлов: {result.context_script_files}; "
                f"ключей со шрифтом: {result.context_resolved_keys}; "
                f"из них определено по типу: {result.context_semantic_keys}; "
                f"снято предупреждений: {result.contextual_filtered_warnings}; "
                f"неразрешённых: {result.contextual_unresolved_warnings}"
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
        level = "Ошибка" if diagnostic.severity == "error" else "Предупреждение"
        item = self.table.insert(
            "",
            tk.END,
            values=(
                level,
                diagnostic.code,
                str(diagnostic.path),
                diagnostic.line,
                diagnostic.column,
                diagnostic.key,
                diagnostic.message,
            ),
            tags=(diagnostic.severity,),
        )
        self.table.set(item, "message", diagnostic.message)
        self.diagnostics_by_item[item] = diagnostic

    def selected_diagnostic(self) -> Diagnostic | None:
        selected = self.table.selection()
        if not selected:
            return None
        return self.diagnostics_by_item.get(selected[0])

    def selected_key(self) -> str:
        diagnostic = self.selected_diagnostic()
        return diagnostic.key if diagnostic is not None else ""

    def selected_character(self) -> str:
        diagnostic = self.selected_diagnostic()
        if diagnostic is None or diagnostic.code not in GLYPH_DIAGNOSTIC_CODES:
            return ""
        return diagnostic.character

    def show_selected_detail(self, _event: object | None = None) -> None:
        selected = self.table.selection()
        if not selected:
            self.copy_key_button.configure(state=tk.DISABLED)
            self.copy_character_button.configure(state=tk.DISABLED)
            return
        values = self.table.item(selected[0], "values")
        if len(values) < 7:
            self.copy_key_button.configure(state=tk.DISABLED)
            self.copy_character_button.configure(state=tk.DISABLED)
            return
        diagnostic = self.diagnostics_by_item.get(selected[0])
        self.copy_key_button.configure(
            state=tk.NORMAL if str(values[5]) else tk.DISABLED
        )
        self.copy_character_button.configure(
            state=(
                tk.NORMAL
                if diagnostic is not None
                and diagnostic.code in GLYPH_DIAGNOSTIC_CODES
                and diagnostic.character
                else tk.DISABLED
            )
        )
        self.detail_var.set(f"{values[2]}:{values[3]}:{values[4]} — {values[6]}")

    def copy_selected_key(self, _event: object | None = None) -> str:
        key = self.selected_key()
        if not key:
            self.root.bell()
            return "break"
        self.root.clipboard_clear()
        self.root.clipboard_append(key)
        self.root.update_idletasks()
        self.current_file_var.set(f"Ключ скопирован: {key}")
        return "break"

    def copy_selected_character(self, _event: object | None = None) -> str:
        character = self.selected_character()
        if not character:
            self.root.bell()
            return "break"
        self.root.clipboard_clear()
        self.root.clipboard_append(character)
        self.root.update_idletasks()
        self.current_file_var.set(
            f"Символ скопирован: {character} (U+{ord(character):04X})"
        )
        return "break"

    def open_selected_diagnostic(
        self,
        _event: object | None = None,
    ) -> str:
        return self._on_open_diagnostic(
            self.selected_diagnostic(),
            self.current_file_var,
        )

    def _open_double_clicked_diagnostic(self, event: tk.Event) -> str:
        item = self.table.identify_row(event.y)
        if not item:
            return "break"
        self.table.selection_set(item)
        self.table.focus(item)
        return self.open_selected_diagnostic()

    def _show_context_menu(self, event: tk.Event) -> str:
        item = self.table.identify_row(event.y)
        if not item:
            return "break"
        self.table.selection_set(item)
        self.table.focus(item)
        diagnostic = self.selected_diagnostic()
        self.context_menu.entryconfigure(
            "Открыть в Notepad++",
            state=(
                tk.NORMAL
                if diagnostic is not None and diagnostic.path.is_file()
                else tk.DISABLED
            ),
        )
        key = self.selected_key()
        self.context_menu.entryconfigure(
            "Копировать ключ",
            state=tk.NORMAL if key else tk.DISABLED,
        )
        character = self.selected_character()
        self.context_menu.entryconfigure(
            "Копировать символ",
            state=tk.NORMAL if character else tk.DISABLED,
        )
        self.context_menu.entryconfigure(
            "Добавить символ в исключения",
            state=(
                tk.NORMAL
                if character and not self._is_character_excluded(character)
                else tk.DISABLED
            ),
        )
        try:
            self.context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.context_menu.grab_release()
        return "break"

    def _export_results(self) -> None:
        self._on_export(
            self.table,
            "localisation_check",
            self.current_file_var,
        )
