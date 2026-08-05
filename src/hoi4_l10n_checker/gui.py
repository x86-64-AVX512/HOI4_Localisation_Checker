from __future__ import annotations

import threading
import tkinter as tk
import unicodedata
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import cast

from .background_tasks import (
    BackgroundTaskRunner,
    TaskFailed,
    TaskNotice,
    TaskProgress,
    TaskReporter,
    TaskSucceeded,
)
from .checker import GlyphMode, LocalisationChecker, ScanResult
from .csv_export import export_csv
from .focus_preview_cli import (
    FocusPreviewError,
    validate_focus_preview_installation,
)
from .font_context import (
    find_hoi4_install,
    find_mod_root,
    is_context_root,
    mod_display_name,
)
from .font_profile import FontProfile, FontProfileError
from .gui_compare_tab import ComparisonTab
from .gui_layout_tab import TextLayoutTab
from .localisation_compare import (
    ComparisonLanguage,
    LocalisationComparator,
    LocalisationComparisonResult,
)
from .models import Diagnostic
from .notepad_plus_plus import (
    NotepadPlusPlusError,
    OpenResult,
    find_notepad_plus_plus,
    open_location,
)
from .settings import (
    AppSettings,
    SettingsError,
    load_settings,
    save_settings,
    settings_path_for,
)
from .text_layout_checker import (
    TextLayoutChecker,
    TextLayoutOptions,
    TextLayoutResult,
)
from .version import DISPLAY_VERSION

