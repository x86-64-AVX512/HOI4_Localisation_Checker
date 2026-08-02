from __future__ import annotations

import queue
import threading
import tkinter as tk
import unicodedata
from dataclasses import replace
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import cast

from .checker import GlyphMode, LocalisationChecker, ScanResult
from .font_context import (
    find_hoi4_install,
    find_mod_root,
    is_context_root,
    mod_display_name,
)
from .font_profile import FontProfile, FontProfileError
from .focus_preview_cli import (
    FocusPreviewError,
    validate_focus_preview_installation,
)
from .localisation_compare import (
    ComparisonIssue,
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
    FocusCheckMode,
    FocusPreviewPriorityMode,
    TextLayoutChecker,
    TextLayoutOptions,
    TextLayoutResult,
)
from .version import DISPLAY_VERSION


_GLYPH_DIAGNOSTIC_CODES = frozenset(
    {"UNSAFE_GLYPH", "UNKNOWN_FONT_CONTEXT"}
)
_PREVIEW_PRIORITY_LABELS = {
    "auto_ru": "Авто; неизвестный язык → RU",
    "auto_en": "Авто; неизвестный язык → EN",
    "ru": "Всегда RU → EN",
    "en": "Всегда EN → RU",
}
_COMPARE_FILTER_LABELS = {
    "Все проблемы": "all",
    "Только отсутствующие ключи": "missing",
    "Нет в русской": "missing_russian",
    "Нет в английской": "missing_english",
    "Только дубли": "duplicates",
    "Только ошибки файлов": "parse_error",
}


