from __future__ import annotations

import tkinter as tk
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
from .gui_check_tab import LocalisationCheckTab
from .gui_compare_tab import ComparisonTab
from .gui_editor import NotepadPlusPlusController
from .gui_exceptions import CharacterExceptionsController
from .gui_layout_tab import TextLayoutTab
from .localisation_compare import (
    ComparisonLanguage,
    LocalisationComparator,
    LocalisationComparisonResult,
)
from .settings import (
    AppSettings,
    SettingsError,
    SettingsStore,
    settings_path_for,
)
from .text_layout_checker import (
    TextLayoutChecker,
    TextLayoutOptions,
    TextLayoutResult,
)
from .version import DISPLAY_VERSION


class CheckerApplication:
    def __init__(self, root: tk.Tk, app_root: Path) -> None:
        self.root = root
        self.app_root = app_root
        self.tasks = BackgroundTaskRunner()
        self.busy = False
        self.settings_path = settings_path_for(app_root)
        self.settings_error = ""
        try:
            self.settings = SettingsStore.load(self.settings_path)
        except SettingsError as error:
            self.settings = SettingsStore(self.settings_path, AppSettings())
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
        self.exceptions = CharacterExceptionsController(
            root=self.root,
            characters=self.settings.current.excluded_characters,
            persist=lambda characters: self.settings.update(
                excluded_characters=characters
            ),
            set_count=lambda count: self.check_tab.set_exceptions_count(count),
            set_status=lambda status: self.check_tab.set_status(status),
            selected_character=lambda: self.check_tab.selected_character(),
        )
        self.editor = NotepadPlusPlusController(
            root=self.root,
            tasks=self.tasks,
            configured_path=(
                lambda: self.settings.current.notepad_plus_plus_path
            ),
            remember_executable=self._remember_notepad_plus_plus,
            fullscreen=(
                lambda: self.settings.current.notepad_plus_plus_fullscreen
            ),
        )
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
        settings = self.settings.current
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True)
        self.check_tab = LocalisationCheckTab(
            root=self.root,
            notebook=self.notebook,
            font_available=self.font_profile is not None,
            font_status=self.font_status,
            show_unknown_context=settings.show_unknown_context_warnings,
            check_russian_straight_quotes=settings.check_russian_straight_quotes,
            notepad_fullscreen=settings.notepad_plus_plus_fullscreen,
            on_choose_file=self._choose_file,
            on_choose_folder=self._choose_folder,
            on_open_exceptions=self.exceptions.open_dialog,
            on_select_context_mod=self._select_context_mod,
            on_unknown_context_changed=self._unknown_context_visibility_changed,
            on_russian_quotes_changed=self._russian_straight_quotes_changed,
            on_notepad_mode_changed=self._notepad_window_mode_changed,
            on_open_diagnostic=self.editor.open_diagnostic,
            on_add_selected_exception=self.exceptions.add_selected_character,
            is_character_excluded=self.exceptions.contains,
            on_export=self._export_table_results,
        )
        self.exceptions.refresh()
        self._refresh_context_mod_ui()
        self._build_layout_tab()
        self._build_compare_tab()
        self._refresh_export_controls()

    def _build_layout_tab(self) -> None:
        settings = self.settings.current
        options = TextLayoutOptions(
            focus_enabled=settings.layout_focus_enabled,
            focus_mode=settings.layout_focus_mode,
            focus_limit=settings.layout_focus_limit,
            focus_preview_cli_path=(
                Path(settings.layout_focus_preview_cli_path)
                if settings.layout_focus_preview_cli_path
                else None
            ),
            focus_preview_priority=settings.layout_focus_preview_priority,
            events_enabled=settings.layout_events_enabled,
            event_limit=settings.layout_event_limit,
            welcome_enabled=settings.layout_welcome_enabled,
            welcome_limit=settings.layout_welcome_limit,
            title_newline_enabled=(
                settings.layout_title_newline_enabled
            ),
        )
        self.layout_tab = TextLayoutTab(
            root=self.root,
            notebook=self.notebook,
            options=options,
            on_run=self._start_layout_scan,
            on_select_source=self._select_layout_source,
            on_controls_changed=self._layout_controls_changed,
            on_select_context_mod=self._select_context_mod,
            on_select_preview_cli=self._select_focus_preview_cli,
            on_open_languages=self._open_layout_selected_languages,
            on_export=self._export_table_results,
        )
        self._refresh_layout_source_ui()
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

    def _refresh_layout_source_ui(self) -> None:
        if not hasattr(self, "layout_tab"):
            return
        settings = self.settings.current
        self.layout_tab.set_source_paths(
            settings.layout_english_path,
            settings.layout_russian_path,
        )

    def _select_layout_source(
        self,
        language: ComparisonLanguage,
        source_kind: str,
    ) -> Path | None:
        if source_kind not in {"file", "folder"}:
            raise ValueError("Неизвестный тип источника локализации.")
        attribute = (
            "layout_english_path"
            if language == "english"
            else "layout_russian_path"
        )
        current_value = getattr(self.settings.current, attribute)
        current = Path(current_value) if current_value else None
        language_label = "английской" if language == "english" else "русской"
        if source_kind == "file":
            options: dict[str, object] = {
                "parent": self.root,
                "title": f"Выберите файл {language_label} локализации",
                "filetypes": [
                    ("HOI4 localisation", "*.yml"),
                    ("Все файлы", "*.*"),
                ],
            }
            if current is not None:
                initial = current.parent if current.is_file() else current
                if initial.is_dir():
                    options["initialdir"] = str(initial)
            selected = filedialog.askopenfilename(**options)
        else:
            options = {
                "parent": self.root,
                "title": f"Выберите папку {language_label} локализации",
                "mustexist": True,
            }
            if current is not None:
                initial = current if current.is_dir() else current.parent
                if initial.is_dir():
                    options["initialdir"] = str(initial)
            selected = filedialog.askdirectory(**options)
        if not selected:
            return None

        path = Path(selected).resolve()
        try:
            self.settings.update(**{attribute: str(path)})
        except SettingsError as error:
            messagebox.showerror(
                "Источник локализации не сохранён",
                str(error),
            )
            return None
        self._refresh_layout_source_ui()
        self.layout_tab.set_status(f"Выбран {language_label} источник: {path}")
        return path

    def _refresh_focus_preview_ui(self) -> None:
        cli_path = self.settings.current.layout_focus_preview_cli_path
        if not cli_path:
            self.layout_tab.set_preview_cli_status(
                "не выбран — точная проверка заблокирована",
                False,
            )
            return
        path = Path(cli_path)
        try:
            resolved = validate_focus_preview_installation(path)
        except FocusPreviewError as error:
            self.layout_tab.set_preview_cli_status(str(error), False)
            return
        self.layout_tab.set_preview_cli_status(str(resolved), True)

    def _select_focus_preview_cli(self) -> Path | None:
        cli_path = self.settings.current.layout_focus_preview_cli_path
        current = (
            Path(cli_path) if cli_path else None
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
            executable = validate_focus_preview_installation(Path(selected))
        except FocusPreviewError as error:
            messagebox.showerror(
                "Неполная установка EaW Focus Text Preview",
                str(error),
            )
            return None

        try:
            self.settings.update(
                layout_focus_preview_cli_path=str(executable)
            )
        except SettingsError as error:
            messagebox.showerror(
                "Путь к EaW Focus Text Preview не сохранён",
                str(error),
            )
            self._refresh_focus_preview_ui()
            return None
        self._refresh_focus_preview_ui()
        self.layout_tab.set_status(f"Точный проверяющий модуль выбран: {executable}")
        return executable

    def _require_focus_preview_cli(self) -> Path | None:
        cli_path = self.settings.current.layout_focus_preview_cli_path
        if cli_path:
            try:
                return validate_focus_preview_installation(
                    Path(cli_path)
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
        selected = self._select_focus_preview_cli()
        if selected is None:
            self.layout_tab.flash_preview_requirement()
        return selected

    def _refresh_compare_paths_ui(self) -> None:
        if hasattr(self, "compare_tab"):
            settings = self.settings.current
            self.compare_tab.set_paths(
                settings.compare_english_path,
                settings.compare_russian_path,
            )

    def _select_compare_folder(self, language: str) -> Path | None:
        if language not in {"english", "russian"}:
            raise ValueError("Неизвестная сторона сравнения.")
        attribute = (
            "compare_english_path" if language == "english" else "compare_russian_path"
        )
        current_value = getattr(self.settings.current, attribute)
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
        try:
            self.settings.update(**{attribute: str(path)})
        except SettingsError as error:
            self._refresh_compare_paths_ui()
            messagebox.showerror(
                "Папка сравнения не сохранена",
                str(error),
            )
            return None
        self._refresh_compare_paths_ui()
        self.compare_tab.status_var.set(f"Папка для сравнения выбрана: {path}")
        return path

    def _require_compare_folders(
        self,
    ) -> tuple[Path, Path] | None:
        settings = self.settings.current
        english = (
            Path(settings.compare_english_path)
            if settings.compare_english_path
            else None
        )
        if english is None or not english.is_dir():
            messagebox.showwarning(
                "Нужна английская папка",
                "Укажите папку с английской локализацией.",
            )
            english = self._select_compare_folder("english")
            if english is None:
                self.compare_tab.flash_path_requirement("english")
                return None

        russian_path = self.settings.current.compare_russian_path
        russian = Path(russian_path) if russian_path else None
        if russian is None or not russian.is_dir():
            messagebox.showwarning(
                "Нужна русская папка",
                "Укажите папку с русской локализацией.",
            )
            russian = self._select_compare_folder("russian")
            if russian is None:
                self.compare_tab.flash_path_requirement("russian")
                return None
        return english.resolve(), russian.resolve()

    def _capture_layout_settings(self) -> TextLayoutOptions:
        return self.layout_tab.capture_options(
            self.settings.current.layout_focus_preview_cli_path
        )

    def _store_layout_settings(
        self,
        options: TextLayoutOptions,
    ) -> None:
        self.settings.update(
            layout_focus_enabled=options.focus_enabled,
            layout_focus_mode=options.focus_mode,
            layout_focus_limit=options.focus_limit,
            layout_focus_preview_cli_path=(
                str(options.focus_preview_cli_path)
                if options.focus_preview_cli_path is not None
                else ""
            ),
            layout_focus_preview_priority=(options.focus_preview_priority),
            layout_events_enabled=options.events_enabled,
            layout_event_limit=options.event_limit,
            layout_welcome_enabled=options.welcome_enabled,
            layout_welcome_limit=options.welcome_limit,
            layout_title_newline_enabled=(
                options.title_newline_enabled
            ),
        )

    def _restore_layout_variables(self) -> None:
        settings = self.settings.current
        self.layout_tab.restore_options(
            TextLayoutOptions(
                focus_enabled=settings.layout_focus_enabled,
                focus_mode=settings.layout_focus_mode,
                focus_limit=settings.layout_focus_limit,
                focus_preview_cli_path=(
                    Path(settings.layout_focus_preview_cli_path)
                    if settings.layout_focus_preview_cli_path
                    else None
                ),
                focus_preview_priority=settings.layout_focus_preview_priority,
                events_enabled=settings.layout_events_enabled,
                event_limit=settings.layout_event_limit,
                welcome_enabled=settings.layout_welcome_enabled,
                welcome_limit=settings.layout_welcome_limit,
                title_newline_enabled=(
                    settings.layout_title_newline_enabled
                ),
            )
        )

    def _layout_controls_changed(
        self,
        _event: object | None = None,
    ) -> str:
        try:
            self._store_layout_settings(self._capture_layout_settings())
        except (ValueError, SettingsError) as error:
            self._restore_layout_variables()
            self._refresh_focus_preview_ui()
            self._refresh_layout_controls()
            messagebox.showerror("Настройки не сохранены", str(error))
            return "break"

        self._refresh_layout_controls()
        self._refresh_focus_preview_ui()
        self.layout_tab.set_status("Настройки проверки текстов сохранены.")
        return "break"

    def _refresh_layout_controls(self) -> None:
        if hasattr(self, "layout_tab"):
            self.layout_tab.set_busy(self.busy)

    def _refresh_compare_controls(self) -> None:
        if hasattr(self, "compare_tab"):
            self.compare_tab.set_busy(self.busy)

    def _refresh_context_mod_ui(self) -> None:
        context_mod_path = self.settings.current.context_mod_path
        if not context_mod_path:
            self.check_tab.set_context_status(
                "не указана — контекстный режим заблокирован",
                False,
            )
            if hasattr(self, "layout_tab"):
                self.layout_tab.set_context_status(
                    "не указана — проверка текстов заблокирована",
                    False,
                )
            return
        path = Path(context_mod_path)
        if not path.is_dir() or not is_context_root(path):
            message = f"путь недоступен или не является папкой мода: {path}"
            self.check_tab.set_context_status(message, False)
            if hasattr(self, "layout_tab"):
                self.layout_tab.set_context_status(message, False)
            return
        message = f"{mod_display_name(path)} — {path}"
        self.check_tab.set_context_status(message, True)
        if hasattr(self, "layout_tab"):
            self.layout_tab.set_context_status(message, True)

    def _select_context_mod(
        self,
        initial_dir: Path | None = None,
    ) -> Path | None:
        context_mod_path = self.settings.current.context_mod_path
        current = Path(context_mod_path) if context_mod_path else None
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

        try:
            self.settings.update(context_mod_path=str(path))
        except SettingsError as error:
            self._refresh_context_mod_ui()
            messagebox.showerror(
                "Папка мода не сохранена",
                str(error),
            )
            return None

        self._refresh_context_mod_ui()
        self.check_tab.set_status(f"Контекстный мод: {mod_display_name(path)} — {path}")
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
            context_mod_path = self.settings.current.context_mod_path
            configured = Path(context_mod_path) if context_mod_path else None
            if (
                configured is None
                or not configured.is_dir()
                or not is_context_root(configured)
            ):
                messagebox.showwarning(
                    "Нужно указать папку мода",
                    (f"{purpose} нельзя запустить без корневой папки мода."),
                )
                configured = self._select_context_mod()
                if configured is None:
                    if purpose == "Проверку текстов":
                        self.layout_tab.flash_context_requirement()
                    else:
                        self.check_tab.flash_context_requirement()
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
                    if purpose == "Проверку текстов":
                        self.layout_tab.flash_context_requirement()
                    else:
                        self.check_tab.flash_context_requirement()
                    return None
                continue
            return configured

    def _resolve_hoi4_install(self) -> Path | None:
        install_path = self.settings.current.hoi4_install_path
        game_root = find_hoi4_install(install_path)
        if game_root is None:
            return None
        if str(game_root) == install_path:
            return game_root

        try:
            self.settings.update(hoi4_install_path=str(game_root))
        except SettingsError as error:
            messagebox.showwarning(
                "Путь к Hearts of Iron IV не сохранён",
                str(error),
            )
        return game_root

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        self.check_tab.set_busy(busy)
        self._refresh_layout_controls()
        self._refresh_compare_controls()
        self._refresh_export_controls()

    def _refresh_export_controls(self) -> None:
        self.check_tab.refresh_export_control()
        if hasattr(self, "compare_tab"):
            self.compare_tab.refresh_export_control()
        if hasattr(self, "layout_tab"):
            self.layout_tab.refresh_export_control()

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
        excluded_english = self.compare_tab.excluded_files("english")
        excluded_russian = self.compare_tab.excluded_files("russian")

        def work(reporter: TaskReporter) -> LocalisationComparisonResult:
            return self.localisation_comparator.scan(
                english_root,
                russian_root,
                progress=reporter.progress,
                excluded_english_files=excluded_english,
                excluded_russian_files=excluded_russian,
            )

        if self.tasks.start("comparison", work):
            self._set_busy(True)

    def _start_scan(self, target: Path) -> None:
        if self.tasks.is_running:
            return

        glyph_mode = self.check_tab.glyph_mode()
        context_mod_root: Path | None = None
        context_game_root: Path | None = None
        if glyph_mode == "contextual":
            context_mod_root = self._require_context_mod(target)
            if context_mod_root is None:
                self.check_tab.set_status(
                    "Контекстная проверка отменена: папка мода не указана."
                )
                return
            context_game_root = self._resolve_hoi4_install()

        excluded_characters = self.exceptions.characters
        settings = self.settings.current
        show_unknown_context_warnings = settings.show_unknown_context_warnings
        check_russian_straight_quotes = settings.check_russian_straight_quotes
        if glyph_mode == "contextual":
            game_note = (
                f"; HOI4: {context_game_root}"
                if context_game_root is not None
                else "; стандартный интерфейс HOI4 не найден"
            )
            scan_status = f"Контекст: {context_mod_root}{game_note}"
        else:
            scan_status = "Подготовка проверки…"
        self.check_tab.prepare_scan(target, scan_status)

        def work(reporter: TaskReporter) -> tuple[ScanResult, GlyphMode]:
            result = self.checker.scan(
                target,
                progress=reporter.progress,
                glyph_mode=glyph_mode,
                excluded_characters=excluded_characters,
                context_mod_root=context_mod_root,
                context_game_root=context_game_root,
                show_unknown_context_warnings=(show_unknown_context_warnings),
                check_russian_straight_quotes=(check_russian_straight_quotes),
            )
            return result, glyph_mode

        if self.tasks.start("localisation", work):
            self._set_busy(True)

    def _require_layout_sources(self) -> tuple[Path, Path] | None:
        settings = self.settings.current
        raw_paths = {
            "russian": settings.layout_russian_path,
            "english": settings.layout_english_path,
        }
        resolved: dict[ComparisonLanguage, Path] = {}
        missing: list[ComparisonLanguage] = []
        for language in ("russian", "english"):
            raw_path = raw_paths[language]
            path = Path(raw_path) if raw_path else None
            if path is None or not (
                path.is_dir()
                or (
                    path.is_file()
                    and path.suffix.casefold() == ".yml"
                )
            ):
                missing.append(language)
                continue
            resolved[language] = path.resolve()
        if missing:
            labels = {
                "russian": "русский",
                "english": "английский",
            }
            required = " и ".join(labels[item] for item in missing)
            messagebox.showwarning(
                "Не выбраны источники локализации",
                f"Укажите {required} источник перед запуском проверки.",
            )
            for language in missing:
                self.layout_tab.flash_source_requirement(language)
            return None

        russian = resolved["russian"]
        english = resolved["english"]
        if russian.is_file() != english.is_file():
            messagebox.showwarning(
                "Источники разного типа",
                "Выберите либо два .yml-файла, либо две папки.",
            )
            self.layout_tab.show_source_type_mismatch()
            return None
        return russian, english

    def _start_layout_scan(self) -> None:
        if self.tasks.is_running:
            return

        sources = self._require_layout_sources()
        if sources is None:
            self.layout_tab.set_status(
                "Проверка заблокирована: нужны русский и английский источники."
            )
            return
        russian_target, english_target = sources

        try:
            options = self._capture_layout_settings()
            if options.focus_enabled and options.focus_mode == "exact":
                preview_cli = self._require_focus_preview_cli()
                if preview_cli is None:
                    self.layout_tab.set_status(
                        "Точная проверка отменена: CLI не указан."
                    )
                    return
                options = replace(
                    options,
                    focus_preview_cli_path=preview_cli,
                )
            options.validate()
            self._store_layout_settings(options)
        except (ValueError, SettingsError) as error:
            self._restore_layout_variables()
            self._refresh_focus_preview_ui()
            self._refresh_layout_controls()
            messagebox.showerror(
                "Проверка не запущена",
                str(error),
            )
            return

        context_mod_root = self._require_context_mod(
            russian_target,
            purpose="Проверку текстов",
        )
        if context_mod_root is None:
            self.layout_tab.set_status("Проверка отменена: папка мода не указана.")
            return
        context_game_root = self._resolve_hoi4_install()

        game_note = (
            f"; HOI4: {context_game_root}"
            if context_game_root is not None
            else "; стандартная HOI4 не найдена"
        )
        self.layout_tab.prepare_scan(
            russian_target,
            english_target,
            f"Контекст: {context_mod_root}{game_note}",
        )

        def work(reporter: TaskReporter) -> TextLayoutResult:
            return self.text_layout_checker.scan(
                target=russian_target,
                english_target=english_target,
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
            self.check_tab.update_progress(
                event.current,
                event.total,
                event.path,
            )
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
            self.check_tab.show_result(result, glyph_mode)
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
            self.check_tab.show_failure()
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
        else:
            self.editor.handle_notice(event)

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
        return self.editor.open_comparison(
            self.compare_tab.selected_issue(),
            languages,
            self.compare_tab.status_var,
        )

    def _open_layout_selected_languages(
        self,
        languages: tuple[ComparisonLanguage, ...],
    ) -> str:
        return self.editor.open_comparison(
            self.layout_tab.selected_issue(),
            languages,
            self.layout_tab.current_file_var,
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

        initial_directory = Path(self.settings.current.export_directory)
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
            str(table.heading(column, "text")).replace(" ↕", "") for column in columns
        )
        rows = (tuple(table.item(item, "values")) for item in items)
        try:
            row_count = export_csv(path, headers, rows)
        except (OSError, UnicodeError) as error:
            messagebox.showerror(
                "Не удалось выгрузить результаты",
                f"Файл не сохранён:\n{path}\n\n{error}",
            )
            return

        try:
            self.settings.update(export_directory=str(path.parent))
        except SettingsError as error:
            messagebox.showwarning(
                "Папка выгрузки не запомнена",
                f"CSV сохранён, но настройку сохранить не удалось:\n{error}",
            )
        status_var.set(f"Выгружено строк: {row_count}; файл: {path}")

    def _unknown_context_visibility_changed(self) -> None:
        previous = self.settings.current.show_unknown_context_warnings
        enabled = self.check_tab.show_unknown_context_var.get()
        try:
            self.settings.update(show_unknown_context_warnings=enabled)
        except SettingsError as error:
            self.check_tab.show_unknown_context_var.set(previous)
            messagebox.showerror(
                "Настройка контекстных предупреждений не сохранена",
                str(error),
            )
            return
        state = (
            "будут показаны отдельным предупреждением"
            if enabled
            else "будут скрыты"
        )
        self.check_tab.set_status(f"Ключи с неопределённым контекстом {state}.")

    def _russian_straight_quotes_changed(self) -> None:
        previous = self.settings.current.check_russian_straight_quotes
        enabled = self.check_tab.russian_straight_quotes_var.get()
        try:
            self.settings.update(check_russian_straight_quotes=enabled)
        except SettingsError as error:
            self.check_tab.russian_straight_quotes_var.set(previous)
            messagebox.showerror(
                "Настройка проверки кавычек не сохранена",
                str(error),
            )
            return
        state = "включена" if enabled else "выключена"
        self.check_tab.set_status(
            f"Проверка прямых кавычек в русской локализации {state}."
        )

    def _notepad_window_mode_changed(self) -> None:
        previous = self.settings.current.notepad_plus_plus_fullscreen
        fullscreen = self.check_tab.notepad_fullscreen_var.get()
        try:
            self.settings.update(notepad_plus_plus_fullscreen=fullscreen)
        except SettingsError as error:
            self.check_tab.notepad_fullscreen_var.set(previous)
            messagebox.showerror(
                "Режим окна Notepad++ не сохранён",
                str(error),
            )
            return
        mode = (
            "в полноэкранном режиме"
            if fullscreen
            else "в обычном окне"
        )
        self.check_tab.set_status(f"Notepad++ будет открываться {mode}.")

    def _remember_notepad_plus_plus(self, executable: Path) -> None:
        try:
            self.settings.update(notepad_plus_plus_path=str(executable))
        except SettingsError as error:
            messagebox.showwarning(
                "Путь к Notepad++ не сохранён",
                str(error),
            )


def run_gui(app_root: Path) -> None:
    root = tk.Tk()
    try:
        ttk.Style(root).theme_use("vista")
    except tk.TclError:
        pass
    CheckerApplication(root=root, app_root=app_root)
    root.mainloop()