_GLYPH_DIAGNOSTIC_CODES = frozenset(
    {"UNSAFE_GLYPH", "UNKNOWN_FONT_CONTEXT"}
)
class CheckerApplication:
    def __init__(self, root: tk.Tk, app_root: Path) -> None:
        self.root = root
        self.app_root = app_root
        self.tasks = BackgroundTaskRunner()
        self.busy = False
        self.diagnostics_by_item: dict[str, Diagnostic] = {}
        self.settings_path = settings_path_for(app_root)
        self.settings_error = ""
        self.exceptions_dialog: tk.Toplevel | None = None
        self.exceptions_listbox: tk.Listbox | None = None
        self.exception_list_characters: list[str] = []

        try:
            settings = load_settings(self.settings_path)
            self.excluded_characters = set(settings.excluded_characters)
            self.notepad_plus_plus_path = settings.notepad_plus_plus_path
            self.notepad_plus_plus_fullscreen = (
                settings.notepad_plus_plus_fullscreen
            )
            self.context_mod_path = settings.context_mod_path
            self.hoi4_install_path = settings.hoi4_install_path
            self.show_unknown_context_warnings = (
                settings.show_unknown_context_warnings
            )
            self.check_russian_straight_quotes = (
                settings.check_russian_straight_quotes
            )
            self.layout_focus_enabled = settings.layout_focus_enabled
            self.layout_focus_mode = settings.layout_focus_mode
            self.layout_focus_limit = settings.layout_focus_limit
            self.layout_focus_preview_cli_path = (
                settings.layout_focus_preview_cli_path
            )
            self.layout_focus_preview_priority = (
                settings.layout_focus_preview_priority
            )
            self.layout_events_enabled = settings.layout_events_enabled
            self.layout_event_limit = settings.layout_event_limit
            self.layout_welcome_enabled = settings.layout_welcome_enabled
            self.layout_welcome_limit = settings.layout_welcome_limit
            self.compare_english_path = settings.compare_english_path
            self.compare_russian_path = settings.compare_russian_path
            self.export_directory = settings.export_directory
        except SettingsError as error:
            self.excluded_characters: set[str] = set()
            self.notepad_plus_plus_path = ""
            self.notepad_plus_plus_fullscreen = False
            self.context_mod_path = ""
            self.hoi4_install_path = ""
            self.show_unknown_context_warnings = False
            self.check_russian_straight_quotes = True
            self.layout_focus_enabled = True
            self.layout_focus_mode = "length"
            self.layout_focus_limit = 350
            self.layout_focus_preview_cli_path = ""
            self.layout_focus_preview_priority = "auto_ru"
            self.layout_events_enabled = True
            self.layout_event_limit = 3400
            self.layout_welcome_enabled = True
            self.layout_welcome_limit = 3400
            self.compare_english_path = ""
            self.compare_russian_path = ""
            self.export_directory = ""
            self.settings_error = str(error)

        self.root.title(f"HOI4 Localisation Checker — {DISPLAY_VERSION}")
        self.root.geometry("1180x900")
        self.root.minsize(900, 620)

        try:
            self.font_profile = FontProfile.load(app_root)
            self.font_status = (
                f"Профиль шрифтов загружен: "
                f"{len(self.font_profile.available_languages)} языков."
            )
        except FontProfileError as error:
            self.font_profile = None
            self.font_status = f"Проверка символов отключена: {error}"

        self.checker = LocalisationChecker(self.font_profile)
        self.text_layout_checker = TextLayoutChecker()
        self.localisation_comparator = LocalisationComparator()
        self._build_ui()
        self.root.after(100, self._poll_events)

        if self.settings_error:
            self.root.after(
                300,
                lambda: messagebox.showwarning(
                    "Настройки не загружены",
                    self.settings_error,
                ),
            )

        if self.font_profile is None:
            self.root.after(
                250,
                lambda: messagebox.showwarning(
                    "Профиль шрифтов не загружен",
                    self.font_status
                    + "\n\nПроверки UTF-8, BOM, кавычек, ключей и escape-последовательностей "
                    "останутся доступны.",
                ),
            )

    def _build_ui(self) -> None:
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True)
        outer = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(outer, text="Проверка локализации")

        controls = ttk.Frame(outer)
        controls.pack(fill=tk.X)

        self.file_button = ttk.Button(
            controls,
            text="Проверить файл",
            command=self._choose_file,
        )
        self.file_button.pack(side=tk.LEFT)

        self.folder_button = ttk.Button(
            controls,
            text="Проверить папку",
            command=self._choose_folder,
        )
        self.folder_button.pack(side=tk.LEFT, padx=(8, 0))

        self.clear_button = ttk.Button(
            controls,
            text="Очистить результаты",
            command=self._clear_results,
        )
        self.clear_button.pack(side=tk.LEFT, padx=(8, 0))

        self.copy_key_button = ttk.Button(
            controls,
            text="Копировать ключ",
            command=self._copy_selected_key,
            state=tk.DISABLED,
        )
        self.copy_key_button.pack(side=tk.LEFT, padx=(8, 0))

        self.copy_character_button = ttk.Button(
            controls,
            text="Копировать символ",
            command=self._copy_selected_character,
            state=tk.DISABLED,
        )
        self.copy_character_button.pack(side=tk.LEFT, padx=(8, 0))

        self.export_button = ttk.Button(
            controls,
            text="Выгрузить результаты…",
            command=lambda: self._export_table_results(
                self.table,
                "localisation_check",
                self.current_file_var,
            ),
            state=tk.DISABLED,
        )
        self.export_button.pack(side=tk.LEFT, padx=(8, 0))

        self.summary_var = tk.StringVar(value="Выберите .yml-файл или папку.")
        ttk.Label(controls, textvariable=self.summary_var).pack(
            side=tk.LEFT,
            padx=(18, 0),
        )

        mode_frame = ttk.LabelFrame(
            outer,
            text="Режим проверки символов",
            padding=(10, 6),
        )
        mode_frame.pack(fill=tk.X, pady=(10, 0))
        mode_frame.columnconfigure(0, weight=1)
        mode_frame.columnconfigure(1, weight=1)
        mode_frame.columnconfigure(2, weight=1)

        self.glyph_mode_var = tk.StringVar(value="soft")
        initial_mode_state = (
            tk.NORMAL if self.font_profile is not None else tk.DISABLED
        )
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
            command=self._open_exceptions_dialog,
        )
        self.exceptions_button.grid(
            row=2,
            column=2,
            sticky=tk.E,
            pady=(6, 0),
        )
        self._refresh_exceptions_ui()

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
            command=self._select_context_mod,
        )
        self.context_mod_button.grid(row=0, column=2, sticky=tk.E)
        self._refresh_context_mod_ui()

        self.show_unknown_context_var = tk.BooleanVar(
            value=self.show_unknown_context_warnings
        )
        self.show_unknown_context_button = ttk.Checkbutton(
            mode_frame,
            text=(
                "Показывать неопределённый контекст "
                "(может вернуть много ложных срабатываний)"
            ),
            variable=self.show_unknown_context_var,
            command=self._unknown_context_visibility_changed,
        )
        self.show_unknown_context_button.grid(
            row=4,
            column=0,
            columnspan=3,
            sticky=tk.W,
            pady=(7, 0),
        )

        additional_checks_frame = ttk.LabelFrame(
            outer,
            text="Дополнительные проверки",
            padding=(10, 6),
        )
        additional_checks_frame.pack(fill=tk.X, pady=(10, 0))
        self.russian_straight_quotes_var = tk.BooleanVar(
            value=self.check_russian_straight_quotes
        )
        self.russian_straight_quotes_button = ttk.Checkbutton(
            additional_checks_frame,
            text=(
                'Предупреждать о прямых кавычках "…" '
                "в русской локализации"
            ),
            variable=self.russian_straight_quotes_var,
            command=self._russian_straight_quotes_changed,
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
            outer,
            text="Открытие в Notepad++",
            padding=(10, 6),
        )
        editor_frame.pack(fill=tk.X, pady=(10, 0))
        self.notepad_fullscreen_var = tk.BooleanVar(
            value=self.notepad_plus_plus_fullscreen
        )
        ttk.Checkbutton(
            editor_frame,
            text="Открывать Notepad++ в полноэкранном режиме (F11)",
            variable=self.notepad_fullscreen_var,
            command=self._notepad_window_mode_changed,
        ).pack(side=tk.LEFT)
        ttk.Label(
            editor_frame,
            text="Настройка сохраняется в settings.json рядом с программой.",
        ).pack(side=tk.LEFT, padx=(16, 0))

        self.progress = ttk.Progressbar(outer, mode="determinate")
        self.progress.pack(fill=tk.X, pady=(10, 4))

        self.current_file_var = tk.StringVar(value=self.font_status)
        ttk.Label(
            outer,
            textvariable=self.current_file_var,
            anchor=tk.W,
        ).pack(fill=tk.X, pady=(0, 8))

        table_frame = ttk.Frame(outer)
        table_frame.pack(fill=tk.BOTH, expand=True)

        columns = ("severity", "code", "file", "line", "column", "key", "message")
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
            outer,
            text="Полное сообщение — двойной щелчок открывает строку в Notepad++",
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
        self.table.bind("<<TreeviewSelect>>", self._show_selected_detail)
        self.table.bind("<Control-c>", self._copy_selected_key)
        self.table.bind("<Control-C>", self._copy_selected_key)
        self.table.bind("<Double-1>", self._open_double_clicked_diagnostic)
        self.table.bind("<Button-3>", self._show_context_menu)

        self.context_menu = tk.Menu(self.root, tearoff=False)
        self.context_menu.add_command(
            label="Открыть в Notepad++",
            command=self._open_selected_diagnostic,
        )
        self.context_menu.add_separator()
        self.context_menu.add_command(
            label="Копировать ключ",
            command=self._copy_selected_key,
        )
        self.context_menu.add_command(
            label="Копировать символ",
            command=self._copy_selected_character,
        )
        self.context_menu.add_separator()
        self.context_menu.add_command(
            label="Добавить символ в исключения",
            command=self._add_selected_character_to_exceptions,
        )

        self._build_layout_tab()
        self._build_compare_tab()
        self._refresh_export_controls()

    def _build_layout_tab(self) -> None:
        options = TextLayoutOptions(
            focus_enabled=self.layout_focus_enabled,
            focus_mode=self.layout_focus_mode,
            focus_limit=self.layout_focus_limit,
            focus_preview_cli_path=(
                Path(self.layout_focus_preview_cli_path)
                if self.layout_focus_preview_cli_path
                else None
            ),
            focus_preview_priority=self.layout_focus_preview_priority,
            events_enabled=self.layout_events_enabled,
            event_limit=self.layout_event_limit,
            welcome_enabled=self.layout_welcome_enabled,
            welcome_limit=self.layout_welcome_limit,
        )
        self.layout_tab = TextLayoutTab(
            root=self.root,
            notebook=self.notebook,
            options=options,
            on_choose_file=self._choose_layout_file,
            on_choose_folder=self._choose_layout_folder,
            on_controls_changed=self._layout_controls_changed,
            on_select_context_mod=self._select_context_mod,
            on_select_preview_cli=self._select_focus_preview_cli,
            on_open_diagnostic=self._open_diagnostic,
            on_export=self._export_table_results,
        )
        self._refresh_layout_controls()
        self._refresh_context_mod_ui()
        self._refresh_focus_preview_ui()

    def _build_compare_tab(self) -> None:
        self.compare_tab = ComparisonTab(
            root=self.root,
            notebook=self.notebook,
            on_run=self._start_localisation_comparison,
            on_select_folder=self._select_compare_folder,
            on_open_languages=self._open_compare_selected_languages,
            on_export=self._export_table_results,
        )
        self._refresh_compare_paths_ui()
        self._refresh_compare_controls()

    def _choose_file(self) -> None:
        selected = filedialog.askopenfilename(
            title="Выберите файл локализации",
            filetypes=[
                ("HOI4 localisation", "*.yml"),
                ("Все файлы", "*.*"),
            ],
        )
        if selected:
            self._start_scan(Path(selected))

    def _choose_folder(self) -> None:
        selected = filedialog.askdirectory(title="Выберите папку с локализациями")
        if selected:
            self._start_scan(Path(selected))

    def _choose_layout_file(self) -> None:
        selected = filedialog.askopenfilename(
            title="Выберите файл локализации",
            filetypes=[
                ("HOI4 localisation", "*.yml"),
                ("Все файлы", "*.*"),
            ],
        )
        if selected:
            self._start_layout_scan(Path(selected))

    def _choose_layout_folder(self) -> None:
        selected = filedialog.askdirectory(
            title="Выберите папку с локализациями"
        )
        if selected:
            self._start_layout_scan(Path(selected))

    def _refresh_focus_preview_ui(self) -> None:
        if not self.layout_focus_preview_cli_path:
            self.layout_tab.set_preview_cli_status(
                "не выбран — точная проверка заблокирована"
            )
            return
        path = Path(self.layout_focus_preview_cli_path)
        try:
            resolved = validate_focus_preview_installation(path)
        except FocusPreviewError as error:
            self.layout_tab.set_preview_cli_status(str(error))
            return
        self.layout_tab.set_preview_cli_status(str(resolved))

    def _select_focus_preview_cli(self) -> Path | None:
        current = (
            Path(self.layout_focus_preview_cli_path)
            if self.layout_focus_preview_cli_path
            else None
        )
        options: dict[str, object] = {
            "parent": self.root,
            "title": "Укажите EaWFocusTextPreviewCLI.exe",
            "filetypes": [
                (
                    "EaW Focus Text Preview CLI",
                    "EaWFocusTextPreviewCLI.exe",
                ),
                ("Исполняемые файлы", "*.exe"),
                ("Все файлы", "*.*"),
            ],
        }
        if current is not None and current.parent.is_dir():
            options["initialdir"] = str(current.parent)
        selected = filedialog.askopenfilename(**options)
        if not selected:
            return None
        try:
            executable = validate_focus_preview_installation(
                Path(selected)
            )
        except FocusPreviewError as error:
            messagebox.showerror(
                "Неполная установка EaW Focus Text Preview",
                str(error),
            )
            return None

        previous = self.layout_focus_preview_cli_path
        self.layout_focus_preview_cli_path = str(executable)
        try:
            self._save_current_settings()
        except SettingsError as error:
            self.layout_focus_preview_cli_path = previous
            messagebox.showerror(
                "Путь к EaW Focus Text Preview не сохранён",
                str(error),
            )
            self._refresh_focus_preview_ui()
            return None
        self._refresh_focus_preview_ui()
        self.layout_tab.set_status(
            f"Точный проверяющий модуль выбран: {executable}"
        )
        return executable

    def _require_focus_preview_cli(self) -> Path | None:
        if self.layout_focus_preview_cli_path:
            try:
                return validate_focus_preview_installation(
                    Path(self.layout_focus_preview_cli_path)
                )
            except FocusPreviewError as error:
                messagebox.showwarning(
                    "EaW Focus Text Preview недоступен",
                    str(error),
                )
        else:
            messagebox.showwarning(
                "Нужно указать точный проверяющий модуль",
                (
                    "Для точной проверки выберите "
                    "EaWFocusTextPreviewCLI.exe. Рядом с ним должна "
                    "находиться папка _internal."
                ),
            )
        return self._select_focus_preview_cli()

    def _refresh_compare_paths_ui(self) -> None:
        if hasattr(self, "compare_tab"):
            self.compare_tab.set_paths(
                self.compare_english_path,
                self.compare_russian_path,
            )

    def _select_compare_folder(self, language: str) -> Path | None:
        if language not in {"english", "russian"}:
            raise ValueError("Неизвестная сторона сравнения.")
        attribute = (
            "compare_english_path"
            if language == "english"
            else "compare_russian_path"
        )
        current_value = getattr(self, attribute)
        current = Path(current_value) if current_value else None
        options: dict[str, object] = {
            "parent": self.root,
            "title": (
                "Выберите папку английской локализации"
                if language == "english"
                else "Выберите папку русской локализации"
            ),
            "mustexist": True,
        }
        if current is not None and current.is_dir():
            options["initialdir"] = str(current)
        selected = filedialog.askdirectory(**options)
        if not selected:
            return None
        path = Path(selected).resolve()
        previous = current_value
        setattr(self, attribute, str(path))
        try:
            self._save_current_settings()
        except SettingsError as error:
            setattr(self, attribute, previous)
            self._refresh_compare_paths_ui()
            messagebox.showerror(
                "Папка сравнения не сохранена",
                str(error),
            )
            return None
        self._refresh_compare_paths_ui()
        self.compare_tab.status_var.set(
            "Папка для сравнения выбрана: "
            f"{path}"
        )
        return path

    def _require_compare_folders(
        self,
    ) -> tuple[Path, Path] | None:
        english = (
            Path(self.compare_english_path)
            if self.compare_english_path
            else None
        )
        if english is None or not english.is_dir():
            messagebox.showwarning(
                "Нужна английская папка",
                "Укажите папку с английской локализацией.",
            )
            english = self._select_compare_folder("english")
            if english is None:
                return None

        russian = (
            Path(self.compare_russian_path)
            if self.compare_russian_path
            else None
        )
        if russian is None or not russian.is_dir():
            messagebox.showwarning(
                "Нужна русская папка",
                "Укажите папку с русской локализацией.",
            )
            russian = self._select_compare_folder("russian")
            if russian is None:
                return None
        return english.resolve(), russian.resolve()

    def _capture_layout_settings(self) -> TextLayoutOptions:
        options = self.layout_tab.capture_options(
            self.layout_focus_preview_cli_path
        )
        self.layout_focus_enabled = options.focus_enabled
        self.layout_focus_mode = options.focus_mode
        self.layout_focus_limit = options.focus_limit
        self.layout_focus_preview_priority = options.focus_preview_priority
        self.layout_events_enabled = options.events_enabled
        self.layout_event_limit = options.event_limit
        self.layout_welcome_enabled = options.welcome_enabled
        self.layout_welcome_limit = options.welcome_limit
        return options

    def _restore_layout_variables(self) -> None:
        self.layout_tab.restore_options(
            TextLayoutOptions(
                focus_enabled=self.layout_focus_enabled,
                focus_mode=self.layout_focus_mode,
                focus_limit=self.layout_focus_limit,
                focus_preview_cli_path=(
                    Path(self.layout_focus_preview_cli_path)
                    if self.layout_focus_preview_cli_path
                    else None
                ),
                focus_preview_priority=self.layout_focus_preview_priority,
                events_enabled=self.layout_events_enabled,
                event_limit=self.layout_event_limit,
                welcome_enabled=self.layout_welcome_enabled,
                welcome_limit=self.layout_welcome_limit,
            )
        )

    def _layout_controls_changed(
        self,
        _event: object | None = None,
    ) -> str:
        previous = (
            self.layout_focus_enabled,
            self.layout_focus_mode,
            self.layout_focus_limit,
            self.layout_focus_preview_cli_path,
            self.layout_focus_preview_priority,
            self.layout_events_enabled,
            self.layout_event_limit,
            self.layout_welcome_enabled,
            self.layout_welcome_limit,
        )
        try:
            self._capture_layout_settings()
            self._save_current_settings()
        except (ValueError, SettingsError) as error:
            (
                self.layout_focus_enabled,
                self.layout_focus_mode,
                self.layout_focus_limit,
                self.layout_focus_preview_cli_path,
                self.layout_focus_preview_priority,
                self.layout_events_enabled,
                self.layout_event_limit,
                self.layout_welcome_enabled,
                self.layout_welcome_limit,
            ) = previous
            self._restore_layout_variables()
            self._refresh_focus_preview_ui()
            self._refresh_layout_controls()
            messagebox.showerror("Настройки не сохранены", str(error))
            return "break"

        self._refresh_layout_controls()
        self._refresh_focus_preview_ui()
        self.layout_tab.set_status(
            "Настройки проверки текстов сохранены."
        )
        return "break"

    def _refresh_layout_controls(self) -> None:
        if hasattr(self, "layout_tab"):
            self.layout_tab.set_busy(self.busy)

    def _refresh_compare_controls(self) -> None:
        if hasattr(self, "compare_tab"):
            self.compare_tab.set_busy(self.busy)

    def _refresh_context_mod_ui(self) -> None:
        if not self.context_mod_path:
            self.context_mod_var.set("не указана — контекстный режим заблокирован")
            if hasattr(self, "layout_tab"):
                self.layout_tab.set_context_status(
                    "не указана — проверка текстов заблокирована"
                )
            return
        path = Path(self.context_mod_path)
        if not path.is_dir() or not is_context_root(path):
            message = f"путь недоступен или не является папкой мода: {path}"
            self.context_mod_var.set(message)
            if hasattr(self, "layout_tab"):
                self.layout_tab.set_context_status(message)
            return
        message = f"{mod_display_name(path)} — {path}"
        self.context_mod_var.set(message)
        if hasattr(self, "layout_tab"):
            self.layout_tab.set_context_status(message)

    def _select_context_mod(
        self,
        initial_dir: Path | None = None,
    ) -> Path | None:
        current = Path(self.context_mod_path) if self.context_mod_path else None
        starting_directory = initial_dir
        if starting_directory is None and current is not None and current.is_dir():
            starting_directory = current

        options: dict[str, object] = {
            "parent": self.root,
            "title": "Выберите корневую папку мода",
            "mustexist": True,
        }
        if starting_directory is not None and starting_directory.is_dir():
            options["initialdir"] = str(starting_directory)
        selected = filedialog.askdirectory(**options)
        if not selected:
            return None

        path = Path(selected).resolve()
        if not is_context_root(path):
            messagebox.showerror(
                "Это не корневая папка мода",
                (
                    "В выбранной папке не найден descriptor.mod или структура "
                    "interface/localisation.\n\n"
                    f"Выбрано: {path}"
                ),
            )
            return None

        previous = self.context_mod_path
        self.context_mod_path = str(path)
        try:
            self._save_current_settings()
        except SettingsError as error:
            self.context_mod_path = previous
            self._refresh_context_mod_ui()
            messagebox.showerror(
                "Папка мода не сохранена",
                str(error),
            )
            return None

        self._refresh_context_mod_ui()
        self.current_file_var.set(
            f"Контекстный мод: {mod_display_name(path)} — {path}"
        )
        if hasattr(self, "layout_tab"):
            self.layout_tab.set_status(
                f"Мод для определения типов: {mod_display_name(path)} — {path}"
            )
        return path

    def _require_context_mod(
        self,
        target: Path,
        purpose: str = "Контекстный жёсткий режим",
    ) -> Path | None:
        while True:
            configured = (
                Path(self.context_mod_path)
                if self.context_mod_path
                else None
            )
            if (
                configured is None
                or not configured.is_dir()
                or not is_context_root(configured)
            ):
                messagebox.showwarning(
                    "Нужно указать папку мода",
                    (
                        f"{purpose} нельзя запустить без корневой папки мода."
                    ),
                )
                configured = self._select_context_mod()
                if configured is None:
                    return None

            configured = configured.resolve()
            detected = find_mod_root(target)
            if (
                detected is not None
                and str(detected).casefold() != str(configured).casefold()
            ):
                messagebox.showerror(
                    "Выбрана другая версия мода",
                    (
                        "Проверяемый файл находится в другой папке мода.\n\n"
                        f"Указанный контекст:\n{configured}\n\n"
                        f"Папка проверяемого файла:\n{detected}\n\n"
                        "Выберите правильную версию мода."
                    ),
                )
                selected = self._select_context_mod(initial_dir=detected)
                if selected is None:
                    return None
                continue
            return configured

    def _resolve_hoi4_install(self) -> Path | None:
        game_root = find_hoi4_install(self.hoi4_install_path)
        if game_root is None:
            return None
        if str(game_root) == self.hoi4_install_path:
            return game_root

        previous = self.hoi4_install_path
        self.hoi4_install_path = str(game_root)
        try:
            self._save_current_settings()
        except SettingsError as error:
            self.hoi4_install_path = previous
            messagebox.showwarning(
                "Путь к Hearts of Iron IV не сохранён",
                str(error),
            )
        return game_root

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        state = tk.DISABLED if busy else tk.NORMAL
        self.file_button.configure(state=state)
        self.folder_button.configure(state=state)
        self.clear_button.configure(state=state)
        self.exceptions_button.configure(state=state)
        mode_state = (
            tk.DISABLED
            if busy or self.font_profile is None
            else tk.NORMAL
        )
        self.soft_mode_button.configure(state=mode_state)
        self.strict_mode_button.configure(state=mode_state)
        self.contextual_mode_button.configure(state=mode_state)
        self.context_mod_button.configure(state=state)
        self.show_unknown_context_button.configure(state=state)
        self.russian_straight_quotes_button.configure(state=state)
        self._refresh_layout_controls()
        self._refresh_compare_controls()
        self._refresh_export_controls()

    def _refresh_export_controls(self) -> None:
        controls = (
            (self.export_button, self.table),
        )
        for button, table in controls:
            has_rows = bool(table.get_children(""))
            button.configure(
                state=(
                    tk.NORMAL
                    if not self.busy and has_rows
                    else tk.DISABLED
                )
            )
        if hasattr(self, "compare_tab"):
            self.compare_tab.refresh_export_control()
        if hasattr(self, "layout_tab"):
            self.layout_tab.refresh_export_control()

    def _clear_results(self) -> None:
        for item in self.table.get_children():
            self.table.delete(item)
        self.diagnostics_by_item.clear()
        self.summary_var.set("Результаты очищены.")
        self.current_file_var.set(self.font_status)
        self.detail_var.set("")
        self.progress.configure(value=0, maximum=1)
        self.copy_key_button.configure(state=tk.DISABLED)
        self.copy_character_button.configure(state=tk.DISABLED)
        self._refresh_export_controls()

    def _start_localisation_comparison(self) -> None:
        if self.tasks.is_running:
            return

        folders = self._require_compare_folders()
        if folders is None:
            self.compare_tab.status_var.set(
                "Сравнение отменено: обе папки обязательны."
            )
            return
        english_root, russian_root = folders

        self.compare_tab.prepare_comparison(english_root, russian_root)

        def work(reporter: TaskReporter) -> LocalisationComparisonResult:
            return self.localisation_comparator.scan(
                english_root,
                russian_root,
                progress=reporter.progress,
            )

        if self.tasks.start("comparison", work):
            self._set_busy(True)

    def _start_scan(self, target: Path) -> None:
        if self.tasks.is_running:
            return

        glyph_mode = cast(GlyphMode, self.glyph_mode_var.get())
        context_mod_root: Path | None = None
        context_game_root: Path | None = None
        if glyph_mode == "contextual":
            context_mod_root = self._require_context_mod(target)
            if context_mod_root is None:
                self.current_file_var.set(
                    "Контекстная проверка отменена: папка мода не указана."
                )
                return
            context_game_root = self._resolve_hoi4_install()

        self._clear_results()
        excluded_characters = frozenset(self.excluded_characters)
        show_unknown_context_warnings = (
            self.show_unknown_context_warnings
        )
        check_russian_straight_quotes = (
            self.check_russian_straight_quotes
        )
        self.summary_var.set(f"Проверяется: {target}")
        if glyph_mode == "contextual":
            game_note = (
                f"; HOI4: {context_game_root}"
                if context_game_root is not None
                else "; стандартный интерфейс HOI4 не найден"
            )
            self.current_file_var.set(
                f"Контекст: {context_mod_root}{game_note}"
            )
        else:
            self.current_file_var.set("Подготовка проверки…")

        def work(reporter: TaskReporter) -> tuple[ScanResult, GlyphMode]:
            result = self.checker.scan(
                target,
                progress=reporter.progress,
                glyph_mode=glyph_mode,
                excluded_characters=excluded_characters,
                context_mod_root=context_mod_root,
                context_game_root=context_game_root,
                show_unknown_context_warnings=(
                    show_unknown_context_warnings
                ),
                check_russian_straight_quotes=(
                    check_russian_straight_quotes
                ),
            )
            return result, glyph_mode

        if self.tasks.start("localisation", work):
            self._set_busy(True)

    def _start_layout_scan(self, target: Path) -> None:
        if self.tasks.is_running:
            return

        previous = (
            self.layout_focus_enabled,
            self.layout_focus_mode,
            self.layout_focus_limit,
            self.layout_focus_preview_cli_path,
            self.layout_focus_preview_priority,
            self.layout_events_enabled,
            self.layout_event_limit,
            self.layout_welcome_enabled,
            self.layout_welcome_limit,
        )
        try:
            options = self._capture_layout_settings()
            if options.focus_enabled and options.focus_mode == "exact":
                preview_cli = self._require_focus_preview_cli()
                if preview_cli is None:
                    self.layout_tab.set_status(
                        "Точная проверка отменена: CLI не указан."
                    )
                    return
                self.layout_focus_preview_cli_path = str(preview_cli)
                options = replace(
                    options,
                    focus_preview_cli_path=preview_cli,
                )
            options.validate()
            self._save_current_settings()
        except (ValueError, SettingsError) as error:
            (
                self.layout_focus_enabled,
                self.layout_focus_mode,
                self.layout_focus_limit,
                self.layout_focus_preview_cli_path,
                self.layout_focus_preview_priority,
                self.layout_events_enabled,
                self.layout_event_limit,
                self.layout_welcome_enabled,
                self.layout_welcome_limit,
            ) = previous
            self._restore_layout_variables()
            self._refresh_focus_preview_ui()
            self._refresh_layout_controls()
            messagebox.showerror(
                "Проверка не запущена",
                str(error),
            )
            return

        context_mod_root = self._require_context_mod(
            target,
            purpose="Проверку текстов",
        )
        if context_mod_root is None:
            self.layout_tab.set_status(
                "Проверка отменена: папка мода не указана."
            )
            return
        context_game_root = self._resolve_hoi4_install()

        game_note = (
            f"; HOI4: {context_game_root}"
            if context_game_root is not None
            else "; стандартная HOI4 не найдена"
        )
        self.layout_tab.prepare_scan(
            target,
            f"Контекст: {context_mod_root}{game_note}",
        )

        def work(reporter: TaskReporter) -> TextLayoutResult:
            return self.text_layout_checker.scan(
                target=target,
                mod_root=context_mod_root,
                options=options,
                game_root=context_game_root,
                progress=reporter.progress,
                preview_started=lambda total: reporter.notify(
                    "preview_started",
                    total,
                ),
            )

        if self.tasks.start("layout", work):
            self._set_busy(True)

    def _poll_events(self) -> None:
        try:
            for event in self.tasks.drain():
                self._handle_background_event(event)
        finally:
            self.root.after(100, self._poll_events)

    def _handle_background_event(
        self,
        event: TaskProgress | TaskNotice | TaskSucceeded | TaskFailed,
    ) -> None:
        if isinstance(event, TaskProgress):
            self._handle_task_progress(event)
        elif isinstance(event, TaskSucceeded):
            self._handle_task_success(event)
        elif isinstance(event, TaskFailed):
            self._handle_task_failure(event)
        else:
            self._handle_task_notice(event)

    def _handle_task_progress(self, event: TaskProgress) -> None:
        if event.task == "localisation":
            self.progress.configure(
                maximum=event.total,
                value=event.current,
            )
            self.current_file_var.set(str(event.path))
        elif event.task == "layout":
            self.layout_tab.update_progress(
                event.current,
                event.total,
                event.path,
            )
        elif event.task == "comparison":
            self.compare_tab.update_progress(
                event.current,
                event.total,
                event.path,
            )

    def _handle_task_success(self, event: TaskSucceeded) -> None:
        if event.task == "localisation":
            result, glyph_mode = cast(
                tuple[ScanResult, GlyphMode],
                event.result,
            )
            self._show_result(result, glyph_mode)
        elif event.task == "layout":
            result = cast(TextLayoutResult, event.result)
            self.layout_tab.show_result(result)
            self._show_layout_preview_errors(result)
        elif event.task == "comparison":
            self.compare_tab.show_result(
                cast(LocalisationComparisonResult, event.result)
            )
        self._set_busy(False)

    def _handle_task_failure(self, event: TaskFailed) -> None:
        self._set_busy(False)
        if event.task == "localisation":
            self.summary_var.set(
                "Проверка завершилась внутренней ошибкой."
            )
            title = "Ошибка"
        elif event.task == "layout":
            self.layout_tab.show_failure()
            title = "Ошибка"
        else:
            self.compare_tab.show_failure()
            title = "Ошибка сравнения локализаций"
        messagebox.showerror(title, str(event.error))

    def _handle_task_notice(self, event: TaskNotice) -> None:
        if event.source == "layout" and event.kind == "preview_started":
            self.layout_tab.show_preview_started(cast(int, event.payload))
        elif event.source == "compare_editor" and event.kind == "opened":
            self._show_compare_editor_result(
                cast(
                    list[
                        tuple[
                            ComparisonLanguage,
                            Diagnostic,
                            OpenResult,
                        ]
                    ],
                    event.payload,
                )
            )
        elif event.source == "compare_editor" and event.kind == "failure":
            error, opened = cast(
                tuple[
                    Exception,
                    list[
                        tuple[
                            ComparisonLanguage,
                            Diagnostic,
                            OpenResult,
                        ]
                    ],
                ],
                event.payload,
            )
            self._show_compare_editor_failure(error, opened)
        elif event.source == "editor" and event.kind == "opened":
            diagnostic, result, status_var = cast(
                tuple[Diagnostic, OpenResult, tk.StringVar],
                event.payload,
            )
            self._show_editor_result(
                diagnostic,
                result,
                status_var,
            )
        elif event.source == "editor" and event.kind == "failure":
            messagebox.showerror(
                "Не удалось открыть Notepad++",
                str(event.payload),
            )

    def _show_result(
        self,
        result: ScanResult,
        glyph_mode: GlyphMode,
    ) -> None:
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
        self._refresh_export_controls()

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

    @staticmethod
    def _show_layout_preview_errors(result: TextLayoutResult) -> None:
        if not result.preview_error_messages:
            return
        shown = "\n".join(result.preview_error_messages[:5])
        remaining = len(result.preview_error_messages) - 5
        if remaining > 0:
            shown += f"\n…и ещё ошибок: {remaining}"
        messagebox.showwarning(
            "Часть фокусов не проверена точным модулем",
            shown,
        )

    def _open_compare_selected_languages(
        self,
        languages: tuple[ComparisonLanguage, ...],
    ) -> str:
        issue = self.compare_tab.selected_issue()
        diagnostics: list[tuple[ComparisonLanguage, Diagnostic]] = []
        if issue is not None:
            for language in languages:
                diagnostic = issue.diagnostic_for(language)
                if (
                    diagnostic is not None
                    and diagnostic.path.is_file()
                ):
                    diagnostics.append((language, diagnostic))
        if not diagnostics:
            self.root.bell()
            return "break"

        executable = self._resolve_notepad_plus_plus()
        if executable is None:
            self.compare_tab.status_var.set(
                "Открытие в Notepad++ отменено."
            )
            return "break"

        labels = {
            "english": "английский",
            "russian": "русский",
        }
        requested = " и ".join(
            labels[language]
            for language, _ in diagnostics
        )
        self.compare_tab.status_var.set(
            f"Открывается {requested} файл в Notepad++…"
        )
        fullscreen = self.notepad_plus_plus_fullscreen

        def work() -> None:
            opened: list[
                tuple[ComparisonLanguage, Diagnostic, OpenResult]
            ] = []
            try:
                for language, diagnostic in diagnostics:
                    result = open_location(
                        executable=executable,
                        file_path=diagnostic.path,
                        line=diagnostic.line,
                        column=diagnostic.column,
                        selection_length=0,
                        fullscreen=fullscreen,
                    )
                    opened.append((language, diagnostic, result))
            except NotepadPlusPlusError as error:
                self.tasks.post_notice(
                    "compare_editor",
                    "failure",
                    (error, opened),
                )
                return
            self.tasks.post_notice(
                "compare_editor",
                "opened",
                opened,
            )

        threading.Thread(target=work, daemon=True).start()
        return "break"

    def _show_selected_detail(self, _event: object) -> None:
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
                and diagnostic.code in _GLYPH_DIAGNOSTIC_CODES
                and diagnostic.character
                else tk.DISABLED
            )
        )
        self.detail_var.set(
            f"{values[2]}:{values[3]}:{values[4]} — {values[6]}"
        )

    def _selected_diagnostic(self) -> Diagnostic | None:
        selected = self.table.selection()
        if not selected:
            return None
        return self.diagnostics_by_item.get(selected[0])

    def _selected_key(self) -> str:
        diagnostic = self._selected_diagnostic()
        return diagnostic.key if diagnostic is not None else ""

    def _selected_character(self) -> str:
        diagnostic = self._selected_diagnostic()
        if (
            diagnostic is None
            or diagnostic.code not in _GLYPH_DIAGNOSTIC_CODES
        ):
            return ""
        return diagnostic.character

    def _save_current_settings(self) -> None:
        save_settings(
            self.settings_path,
            AppSettings(
                excluded_characters=frozenset(self.excluded_characters),
                notepad_plus_plus_path=self.notepad_plus_plus_path,
                notepad_plus_plus_fullscreen=self.notepad_plus_plus_fullscreen,
                context_mod_path=self.context_mod_path,
                hoi4_install_path=self.hoi4_install_path,
                show_unknown_context_warnings=(
                    self.show_unknown_context_warnings
                ),
                check_russian_straight_quotes=(
                    self.check_russian_straight_quotes
                ),
                layout_focus_enabled=self.layout_focus_enabled,
                layout_focus_mode=self.layout_focus_mode,
                layout_focus_limit=self.layout_focus_limit,
                layout_focus_preview_cli_path=(
                    self.layout_focus_preview_cli_path
                ),
                layout_focus_preview_priority=(
                    self.layout_focus_preview_priority
                ),
                layout_events_enabled=self.layout_events_enabled,
                layout_event_limit=self.layout_event_limit,
                layout_welcome_enabled=self.layout_welcome_enabled,
                layout_welcome_limit=self.layout_welcome_limit,
                compare_english_path=self.compare_english_path,
                compare_russian_path=self.compare_russian_path,
                export_directory=self.export_directory,
            ),
        )

    def _export_table_results(
        self,
        table: ttk.Treeview,
        filename_prefix: str,
        status_var: tk.StringVar,
    ) -> None:
        items = table.get_children("")
        if not items:
            self.root.bell()
            return

        initial_directory = Path(self.export_directory)
        if not initial_directory.is_dir():
            initial_directory = self.app_root
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        selected = filedialog.asksaveasfilename(
            parent=self.root,
            title="Выгрузить результаты в CSV",
            initialdir=str(initial_directory),
            initialfile=f"{filename_prefix}_{timestamp}.csv",
            defaultextension=".csv",
            filetypes=(("CSV-файлы", "*.csv"), ("Все файлы", "*.*")),
        )
        if not selected:
            return

        path = Path(selected)
        columns = tuple(str(column) for column in table["columns"])
        headers = tuple(
            str(table.heading(column, "text")).replace(" ↕", "")
            for column in columns
        )
        rows = (
            tuple(table.item(item, "values"))
            for item in items
        )
        try:
            row_count = export_csv(path, headers, rows)
        except (OSError, UnicodeError) as error:
            messagebox.showerror(
                "Не удалось выгрузить результаты",
                f"Файл не сохранён:\n{path}\n\n{error}",
            )
            return

        previous_directory = self.export_directory
        self.export_directory = str(path.parent)
        try:
            self._save_current_settings()
        except SettingsError as error:
            self.export_directory = previous_directory
            messagebox.showwarning(
                "Папка выгрузки не запомнена",
                f"CSV сохранён, но настройку сохранить не удалось:\n{error}",
            )
        status_var.set(
            f"Выгружено строк: {row_count}; файл: {path}"
        )

    def _unknown_context_visibility_changed(self) -> None:
        previous = self.show_unknown_context_warnings
        self.show_unknown_context_warnings = (
            self.show_unknown_context_var.get()
        )
        try:
            self._save_current_settings()
        except SettingsError as error:
            self.show_unknown_context_warnings = previous
            self.show_unknown_context_var.set(previous)
            messagebox.showerror(
                "Настройка контекстных предупреждений не сохранена",
                str(error),
            )
            return
        state = (
            "будут показаны отдельным предупреждением"
            if self.show_unknown_context_warnings
            else "будут скрыты"
        )
        self.current_file_var.set(
            f"Ключи с неопределённым контекстом {state}."
        )

    def _russian_straight_quotes_changed(self) -> None:
        previous = self.check_russian_straight_quotes
        self.check_russian_straight_quotes = (
            self.russian_straight_quotes_var.get()
        )
        try:
            self._save_current_settings()
        except SettingsError as error:
            self.check_russian_straight_quotes = previous
            self.russian_straight_quotes_var.set(previous)
            messagebox.showerror(
                "Настройка проверки кавычек не сохранена",
                str(error),
            )
            return
        state = (
            "включена"
            if self.check_russian_straight_quotes
            else "выключена"
        )
        self.current_file_var.set(
            f"Проверка прямых кавычек в русской локализации {state}."
        )

    def _notepad_window_mode_changed(self) -> None:
        previous = self.notepad_plus_plus_fullscreen
        self.notepad_plus_plus_fullscreen = self.notepad_fullscreen_var.get()
        try:
            self._save_current_settings()
        except SettingsError as error:
            self.notepad_plus_plus_fullscreen = previous
            self.notepad_fullscreen_var.set(previous)
            messagebox.showerror(
                "Режим окна Notepad++ не сохранён",
                str(error),
            )
            return
        mode = (
            "в полноэкранном режиме"
            if self.notepad_plus_plus_fullscreen
            else "в обычном окне"
        )
        self.current_file_var.set(f"Notepad++ будет открываться {mode}.")

    def _remember_notepad_plus_plus(self, executable: Path) -> None:
        previous = self.notepad_plus_plus_path
        self.notepad_plus_plus_path = str(executable)
        try:
            self._save_current_settings()
        except SettingsError as error:
            self.notepad_plus_plus_path = previous
            messagebox.showwarning(
                "Путь к Notepad++ не сохранён",
                str(error),
            )

    def _resolve_notepad_plus_plus(self) -> Path | None:
        executable = find_notepad_plus_plus(self.notepad_plus_plus_path)
        if executable is not None:
            if str(executable) != self.notepad_plus_plus_path:
                self._remember_notepad_plus_plus(executable)
            return executable

        selected = filedialog.askopenfilename(
            parent=self.root,
            title="Укажите notepad++.exe",
            filetypes=[
                ("Notepad++", "notepad++.exe"),
                ("Исполняемые файлы", "*.exe"),
                ("Все файлы", "*.*"),
            ],
        )
        if not selected:
            return None

        executable = Path(selected)
        if not executable.is_file():
            messagebox.showerror(
                "Notepad++ не найден",
                f"Указанный файл не существует:\n{executable}",
            )
            return None
        self._remember_notepad_plus_plus(executable.resolve())
        return executable.resolve()

    def _open_double_clicked_diagnostic(self, event: tk.Event) -> str:
        item = self.table.identify_row(event.y)
        if not item:
            return "break"
        self.table.selection_set(item)
        self.table.focus(item)
        return self._open_selected_diagnostic()

    def _open_selected_diagnostic(
        self,
        _event: object | None = None,
    ) -> str:
        diagnostic = self._selected_diagnostic()
        return self._open_diagnostic(
            diagnostic,
            self.current_file_var,
        )

    def _open_diagnostic(
        self,
        diagnostic: Diagnostic | None,
        status_var: tk.StringVar,
    ) -> str:
        if diagnostic is None:
            self.root.bell()
            return "break"
        if not diagnostic.path.is_file():
            messagebox.showerror(
                "Файл не найден",
                f"Нельзя открыть файл диагностики:\n{diagnostic.path}",
            )
            return "break"

        executable = self._resolve_notepad_plus_plus()
        if executable is None:
            status_var.set("Открытие в Notepad++ отменено.")
            return "break"

        selection_length = diagnostic.selection_length
        if (
            selection_length <= 0
            and diagnostic.code in _GLYPH_DIAGNOSTIC_CODES
            and diagnostic.character
        ):
            selection_length = 1
        fullscreen = self.notepad_plus_plus_fullscreen
        status_var.set(
            f"Открывается в Notepad++: "
            f"{diagnostic.path}:{diagnostic.line}:{diagnostic.column}"
        )

        def work() -> None:
            try:
                result = open_location(
                    executable=executable,
                    file_path=diagnostic.path,
                    line=diagnostic.line,
                    column=diagnostic.column,
                    selection_length=selection_length,
                    fullscreen=fullscreen,
                )
            except NotepadPlusPlusError as error:
                self.tasks.post_notice("editor", "failure", error)
                return
            self.tasks.post_notice(
                "editor",
                "opened",
                (diagnostic, result, status_var),
            )

        threading.Thread(target=work, daemon=True).start()
        return "break"

    def _show_compare_editor_result(
        self,
        opened: list[
            tuple[ComparisonLanguage, Diagnostic, OpenResult]
        ],
    ) -> None:
        labels = {
            "english": "английский",
            "russian": "русский",
        }
        if not opened:
            self.compare_tab.status_var.set(
                "Notepad++ не открыл ни одного файла."
            )
            return
        opened_labels = " и ".join(
            labels[language]
            for language, _, _ in opened
        )
        if len(opened) == 1:
            _, diagnostic, result = opened[0]
            location = (
                f"{diagnostic.path}:"
                f"{diagnostic.line}:{diagnostic.column}"
            )
            if result.exact_position_set:
                self.compare_tab.status_var.set(
                    f"Открыт {opened_labels} файл в Notepad++ "
                    f"на позиции: {location}"
                )
            else:
                self.compare_tab.status_var.set(
                    f"Открыт {opened_labels} файл в Notepad++: "
                    f"{location}. Точная позиция не подтверждена."
                )
            return
        active_language, active_diagnostic, _ = opened[-1]
        self.compare_tab.status_var.set(
            f"Открыты {opened_labels} файлы в Notepad++; "
            f"активен {labels[active_language]}: "
            f"{active_diagnostic.path}:"
            f"{active_diagnostic.line}:{active_diagnostic.column}"
        )

    def _show_compare_editor_failure(
        self,
        error: Exception,
        opened: list[
            tuple[ComparisonLanguage, Diagnostic, OpenResult]
        ],
    ) -> None:
        if opened:
            self.compare_tab.status_var.set(
                f"Открыто файлов: {len(opened)}; следующий файл "
                "открыть не удалось."
            )
        else:
            self.compare_tab.status_var.set(
                "Файлы в Notepad++ открыть не удалось."
            )
        messagebox.showerror(
            "Не удалось открыть файл сравнения в Notepad++",
            str(error),
        )

    def _show_editor_result(
        self,
        diagnostic: Diagnostic,
        result: OpenResult,
        status_var: tk.StringVar,
    ) -> None:
        location = (
            f"{diagnostic.path}:{diagnostic.line}:{diagnostic.column}"
        )
        if result.character_selected:
            status_var.set(
                f"Открыто в Notepad++; фрагмент выделен: {location}"
            )
        elif result.exact_position_set:
            status_var.set(
                f"Открыто в Notepad++ на позиции: {location}"
            )
        else:
            status_var.set(
                f"Файл открыт в Notepad++ через строку и столбец: {location}. "
                "Точное позиционирование через редактор не подтверждено."
            )

    def _copy_selected_key(self, _event: object | None = None) -> str:
        key = self._selected_key()
        if not key:
            self.root.bell()
            return "break"
        self.root.clipboard_clear()
        self.root.clipboard_append(key)
        self.root.update_idletasks()
        self.current_file_var.set(f"Ключ скопирован: {key}")
        return "break"

    def _copy_selected_character(self, _event: object | None = None) -> str:
        character = self._selected_character()
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

    @staticmethod
    def _exception_label(character: str) -> str:
        if character == " ":
            display = "обычный пробел"
        elif character == "\u00a0":
            display = "неразрывный пробел"
        elif character == "\u200b":
            display = "пробел нулевой ширины"
        elif character.isprintable():
            display = f"«{character}»"
        else:
            display = "непечатный символ"
        unicode_name = unicodedata.name(character, "UNNAMED CHARACTER")
        return f"{display} — U+{ord(character):04X} — {unicode_name}"

    def _refresh_exceptions_ui(self) -> None:
        count = len(self.excluded_characters)
        self.exceptions_button.configure(
            text=f"Исключения… ({count})"
        )
        listbox = self.exceptions_listbox
        if listbox is None or not listbox.winfo_exists():
            return

        self.exception_list_characters = sorted(
            self.excluded_characters,
            key=ord,
        )
        listbox.delete(0, tk.END)
        for character in self.exception_list_characters:
            listbox.insert(tk.END, self._exception_label(character))

    def _save_exceptions(self, previous: set[str]) -> bool:
        try:
            self._save_current_settings()
        except SettingsError as error:
            self.excluded_characters = previous
            self._refresh_exceptions_ui()
            messagebox.showerror("Исключения не сохранены", str(error))
            return False
        self._refresh_exceptions_ui()
        return True

    def _add_excluded_text(self, text: str) -> bool:
        characters = set(text)
        new_characters = characters - self.excluded_characters
        if not new_characters:
            self.root.bell()
            return False

        previous = self.excluded_characters.copy()
        self.excluded_characters.update(new_characters)
        if not self._save_exceptions(previous):
            return False

        codes = ", ".join(
            f"U+{ord(character):04X}"
            for character in sorted(new_characters, key=ord)
        )
        self.current_file_var.set(
            f"Добавлено в исключения: {codes}. "
            "Будет применено при следующей проверке."
        )
        return True

    def _remove_selected_exceptions(self) -> None:
        listbox = self.exceptions_listbox
        if listbox is None or not listbox.winfo_exists():
            return
        selected_indices = listbox.curselection()
        if not selected_indices:
            self.root.bell()
            return

        removed = {
            self.exception_list_characters[index]
            for index in selected_indices
        }
        previous = self.excluded_characters.copy()
        self.excluded_characters.difference_update(removed)
        if not self._save_exceptions(previous):
            return

        codes = ", ".join(
            f"U+{ord(character):04X}"
            for character in sorted(removed, key=ord)
        )
        self.current_file_var.set(
            f"Удалено из исключений: {codes}. "
            "Будет применено при следующей проверке."
        )

    def _close_exceptions_dialog(self) -> None:
        dialog = self.exceptions_dialog
        self.exceptions_dialog = None
        self.exceptions_listbox = None
        self.exception_list_characters = []
        if dialog is not None and dialog.winfo_exists():
            dialog.grab_release()
            dialog.destroy()

    def _open_exceptions_dialog(self) -> None:
        dialog = self.exceptions_dialog
        if dialog is not None and dialog.winfo_exists():
            dialog.lift()
            dialog.focus_force()
            return

        dialog = tk.Toplevel(self.root)
        self.exceptions_dialog = dialog
        dialog.title("Исключения UNSAFE_GLYPH")
        dialog.geometry("680x390")
        dialog.minsize(560, 320)
        dialog.transient(self.root)
        dialog.protocol("WM_DELETE_WINDOW", self._close_exceptions_dialog)

        outer = ttk.Frame(dialog, padding=12)
        outer.pack(fill=tk.BOTH, expand=True)
        ttk.Label(
            outer,
            text=(
                "Добавленные символы не считаются небезопасными ни в мягком, "
                "ни в жёстком режиме. Можно вставить сразу несколько символов."
            ),
            justify=tk.LEFT,
            wraplength=640,
        ).pack(fill=tk.X)

        input_frame = ttk.Frame(outer)
        input_frame.pack(fill=tk.X, pady=(10, 8))
        input_var = tk.StringVar()
        entry = ttk.Entry(input_frame, textvariable=input_var)
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

        def add_from_entry(_event: object | None = None) -> str:
            if self._add_excluded_text(input_var.get()):
                input_var.set("")
            return "break"

        ttk.Button(
            input_frame,
            text="Добавить символы",
            command=add_from_entry,
        ).pack(side=tk.LEFT, padx=(8, 0))
        entry.bind("<Return>", add_from_entry)

        list_frame = ttk.Frame(outer)
        list_frame.pack(fill=tk.BOTH, expand=True)
        self.exceptions_listbox = tk.Listbox(
            list_frame,
            selectmode=tk.EXTENDED,
            exportselection=False,
        )
        scrollbar = ttk.Scrollbar(
            list_frame,
            orient=tk.VERTICAL,
            command=self.exceptions_listbox.yview,
        )
        self.exceptions_listbox.configure(yscrollcommand=scrollbar.set)
        self.exceptions_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        buttons = ttk.Frame(outer)
        buttons.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(
            buttons,
            text="Удалить выбранные",
            command=self._remove_selected_exceptions,
        ).pack(side=tk.LEFT)
        ttk.Button(
            buttons,
            text="Закрыть",
            command=self._close_exceptions_dialog,
        ).pack(side=tk.RIGHT)

        self._refresh_exceptions_ui()
        dialog.grab_set()
        entry.focus_set()

    def _add_selected_character_to_exceptions(self) -> None:
        character = self._selected_character()
        if not character or character in self.excluded_characters:
            self.root.bell()
            return
        self._add_excluded_text(character)

    def _show_context_menu(self, event: tk.Event) -> None:
        item = self.table.identify_row(event.y)
        if not item:
            return
        self.table.selection_set(item)
        self.table.focus(item)
        diagnostic = self._selected_diagnostic()
        self.context_menu.entryconfigure(
            "Открыть в Notepad++",
            state=(
                tk.NORMAL
                if diagnostic is not None and diagnostic.path.is_file()
                else tk.DISABLED
            ),
        )
        key = self._selected_key()
        self.context_menu.entryconfigure(
            "Копировать ключ",
            state=tk.NORMAL if key else tk.DISABLED,
        )
        character = self._selected_character()
        self.context_menu.entryconfigure(
            "Копировать символ",
            state=tk.NORMAL if character else tk.DISABLED,
        )
        self.context_menu.entryconfigure(
            "Добавить символ в исключения",
            state=(
                tk.NORMAL
                if character and character not in self.excluded_characters
                else tk.DISABLED
            ),
        )
        self.context_menu.tk_popup(event.x_root, event.y_root)


def run_gui(app_root: Path) -> None:
    root = tk.Tk()
    try:
        ttk.Style(root).theme_use("vista")
    except tk.TclError:
        pass
    CheckerApplication(root=root, app_root=app_root)
    root.mainloop()