class CheckerApplication:
    def __init__(self, root: tk.Tk, app_root: Path) -> None:
        self.root = root
        self.app_root = app_root
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.worker: threading.Thread | None = None
        self.busy = False
        self.diagnostics_by_item: dict[str, Diagnostic] = {}
        self.layout_diagnostics_by_item: dict[str, Diagnostic] = {}
        self.layout_length_sort_descending = True
        self.compare_issues_by_item: dict[str, ComparisonIssue] = {}
        self.compare_all_issues: list[ComparisonIssue] = []
        self.compare_key_sort_descending = False
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
        except SettingsError as error:
            self.excluded_characters: set[str] = set()
            self.notepad_plus_plus_path = ""
            self.notepad_plus_plus_fullscreen = False
            self.context_mod_path = ""
            self.hoi4_install_path = ""
            self.show_unknown_context_warnings = False
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

    def _build_layout_tab(self) -> None:
        outer = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(outer, text="Длина текстов")

        controls = ttk.Frame(outer)
        controls.pack(fill=tk.X)
        self.layout_file_button = ttk.Button(
            controls,
            text="Проверить файл",
            command=self._choose_layout_file,
        )
        self.layout_file_button.pack(side=tk.LEFT)
        self.layout_folder_button = ttk.Button(
            controls,
            text="Проверить папку",
            command=self._choose_layout_folder,
        )
        self.layout_folder_button.pack(side=tk.LEFT, padx=(8, 0))
        self.layout_clear_button = ttk.Button(
            controls,
            text="Очистить результаты",
            command=self._clear_layout_results,
        )
        self.layout_clear_button.pack(side=tk.LEFT, padx=(8, 0))
        self.layout_copy_key_button = ttk.Button(
            controls,
            text="Копировать ключ",
            command=self._copy_layout_selected_key,
            state=tk.DISABLED,
        )
        self.layout_copy_key_button.pack(side=tk.LEFT, padx=(8, 0))
        self.layout_summary_var = tk.StringVar(
            value="Выберите .yml-файл или папку."
        )
        ttk.Label(
            controls,
            textvariable=self.layout_summary_var,
        ).pack(side=tk.LEFT, padx=(18, 0))

        checks = ttk.LabelFrame(
            outer,
            text="Что проверять",
            padding=(10, 8),
        )
        checks.pack(fill=tk.X, pady=(10, 0))
        for column in range(3):
            checks.columnconfigure(column, weight=1)

        focus_frame = ttk.LabelFrame(checks, text="Фокусы", padding=8)
        focus_frame.grid(
            row=0,
            column=0,
            sticky="nsew",
            padx=(0, 6),
        )
        self.layout_focus_enabled_var = tk.BooleanVar(
            value=self.layout_focus_enabled
        )
        self.layout_focus_enabled_button = ttk.Checkbutton(
            focus_frame,
            text="Проверять описания фокусов",
            variable=self.layout_focus_enabled_var,
            command=self._layout_controls_changed,
        )
        self.layout_focus_enabled_button.grid(
            row=0,
            column=0,
            columnspan=4,
            sticky=tk.W,
        )
        self.layout_focus_mode_var = tk.StringVar(
            value=self.layout_focus_mode
        )
        self.layout_focus_length_button = ttk.Radiobutton(
            focus_frame,
            text="Проверять только длину:",
            variable=self.layout_focus_mode_var,
            value="length",
            command=self._layout_controls_changed,
        )
        self.layout_focus_length_button.grid(
            row=1,
            column=0,
            sticky=tk.W,
            pady=(6, 0),
        )
        self.layout_focus_limit_var = tk.StringVar(
            value=str(self.layout_focus_limit)
        )
        self.layout_focus_limit_entry = ttk.Entry(
            focus_frame,
            width=8,
            textvariable=self.layout_focus_limit_var,
        )
        self.layout_focus_limit_entry.grid(
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
        self.layout_focus_newline_button = ttk.Radiobutton(
            focus_frame,
            text=r"Искать наличие \n",
            variable=self.layout_focus_mode_var,
            value="newline",
            command=self._layout_controls_changed,
        )
        self.layout_focus_newline_button.grid(
            row=2,
            column=0,
            columnspan=4,
            sticky=tk.W,
            pady=(6, 0),
        )
        self.layout_focus_exact_button = ttk.Radiobutton(
            focus_frame,
            text="Точная проверка вместимости",
            variable=self.layout_focus_mode_var,
            value="exact",
            command=self._layout_controls_changed,
        )
        self.layout_focus_exact_button.grid(
            row=3,
            column=0,
            columnspan=4,
            sticky=tk.W,
            pady=(6, 0),
        )
        ttk.Label(
            focus_frame,
            text="Предварительный порог:",
        ).grid(
            row=4,
            column=0,
            sticky=tk.W,
            pady=(6, 0),
        )
        self.layout_focus_exact_limit_entry = ttk.Entry(
            focus_frame,
            width=8,
            textvariable=self.layout_focus_limit_var,
        )
        self.layout_focus_exact_limit_entry.grid(
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
        events_frame.grid(
            row=0,
            column=1,
            sticky="nsew",
            padx=6,
        )
        self.layout_events_enabled_var = tk.BooleanVar(
            value=self.layout_events_enabled
        )
        self.layout_events_enabled_button = ttk.Checkbutton(
            events_frame,
            text="Проверять описания ивентов",
            variable=self.layout_events_enabled_var,
            command=self._layout_controls_changed,
        )
        self.layout_events_enabled_button.grid(
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
        self.layout_event_limit_var = tk.StringVar(
            value=str(self.layout_event_limit)
        )
        self.layout_event_limit_entry = ttk.Entry(
            events_frame,
            width=8,
            textvariable=self.layout_event_limit_var,
        )
        self.layout_event_limit_entry.grid(
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
        welcome_frame.grid(
            row=0,
            column=2,
            sticky="nsew",
            padx=(6, 0),
        )
        self.layout_welcome_enabled_var = tk.BooleanVar(
            value=self.layout_welcome_enabled
        )
        self.layout_welcome_enabled_button = ttk.Checkbutton(
            welcome_frame,
            text="Проверять основной текст",
            variable=self.layout_welcome_enabled_var,
            command=self._layout_controls_changed,
        )
        self.layout_welcome_enabled_button.grid(
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
        self.layout_welcome_limit_var = tk.StringVar(
            value=str(self.layout_welcome_limit)
        )
        self.layout_welcome_limit_entry = ttk.Entry(
            welcome_frame,
            width=8,
            textvariable=self.layout_welcome_limit_var,
        )
        self.layout_welcome_limit_entry.grid(
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
            self.layout_focus_limit_entry,
            self.layout_focus_exact_limit_entry,
            self.layout_event_limit_entry,
            self.layout_welcome_limit_entry,
        ):
            entry.bind("<FocusOut>", self._layout_limit_edited)
            entry.bind("<Return>", self._layout_limit_edited)

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
        self.layout_context_mod_var = tk.StringVar()
        ttk.Label(
            context_frame,
            textvariable=self.layout_context_mod_var,
            anchor=tk.W,
        ).grid(row=0, column=1, sticky="ew", padx=(8, 8))
        self.layout_context_mod_button = ttk.Button(
            context_frame,
            text="Выбрать…",
            command=self._select_context_mod,
        )
        self.layout_context_mod_button.grid(row=0, column=2, sticky=tk.E)

        preview_frame = ttk.LabelFrame(
            outer,
            text="Точная проверка фокусов через EaW Focus Text Preview",
            padding=(10, 8),
        )
        preview_frame.pack(fill=tk.X, pady=(10, 0))
        preview_frame.columnconfigure(1, weight=1)
        ttk.Label(
            preview_frame,
            text="EaWFocusTextPreviewCLI.exe:",
        ).grid(row=0, column=0, sticky=tk.W)
        self.layout_preview_cli_var = tk.StringVar()
        ttk.Label(
            preview_frame,
            textvariable=self.layout_preview_cli_var,
            anchor=tk.W,
        ).grid(row=0, column=1, sticky="ew", padx=(8, 8))
        self.layout_preview_cli_button = ttk.Button(
            preview_frame,
            text="Выбрать…",
            command=self._select_focus_preview_cli,
        )
        self.layout_preview_cli_button.grid(
            row=0,
            column=2,
            sticky=tk.E,
        )

        ttk.Label(preview_frame, text="Приоритет атласов:").grid(
            row=1,
            column=0,
            sticky=tk.W,
            pady=(8, 0),
        )
        self.layout_preview_priority_var = tk.StringVar(
            value=_PREVIEW_PRIORITY_LABELS[
                self.layout_focus_preview_priority
            ]
        )
        self.layout_preview_priority_combo = ttk.Combobox(
            preview_frame,
            textvariable=self.layout_preview_priority_var,
            values=tuple(_PREVIEW_PRIORITY_LABELS.values()),
            state="readonly",
            width=35,
        )
        self.layout_preview_priority_combo.grid(
            row=1,
            column=1,
            sticky=tk.W,
            padx=(8, 8),
            pady=(8, 0),
        )
        self.layout_preview_priority_combo.bind(
            "<<ComboboxSelected>>",
            self._layout_controls_changed,
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

        self.layout_progress = ttk.Progressbar(
            outer,
            mode="determinate",
        )
        self.layout_progress.pack(fill=tk.X, pady=(10, 4))
        self.layout_current_file_var = tk.StringVar(
            value="Настройте проверки и выберите файл или папку."
        )
        ttk.Label(
            outer,
            textvariable=self.layout_current_file_var,
            anchor=tk.W,
        ).pack(fill=tk.X, pady=(0, 8))

        table_frame = ttk.Frame(outer)
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
        self.layout_table = ttk.Treeview(
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
            self.layout_table.heading(column, text=headings[column])
            self.layout_table.column(
                column,
                width=widths[column],
                minwidth=50,
                stretch=column in {"file", "key", "message"},
                anchor=tk.W,
            )
        self.layout_table.heading(
            "length",
            text="Длина ↕",
            command=self._sort_layout_by_length,
        )

        vertical = ttk.Scrollbar(
            table_frame,
            orient=tk.VERTICAL,
            command=self.layout_table.yview,
        )
        horizontal = ttk.Scrollbar(
            table_frame,
            orient=tk.HORIZONTAL,
            command=self.layout_table.xview,
        )
        self.layout_table.configure(
            yscrollcommand=vertical.set,
            xscrollcommand=horizontal.set,
        )
        self.layout_table.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)
        self.layout_table.tag_configure(
            "warning",
            foreground="#9A6700",
        )
        self.layout_table.tag_configure(
            "preview_red",
            foreground="#B42318",
        )

        detail_frame = ttk.LabelFrame(
            outer,
            text=(
                "Полное сообщение — двойной щелчок открывает строку "
                "в Notepad++"
            ),
            padding=6,
        )
        detail_frame.pack(fill=tk.X, pady=(10, 0))
        self.layout_detail_var = tk.StringVar(value="")
        ttk.Label(
            detail_frame,
            textvariable=self.layout_detail_var,
            anchor=tk.W,
            justify=tk.LEFT,
            wraplength=1120,
        ).pack(fill=tk.X)

        self.layout_table.bind(
            "<<TreeviewSelect>>",
            self._show_layout_selected_detail,
        )
        self.layout_table.bind(
            "<Control-c>",
            self._copy_layout_selected_key,
        )
        self.layout_table.bind(
            "<Control-C>",
            self._copy_layout_selected_key,
        )
        self.layout_table.bind(
            "<Double-1>",
            self._open_double_clicked_layout_diagnostic,
        )
        self._refresh_layout_controls()
        self._refresh_context_mod_ui()
        self._refresh_focus_preview_ui()

    def _build_compare_tab(self) -> None:
        outer = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(outer, text="Сравнение ключей")

        controls = ttk.Frame(outer)
        controls.pack(fill=tk.X)
        self.compare_run_button = ttk.Button(
            controls,
            text="Сравнить локализации",
            command=self._start_localisation_comparison,
        )
        self.compare_run_button.pack(side=tk.LEFT)
        self.compare_clear_button = ttk.Button(
            controls,
            text="Очистить результаты",
            command=self._clear_compare_results,
        )
        self.compare_clear_button.pack(side=tk.LEFT, padx=(8, 0))
        self.compare_copy_key_button = ttk.Button(
            controls,
            text="Копировать ключ",
            command=self._copy_compare_selected_key,
            state=tk.DISABLED,
        )
        self.compare_copy_key_button.pack(side=tk.LEFT, padx=(8, 0))
        self.compare_summary_var = tk.StringVar(
            value="Укажите папку мода и запустите сравнение."
        )
        ttk.Label(
            controls,
            textvariable=self.compare_summary_var,
        ).pack(side=tk.LEFT, padx=(18, 0))

        settings_frame = ttk.LabelFrame(
            outer,
            text="Сравнение английской и русской локализаций",
            padding=(10, 8),
        )
        settings_frame.pack(fill=tk.X, pady=(10, 0))
        settings_frame.columnconfigure(1, weight=1)
        ttk.Label(
            settings_frame,
            text="Папка английской локализации:",
        ).grid(row=0, column=0, sticky=tk.W)
        self.compare_english_path_var = tk.StringVar()
        ttk.Label(
            settings_frame,
            textvariable=self.compare_english_path_var,
            anchor=tk.W,
        ).grid(row=0, column=1, sticky="ew", padx=(8, 8))
        self.compare_english_path_button = ttk.Button(
            settings_frame,
            text="Выбрать…",
            command=lambda: self._select_compare_folder("english"),
        )
        self.compare_english_path_button.grid(
            row=0,
            column=2,
            sticky=tk.E,
        )
        ttk.Label(
            settings_frame,
            text="Папка русской локализации:",
        ).grid(row=1, column=0, sticky=tk.W, pady=(8, 0))
        self.compare_russian_path_var = tk.StringVar()
        ttk.Label(
            settings_frame,
            textvariable=self.compare_russian_path_var,
            anchor=tk.W,
        ).grid(
            row=1,
            column=1,
            sticky="ew",
            padx=(8, 8),
            pady=(8, 0),
        )
        self.compare_russian_path_button = ttk.Button(
            settings_frame,
            text="Выбрать…",
            command=lambda: self._select_compare_folder("russian"),
        )
        self.compare_russian_path_button.grid(
            row=1,
            column=2,
            sticky=tk.E,
            pady=(8, 0),
        )
        ttk.Label(
            settings_frame,
            text=(
                "Обе папки проверяются рекурсивно. В английской части "
                "учитываются записи под l_english:, в русской — под "
                "l_russian:. Папки могут находиться где угодно."
            ),
            justify=tk.LEFT,
        ).grid(
            row=2,
            column=0,
            columnspan=3,
            sticky=tk.W,
            pady=(8, 0),
        )

        filter_frame = ttk.Frame(outer)
        filter_frame.pack(fill=tk.X, pady=(10, 0))
        ttk.Label(filter_frame, text="Показывать:").pack(side=tk.LEFT)
        self.compare_filter_var = tk.StringVar(value="Все проблемы")
        self.compare_filter_combo = ttk.Combobox(
            filter_frame,
            textvariable=self.compare_filter_var,
            values=tuple(_COMPARE_FILTER_LABELS),
            state="readonly",
            width=30,
        )
        self.compare_filter_combo.pack(side=tk.LEFT, padx=(8, 0))
        self.compare_filter_combo.bind(
            "<<ComboboxSelected>>",
            self._apply_compare_filter,
        )
        self.compare_visible_var = tk.StringVar(value="")
        ttk.Label(
            filter_frame,
            textvariable=self.compare_visible_var,
        ).pack(side=tk.LEFT, padx=(16, 0))
        self.compare_open_both_button = ttk.Button(
            filter_frame,
            text="Открыть оба",
            command=lambda: self._open_compare_selected_languages(
                ("english", "russian")
            ),
            state=tk.DISABLED,
        )
        self.compare_open_both_button.pack(side=tk.RIGHT)
        self.compare_open_russian_button = ttk.Button(
            filter_frame,
            text="Открыть русский",
            command=lambda: self._open_compare_selected_languages(
                ("russian",)
            ),
            state=tk.DISABLED,
        )
        self.compare_open_russian_button.pack(
            side=tk.RIGHT,
            padx=(0, 8),
        )
        self.compare_open_english_button = ttk.Button(
            filter_frame,
            text="Открыть английский",
            command=lambda: self._open_compare_selected_languages(
                ("english",)
            ),
            state=tk.DISABLED,
        )
        self.compare_open_english_button.pack(
            side=tk.RIGHT,
            padx=(0, 8),
        )

        self.compare_progress = ttk.Progressbar(
            outer,
            mode="determinate",
        )
        self.compare_progress.pack(fill=tk.X, pady=(10, 4))
        self.compare_status_var = tk.StringVar(
            value="Сравнение ещё не запускалось."
        )
        ttk.Label(
            outer,
            textvariable=self.compare_status_var,
            anchor=tk.W,
        ).pack(fill=tk.X, pady=(0, 8))

        table_frame = ttk.Frame(outer)
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
        self.compare_table = ttk.Treeview(
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
            self.compare_table.heading(
                column,
                text=headings[column],
            )
            self.compare_table.column(
                column,
                width=widths[column],
                minwidth=50,
                stretch=column in {"key", "file", "value", "message"},
                anchor=tk.W,
            )
        self.compare_table.heading(
            "key",
            text="Ключ ↕",
            command=self._sort_compare_by_key,
        )

        vertical = ttk.Scrollbar(
            table_frame,
            orient=tk.VERTICAL,
            command=self.compare_table.yview,
        )
        horizontal = ttk.Scrollbar(
            table_frame,
            orient=tk.HORIZONTAL,
            command=self.compare_table.xview,
        )
        self.compare_table.configure(
            yscrollcommand=vertical.set,
            xscrollcommand=horizontal.set,
        )
        self.compare_table.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)
        self.compare_table.tag_configure(
            "missing",
            foreground="#9A6700",
        )
        self.compare_table.tag_configure(
            "duplicate",
            foreground="#7A4E00",
        )
        self.compare_table.tag_configure(
            "error",
            foreground="#B00020",
        )

        detail_frame = ttk.LabelFrame(
            outer,
            text=(
                "Полное сообщение — двойной щелчок позволяет выбрать "
                "английский, русский или оба файла"
            ),
            padding=6,
        )
        detail_frame.pack(fill=tk.X, pady=(10, 0))
        self.compare_detail_var = tk.StringVar(value="")
        ttk.Label(
            detail_frame,
            textvariable=self.compare_detail_var,
            anchor=tk.W,
            justify=tk.LEFT,
            wraplength=1120,
        ).pack(fill=tk.X)

        self.compare_table.bind(
            "<<TreeviewSelect>>",
            self._show_compare_selected_detail,
        )
        self.compare_table.bind(
            "<Control-c>",
            self._copy_compare_selected_key,
        )
        self.compare_table.bind(
            "<Control-C>",
            self._copy_compare_selected_key,
        )
        self.compare_table.bind(
            "<Double-1>",
            self._open_double_clicked_compare_issue,
        )
        self.compare_table.bind(
            "<Button-3>",
            self._show_compare_context_menu,
        )
        self.compare_context_menu = tk.Menu(self.root, tearoff=False)
        self.compare_context_menu.add_command(
            label="Открыть английский файл",
            command=lambda: self._open_compare_selected_languages(
                ("english",)
            ),
        )
        self.compare_context_menu.add_command(
            label="Открыть русский файл",
            command=lambda: self._open_compare_selected_languages(
                ("russian",)
            ),
        )
        self.compare_context_menu.add_command(
            label="Открыть оба файла",
            command=lambda: self._open_compare_selected_languages(
                ("english", "russian")
            ),
        )
        self.compare_context_menu.add_separator()
        self.compare_context_menu.add_command(
            label="Копировать ключ",
            command=self._copy_compare_selected_key,
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
            self.layout_preview_cli_var.set(
                "не выбран — точная проверка заблокирована"
            )
            return
        path = Path(self.layout_focus_preview_cli_path)
        try:
            resolved = validate_focus_preview_installation(path)
        except FocusPreviewError as error:
            self.layout_preview_cli_var.set(str(error))
            return
        self.layout_preview_cli_var.set(str(resolved))

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
        self.layout_current_file_var.set(
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
        for raw_path, variable, label in (
            (
                self.compare_english_path,
                self.compare_english_path_var,
                "английская",
            ),
            (
                self.compare_russian_path,
                self.compare_russian_path_var,
                "русская",
            ),
        ):
            if not raw_path:
                variable.set(
                    f"не выбрана — {label} папка обязательна"
                )
                continue
            path = Path(raw_path)
            variable.set(
                str(path)
                if path.is_dir()
                else f"папка недоступна: {path}"
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
        self.compare_status_var.set(
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

    @staticmethod
    def _positive_limit(value: str, label: str) -> int:
        try:
            parsed = int(value.strip())
        except ValueError as error:
            raise ValueError(
                f"Лимит для {label} должен быть целым числом."
            ) from error
        if parsed <= 0:
            raise ValueError(
                f"Лимит для {label} должен быть больше нуля."
            )
        return parsed

    def _capture_layout_settings(self) -> TextLayoutOptions:
        focus_mode = cast(
            FocusCheckMode,
            self.layout_focus_mode_var.get(),
        )
        if focus_mode not in {"length", "newline", "exact"}:
            raise ValueError("Выберите режим проверки фокусов.")

        preview_priority = next(
            (
                value
                for value, label in _PREVIEW_PRIORITY_LABELS.items()
                if label == self.layout_preview_priority_var.get()
            ),
            "",
        )
        if preview_priority not in {"auto_ru", "auto_en", "ru", "en"}:
            raise ValueError("Выберите приоритет атласов.")

        focus_limit = self._positive_limit(
            self.layout_focus_limit_var.get(),
            "фокусов",
        )
        event_limit = self._positive_limit(
            self.layout_event_limit_var.get(),
            "ивентов",
        )
        welcome_limit = self._positive_limit(
            self.layout_welcome_limit_var.get(),
            "вступительных экранов",
        )
        options = TextLayoutOptions(
            focus_enabled=self.layout_focus_enabled_var.get(),
            focus_mode=focus_mode,
            focus_limit=focus_limit,
            focus_preview_cli_path=(
                Path(self.layout_focus_preview_cli_path)
                if self.layout_focus_preview_cli_path
                else None
            ),
            focus_preview_priority=cast(
                FocusPreviewPriorityMode,
                preview_priority,
            ),
            events_enabled=self.layout_events_enabled_var.get(),
            event_limit=event_limit,
            welcome_enabled=self.layout_welcome_enabled_var.get(),
            welcome_limit=welcome_limit,
        )

        self.layout_focus_enabled = options.focus_enabled
        self.layout_focus_mode = options.focus_mode
        self.layout_focus_limit = options.focus_limit
        self.layout_focus_preview_priority = preview_priority
        self.layout_events_enabled = options.events_enabled
        self.layout_event_limit = options.event_limit
        self.layout_welcome_enabled = options.welcome_enabled
        self.layout_welcome_limit = options.welcome_limit
        return options

    def _restore_layout_variables(self) -> None:
        self.layout_focus_enabled_var.set(self.layout_focus_enabled)
        self.layout_focus_mode_var.set(self.layout_focus_mode)
        self.layout_focus_limit_var.set(str(self.layout_focus_limit))
        self.layout_preview_priority_var.set(
            _PREVIEW_PRIORITY_LABELS[self.layout_focus_preview_priority]
        )
        self.layout_events_enabled_var.set(self.layout_events_enabled)
        self.layout_event_limit_var.set(str(self.layout_event_limit))
        self.layout_welcome_enabled_var.set(self.layout_welcome_enabled)
        self.layout_welcome_limit_var.set(str(self.layout_welcome_limit))

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
        self.layout_current_file_var.set(
            "Настройки проверки текстов сохранены."
        )
        return "break"

    def _layout_limit_edited(self, _event: object | None = None) -> str:
        return self._layout_controls_changed()

    def _refresh_layout_controls(self) -> None:
        base_state = tk.DISABLED if self.busy else tk.NORMAL
        for widget in (
            self.layout_clear_button,
            self.layout_context_mod_button,
            self.layout_focus_enabled_button,
            self.layout_events_enabled_button,
            self.layout_welcome_enabled_button,
        ):
            widget.configure(state=base_state)
        any_check_enabled = (
            self.layout_focus_enabled_var.get()
            or self.layout_events_enabled_var.get()
            or self.layout_welcome_enabled_var.get()
        )
        scan_state = (
            tk.NORMAL
            if not self.busy and any_check_enabled
            else tk.DISABLED
        )
        self.layout_file_button.configure(state=scan_state)
        self.layout_folder_button.configure(state=scan_state)

        focus_enabled = (
            not self.busy and self.layout_focus_enabled_var.get()
        )
        focus_mode_state = tk.NORMAL if focus_enabled else tk.DISABLED
        self.layout_focus_length_button.configure(
            state=focus_mode_state
        )
        self.layout_focus_newline_button.configure(
            state=focus_mode_state
        )
        self.layout_focus_exact_button.configure(
            state=focus_mode_state
        )
        self.layout_focus_limit_entry.configure(
            state=(
                tk.NORMAL
                if focus_enabled
                and self.layout_focus_mode_var.get() == "length"
                else tk.DISABLED
            )
        )
        self.layout_focus_exact_limit_entry.configure(
            state=(
                tk.NORMAL
                if focus_enabled
                and self.layout_focus_mode_var.get() == "exact"
                else tk.DISABLED
            )
        )
        preview_enabled = (
            focus_enabled
            and self.layout_focus_mode_var.get() == "exact"
        )
        self.layout_preview_cli_button.configure(
            state=tk.NORMAL if preview_enabled else tk.DISABLED
        )
        self.layout_preview_priority_combo.configure(
            state="readonly" if preview_enabled else tk.DISABLED
        )
        self.layout_event_limit_entry.configure(
            state=(
                tk.NORMAL
                if not self.busy and self.layout_events_enabled_var.get()
                else tk.DISABLED
            )
        )
        self.layout_welcome_limit_entry.configure(
            state=(
                tk.NORMAL
                if not self.busy and self.layout_welcome_enabled_var.get()
                else tk.DISABLED
            )
        )

    def _refresh_compare_controls(self) -> None:
        if not hasattr(self, "compare_run_button"):
            return
        state = tk.DISABLED if self.busy else tk.NORMAL
        self.compare_run_button.configure(state=state)
        self.compare_clear_button.configure(state=state)
        self.compare_english_path_button.configure(state=state)
        self.compare_russian_path_button.configure(state=state)
        self.compare_filter_combo.configure(
            state=tk.DISABLED if self.busy else "readonly"
        )
        self._refresh_compare_open_controls(
            self._compare_selected_issue()
        )

    def _refresh_context_mod_ui(self) -> None:
        if not self.context_mod_path:
            self.context_mod_var.set("не указана — контекстный режим заблокирован")
            if hasattr(self, "layout_context_mod_var"):
                self.layout_context_mod_var.set(
                    "не указана — проверка текстов заблокирована"
                )
            return
        path = Path(self.context_mod_path)
        if not path.is_dir() or not is_context_root(path):
            message = f"путь недоступен или не является папкой мода: {path}"
            self.context_mod_var.set(message)
            if hasattr(self, "layout_context_mod_var"):
                self.layout_context_mod_var.set(message)
            return
        message = f"{mod_display_name(path)} — {path}"
        self.context_mod_var.set(message)
        if hasattr(self, "layout_context_mod_var"):
            self.layout_context_mod_var.set(message)

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
        if hasattr(self, "layout_current_file_var"):
            self.layout_current_file_var.set(
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
        self._refresh_layout_controls()
        self._refresh_compare_controls()

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

    def _clear_layout_results(self) -> None:
        for item in self.layout_table.get_children():
            self.layout_table.delete(item)
        self.layout_diagnostics_by_item.clear()
        self.layout_summary_var.set("Результаты очищены.")
        self.layout_current_file_var.set(
            "Настройте проверки и выберите файл или папку."
        )
        self.layout_detail_var.set("")
        self.layout_progress.stop()
        self.layout_progress.configure(mode="determinate")
        self.layout_progress.configure(value=0, maximum=1)
        self.layout_copy_key_button.configure(state=tk.DISABLED)

    def _clear_compare_results(self) -> None:
        for item in self.compare_table.get_children():
            self.compare_table.delete(item)
        self.compare_issues_by_item.clear()
        self.compare_all_issues.clear()
        self.compare_summary_var.set("Результаты очищены.")
        self.compare_visible_var.set("")
        self.compare_status_var.set(
            "Укажите папку мода и запустите сравнение."
        )
        self.compare_detail_var.set("")
        self.compare_progress.configure(value=0, maximum=1)
        self.compare_copy_key_button.configure(state=tk.DISABLED)
        self._refresh_compare_open_controls(None)

    def _start_localisation_comparison(self) -> None:
        if self.worker is not None and self.worker.is_alive():
            return

        folders = self._require_compare_folders()
        if folders is None:
            self.compare_status_var.set(
                "Сравнение отменено: обе папки обязательны."
            )
            return
        english_root, russian_root = folders

        self._clear_compare_results()
        self._set_busy(True)
        self.compare_summary_var.set("Чтение файлов локализации…")
        self.compare_status_var.set(
            f"EN: {english_root}; RU: {russian_root}"
        )

        def progress(current: int, total: int, path: Path) -> None:
            self.events.put(
                ("compare_progress", (current, total, path))
            )

        def work() -> None:
            try:
                result = self.localisation_comparator.scan(
                    english_root,
                    russian_root,
                    progress=progress,
                )
                self.events.put(("compare_result", result))
            except Exception as error:  # UI boundary: keep the app alive.
                self.events.put(("compare_failure", error))

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    def _start_scan(self, target: Path) -> None:
        if self.worker is not None and self.worker.is_alive():
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
        self._set_busy(True)
        excluded_characters = frozenset(self.excluded_characters)
        show_unknown_context_warnings = (
            self.show_unknown_context_warnings
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

        def progress(current: int, total: int, path: Path) -> None:
            self.events.put(("progress", (current, total, path)))

        def work() -> None:
            try:
                result = self.checker.scan(
                    target,
                    progress=progress,
                    glyph_mode=glyph_mode,
                    excluded_characters=excluded_characters,
                    context_mod_root=context_mod_root,
                    context_game_root=context_game_root,
                    show_unknown_context_warnings=(
                        show_unknown_context_warnings
                    ),
                )
                self.events.put(("result", (result, glyph_mode)))
            except Exception as error:  # UI boundary: keep the app alive.
                self.events.put(("failure", error))

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    def _start_layout_scan(self, target: Path) -> None:
        if self.worker is not None and self.worker.is_alive():
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
                    self.layout_current_file_var.set(
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
            self.layout_current_file_var.set(
                "Проверка отменена: папка мода не указана."
            )
            return
        context_game_root = self._resolve_hoi4_install()

        self._clear_layout_results()
        self._set_busy(True)
        self.layout_summary_var.set(f"Проверяется: {target}")
        game_note = (
            f"; HOI4: {context_game_root}"
            if context_game_root is not None
            else "; стандартная HOI4 не найдена"
        )
        self.layout_current_file_var.set(
            f"Контекст: {context_mod_root}{game_note}"
        )

        def progress(current: int, total: int, path: Path) -> None:
            self.events.put(
                ("layout_progress", (current, total, path))
            )

        def preview_started(total: int) -> None:
            self.events.put(("layout_preview_started", total))

        def work() -> None:
            try:
                result = self.text_layout_checker.scan(
                    target=target,
                    mod_root=context_mod_root,
                    options=options,
                    game_root=context_game_root,
                    progress=progress,
                    preview_started=preview_started,
                )
                self.events.put(("layout_result", result))
            except Exception as error:  # UI boundary: keep the app alive.
                self.events.put(("layout_failure", error))

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    def _poll_events(self) -> None:
        try:
            while True:
                event, payload = self.events.get_nowait()
                if event == "progress":
                    current, total, path = payload
                    self.progress.configure(maximum=total, value=current)
                    self.current_file_var.set(str(path))
                elif event == "result":
                    result, glyph_mode = payload
                    self._show_result(result, glyph_mode)
                    self._set_busy(False)
                elif event == "failure":
                    self._set_busy(False)
                    self.summary_var.set("Проверка завершилась внутренней ошибкой.")
                    messagebox.showerror("Ошибка", str(payload))
                elif event == "layout_progress":
                    current, total, path = payload
                    self.layout_progress.configure(
                        maximum=total,
                        value=current,
                    )
                    self.layout_current_file_var.set(str(path))
                elif event == "layout_result":
                    self._show_layout_result(
                        cast(TextLayoutResult, payload)
                    )
                    self._set_busy(False)
                elif event == "layout_preview_started":
                    self.layout_progress.configure(mode="indeterminate")
                    self.layout_progress.start(12)
                    self.layout_current_file_var.set(
                        "Точная проверка через EaW Focus Text Preview: "
                        f"{payload} описаний фокусов. Это может занять "
                        "некоторое время…"
                    )
                elif event == "layout_failure":
                    self.layout_progress.stop()
                    self.layout_progress.configure(mode="determinate")
                    self._set_busy(False)
                    self.layout_summary_var.set(
                        "Проверка завершилась внутренней ошибкой."
                    )
                    messagebox.showerror("Ошибка", str(payload))
                elif event == "compare_progress":
                    current, total, path = payload
                    self.compare_progress.configure(
                        maximum=total,
                        value=current,
                    )
                    self.compare_status_var.set(str(path))
                elif event == "compare_result":
                    self._show_compare_result(
                        cast(LocalisationComparisonResult, payload)
                    )
                    self._set_busy(False)
                elif event == "compare_failure":
                    self._set_busy(False)
                    self.compare_summary_var.set(
                        "Сравнение завершилось внутренней ошибкой."
                    )
                    messagebox.showerror(
                        "Ошибка сравнения локализаций",
                        str(payload),
                    )
                elif event == "compare_editor_opened":
                    self._show_compare_editor_result(
                        cast(
                            list[
                                tuple[
                                    ComparisonLanguage,
                                    Diagnostic,
                                    OpenResult,
                                ]
                            ],
                            payload,
                        )
                    )
                elif event == "compare_editor_failure":
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
                        payload,
                    )
                    self._show_compare_editor_failure(
                        error,
                        opened,
                    )
                elif event == "editor_opened":
                    diagnostic, result, status_var = payload
                    self._show_editor_result(
                        diagnostic,
                        result,
                        status_var,
                    )
                elif event == "editor_failure":
                    messagebox.showerror("Не удалось открыть Notepad++", str(payload))
        except queue.Empty:
            pass
        finally:
            self.root.after(100, self._poll_events)

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

    def _show_layout_result(self, result: TextLayoutResult) -> None:
        self.layout_progress.stop()
        self.layout_progress.configure(mode="determinate")
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
        self.layout_summary_var.set(summary)

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
        self.layout_current_file_var.set(status)
        self.layout_progress.configure(
            maximum=max(result.files_checked, 1),
            value=result.files_checked,
        )
        for diagnostic in result.diagnostics:
            self._insert_layout_diagnostic(diagnostic)
        if not result.diagnostics:
            self.layout_detail_var.set("Проблем не обнаружено.")
        if result.preview_error_messages:
            shown = "\n".join(result.preview_error_messages[:5])
            remaining = len(result.preview_error_messages) - 5
            if remaining > 0:
                shown += f"\n…и ещё ошибок: {remaining}"
            messagebox.showwarning(
                "Часть фокусов не проверена точным модулем",
                shown,
            )

    def _show_compare_result(
        self,
        result: LocalisationComparisonResult,
    ) -> None:
        self.compare_summary_var.set(
            f"Файлов: {result.files_checked} "
            f"(EN: {result.english_files}, RU: {result.russian_files}); "
            f"уникальных ключей EN: {result.english_keys}, "
            f"RU: {result.russian_keys}; совпадают: {result.common_keys}."
        )
        self.compare_status_var.set(
            f"Сравнение завершено: нет в русской — "
            f"{result.missing_russian}; нет в английской — "
            f"{result.missing_english}; дублей — "
            f"{result.duplicate_count}; ошибок разбора — "
            f"{result.parse_errors}."
        )
        self.compare_progress.configure(
            maximum=max(result.files_checked, 1),
            value=result.files_checked,
        )
        self.compare_all_issues = list(result.issues)
        self._apply_compare_filter()

    @staticmethod
    def _comparison_issue_matches(
        issue: ComparisonIssue,
        selected_filter: str,
    ) -> bool:
        if selected_filter == "all":
            return True
        if selected_filter == "missing":
            return issue.category in {
                "missing_russian",
                "missing_english",
            }
        if selected_filter == "duplicates":
            return issue.category in {
                "duplicate_english",
                "duplicate_russian",
            }
        return issue.category == selected_filter

    def _apply_compare_filter(
        self,
        _event: object | None = None,
    ) -> str:
        selected_filter = _COMPARE_FILTER_LABELS.get(
            self.compare_filter_var.get(),
            "all",
        )
        for item in self.compare_table.get_children():
            self.compare_table.delete(item)
        self.compare_issues_by_item.clear()
        self.compare_copy_key_button.configure(state=tk.DISABLED)
        self._refresh_compare_open_controls(None)
        self.compare_detail_var.set("")

        visible = [
            issue
            for issue in self.compare_all_issues
            if self._comparison_issue_matches(
                issue,
                selected_filter,
            )
        ]
        for issue in visible:
            self._insert_compare_issue(issue)
        self.compare_visible_var.set(
            f"Показано: {len(visible)} из {len(self.compare_all_issues)}"
        )
        if not visible and self.compare_all_issues:
            self.compare_detail_var.set(
                "Для выбранного фильтра результатов нет."
            )
        elif not self.compare_all_issues:
            self.compare_detail_var.set(
                "Различий, дублей и ошибок разбора не обнаружено."
            )
        return "break"

    @staticmethod
    def _comparison_value_preview(value: str) -> str:
        normalized = value.replace("\r", " ").replace("\n", " ")
        if len(normalized) <= 180:
            return normalized
        return normalized[:177] + "…"

    def _insert_compare_issue(self, issue: ComparisonIssue) -> None:
        if issue.category == "parse_error":
            tag = "error"
        elif issue.category.startswith("duplicate_"):
            tag = "duplicate"
        else:
            tag = "missing"
        item = self.compare_table.insert(
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
                self._comparison_value_preview(issue.raw_value),
                issue.message,
            ),
            tags=(tag,),
        )
        self.compare_issues_by_item[item] = issue

    def _sort_compare_by_key(self) -> None:
        descending = self.compare_key_sort_descending
        rows = [
            (
                item,
                self.compare_issues_by_item.get(item),
            )
            for item in self.compare_table.get_children("")
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
        rows.sort(
            key=lambda row: not bool(
                row[1] is not None and row[1].key
            )
        )
        for position, (item, _) in enumerate(rows):
            self.compare_table.move(item, "", position)
        self.compare_table.heading(
            "key",
            text="Ключ ↓" if descending else "Ключ ↑",
            command=self._sort_compare_by_key,
        )
        self.compare_key_sort_descending = not descending

    def _compare_selected_issue(self) -> ComparisonIssue | None:
        selected = self.compare_table.selection()
        if not selected:
            return None
        return self.compare_issues_by_item.get(selected[0])

    def _show_compare_selected_detail(
        self,
        _event: object | None = None,
    ) -> None:
        issue = self._compare_selected_issue()
        self.compare_copy_key_button.configure(
            state=(
                tk.NORMAL
                if issue is not None and issue.key
                else tk.DISABLED
            )
        )
        self._refresh_compare_open_controls(issue)
        if issue is None:
            return
        value = (
            f" Значение: {issue.raw_value}"
            if issue.raw_value
            else ""
        )
        self.compare_detail_var.set(
            f"{issue.path}:{issue.line}:{issue.column} — "
            f"{issue.message}{value}"
        )

    def _copy_compare_selected_key(
        self,
        _event: object | None = None,
    ) -> str:
        issue = self._compare_selected_issue()
        if issue is None or not issue.key:
            self.root.bell()
            return "break"
        self.root.clipboard_clear()
        self.root.clipboard_append(issue.key)
        self.root.update_idletasks()
        self.compare_status_var.set(f"Ключ скопирован: {issue.key}")
        return "break"

    @staticmethod
    def _compare_language_available(
        issue: ComparisonIssue | None,
        language: ComparisonLanguage,
    ) -> bool:
        if issue is None:
            return False
        diagnostic = issue.diagnostic_for(language)
        return (
            diagnostic is not None
            and diagnostic.path.is_file()
        )

    def _refresh_compare_open_controls(
        self,
        issue: ComparisonIssue | None,
    ) -> None:
        if not hasattr(self, "compare_open_english_button"):
            return
        english_available = (
            not self.busy
            and self._compare_language_available(issue, "english")
        )
        russian_available = (
            not self.busy
            and self._compare_language_available(issue, "russian")
        )
        self.compare_open_english_button.configure(
            state=tk.NORMAL if english_available else tk.DISABLED
        )
        self.compare_open_russian_button.configure(
            state=tk.NORMAL if russian_available else tk.DISABLED
        )
        self.compare_open_both_button.configure(
            state=(
                tk.NORMAL
                if english_available and russian_available
                else tk.DISABLED
            )
        )

    def _popup_compare_context_menu(
        self,
        event: tk.Event,
        issue: ComparisonIssue | None,
    ) -> str:
        english_available = self._compare_language_available(
            issue,
            "english",
        )
        russian_available = self._compare_language_available(
            issue,
            "russian",
        )
        self.compare_context_menu.entryconfigure(
            "Открыть английский файл",
            state=tk.NORMAL if english_available else tk.DISABLED,
        )
        self.compare_context_menu.entryconfigure(
            "Открыть русский файл",
            state=tk.NORMAL if russian_available else tk.DISABLED,
        )
        self.compare_context_menu.entryconfigure(
            "Открыть оба файла",
            state=(
                tk.NORMAL
                if english_available and russian_available
                else tk.DISABLED
            ),
        )
        self.compare_context_menu.entryconfigure(
            "Копировать ключ",
            state=(
                tk.NORMAL
                if issue is not None and issue.key
                else tk.DISABLED
            ),
        )
        try:
            self.compare_context_menu.tk_popup(
                event.x_root,
                event.y_root,
            )
        finally:
            self.compare_context_menu.grab_release()
        return "break"

    def _show_compare_context_menu(self, event: tk.Event) -> str:
        item = self.compare_table.identify_row(event.y)
        if not item:
            return "break"
        self.compare_table.selection_set(item)
        self.compare_table.focus(item)
        issue = self.compare_issues_by_item.get(item)
        self._show_compare_selected_detail()
        return self._popup_compare_context_menu(event, issue)

    def _open_double_clicked_compare_issue(
        self,
        event: tk.Event,
    ) -> str:
        item = self.compare_table.identify_row(event.y)
        if not item:
            return "break"
        self.compare_table.selection_set(item)
        self.compare_table.focus(item)
        issue = self.compare_issues_by_item.get(item)
        self._show_compare_selected_detail()
        return self._popup_compare_context_menu(event, issue)

    def _open_compare_selected_languages(
        self,
        languages: tuple[ComparisonLanguage, ...],
    ) -> str:
        issue = self._compare_selected_issue()
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
            self.compare_status_var.set(
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
        self.compare_status_var.set(
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
                self.events.put(
                    ("compare_editor_failure", (error, opened))
                )
                return
            self.events.put(("compare_editor_opened", opened))

        threading.Thread(target=work, daemon=True).start()
        return "break"

    def _insert_layout_diagnostic(
        self,
        diagnostic: Diagnostic,
    ) -> None:
        item = self.layout_table.insert(
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
                }.get(
                    diagnostic.preview_status,
                    diagnostic.preview_status,
                ),
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
        self.layout_diagnostics_by_item[item] = diagnostic

    def _sort_layout_by_length(self) -> None:
        descending = self.layout_length_sort_descending
        rows = [
            (
                item,
                self.layout_diagnostics_by_item.get(item),
            )
            for item in self.layout_table.get_children("")
        ]

        def sort_key(
            row: tuple[str, Diagnostic | None],
        ) -> tuple[bool, int]:
            diagnostic = row[1]
            measured = (
                diagnostic.measured_length
                if diagnostic is not None
                else 0
            )
            missing = measured <= 0
            return (
                missing,
                -measured if descending else measured,
            )

        rows.sort(key=sort_key)
        for position, (item, _) in enumerate(rows):
            self.layout_table.move(item, "", position)

        self.layout_table.heading(
            "length",
            text="Длина ↓" if descending else "Длина ↑",
            command=self._sort_layout_by_length,
        )
        self.layout_length_sort_descending = not descending

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

    def _show_layout_selected_detail(self, _event: object) -> None:
        diagnostic = self._layout_selected_diagnostic()
        self.layout_copy_key_button.configure(
            state=(
                tk.NORMAL
                if diagnostic is not None and diagnostic.key
                else tk.DISABLED
            )
        )
        if diagnostic is None:
            return
        self.layout_detail_var.set(
            f"{diagnostic.path}:{diagnostic.line}:{diagnostic.column} — "
            f"{diagnostic.message} Основание роли: "
            f"{diagnostic.role_evidence}"
        )

    def _layout_selected_diagnostic(self) -> Diagnostic | None:
        selected = self.layout_table.selection()
        if not selected:
            return None
        return self.layout_diagnostics_by_item.get(selected[0])

    def _copy_layout_selected_key(
        self,
        _event: object | None = None,
    ) -> str:
        diagnostic = self._layout_selected_diagnostic()
        if diagnostic is None or not diagnostic.key:
            self.root.bell()
            return "break"
        self.root.clipboard_clear()
        self.root.clipboard_append(diagnostic.key)
        self.root.update_idletasks()
        self.layout_current_file_var.set(
            f"Ключ скопирован: {diagnostic.key}"
        )
        return "break"

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
            ),
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

    def _open_double_clicked_layout_diagnostic(
        self,
        event: tk.Event,
    ) -> str:
        item = self.layout_table.identify_row(event.y)
        if not item:
            return "break"
        self.layout_table.selection_set(item)
        self.layout_table.focus(item)
        return self._open_diagnostic(
            self._layout_selected_diagnostic(),
            self.layout_current_file_var,
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
                self.events.put(("editor_failure", error))
                return
            self.events.put(
                ("editor_opened", (diagnostic, result, status_var))
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
            self.compare_status_var.set(
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
                self.compare_status_var.set(
                    f"Открыт {opened_labels} файл в Notepad++ "
                    f"на позиции: {location}"
                )
            else:
                self.compare_status_var.set(
                    f"Открыт {opened_labels} файл в Notepad++: "
                    f"{location}. Точная позиция не подтверждена."
                )
            return
        active_language, active_diagnostic, _ = opened[-1]
        self.compare_status_var.set(
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
            self.compare_status_var.set(
                f"Открыто файлов: {len(opened)}; следующий файл "
                "открыть не удалось."
            )
        else:
            self.compare_status_var.set(
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
