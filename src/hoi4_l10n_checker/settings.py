from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


class SettingsError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class AppSettings:
    excluded_characters: frozenset[str] = frozenset()
    notepad_plus_plus_path: str = ""
    notepad_plus_plus_fullscreen: bool = False
    context_mod_path: str = ""
    hoi4_install_path: str = ""
    show_unknown_context_warnings: bool = False
    layout_focus_enabled: bool = True
    layout_focus_mode: str = "length"
    layout_focus_limit: int = 350
    layout_focus_preview_cli_path: str = ""
    layout_focus_preview_priority: str = "auto_ru"
    layout_events_enabled: bool = True
    layout_event_limit: int = 3400
    layout_welcome_enabled: bool = True
    layout_welcome_limit: int = 3400
    compare_english_path: str = ""
    compare_russian_path: str = ""


def settings_path_for(app_root: Path) -> Path:
    return app_root / "settings.json"


def load_settings(path: Path) -> AppSettings:
    if not path.is_file():
        return AppSettings()

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SettingsError(f"Не удалось прочитать настройки: {error}") from error

    raw_characters = data.get("excluded_characters")
    if not isinstance(raw_characters, list):
        raise SettingsError(
            "В настройках отсутствует список excluded_characters."
        )

    characters: set[str] = set()
    for value in raw_characters:
        if not isinstance(value, str):
            raise SettingsError(
                "Список excluded_characters содержит значение, которое не является текстом."
            )
        characters.update(value)
    raw_editor_path = data.get("notepad_plus_plus_path", "")
    if not isinstance(raw_editor_path, str):
        raise SettingsError(
            "Значение notepad_plus_plus_path в настройках не является текстом."
        )
    raw_editor_fullscreen = data.get("notepad_plus_plus_fullscreen", False)
    if not isinstance(raw_editor_fullscreen, bool):
        raise SettingsError(
            "Значение notepad_plus_plus_fullscreen в настройках "
            "не является логическим."
        )
    raw_context_mod_path = data.get("context_mod_path", "")
    if not isinstance(raw_context_mod_path, str):
        raise SettingsError(
            "Значение context_mod_path в настройках не является текстом."
        )
    raw_hoi4_install_path = data.get("hoi4_install_path", "")
    if not isinstance(raw_hoi4_install_path, str):
        raise SettingsError(
            "Значение hoi4_install_path в настройках не является текстом."
        )
    raw_show_unknown_context = data.get(
        "show_unknown_context_warnings",
        False,
    )
    if not isinstance(raw_show_unknown_context, bool):
        raise SettingsError(
            "Значение show_unknown_context_warnings в настройках "
            "не является логическим."
        )
    raw_layout_focus_enabled = data.get("layout_focus_enabled", True)
    raw_layout_focus_mode = data.get("layout_focus_mode", "length")
    raw_layout_focus_limit = data.get("layout_focus_limit", 350)
    raw_layout_focus_preview_cli_path = data.get(
        "layout_focus_preview_cli_path",
        "",
    )
    raw_layout_focus_preview_priority = data.get(
        "layout_focus_preview_priority",
        "auto_ru",
    )
    raw_layout_events_enabled = data.get("layout_events_enabled", True)
    raw_layout_event_limit = data.get("layout_event_limit", 3400)
    raw_layout_welcome_enabled = data.get("layout_welcome_enabled", True)
    raw_layout_welcome_limit = data.get("layout_welcome_limit", 3400)
    raw_compare_english_path = data.get("compare_english_path", "")
    raw_compare_russian_path = data.get("compare_russian_path", "")

    for name, value in (
        ("layout_focus_enabled", raw_layout_focus_enabled),
        ("layout_events_enabled", raw_layout_events_enabled),
        ("layout_welcome_enabled", raw_layout_welcome_enabled),
    ):
        if not isinstance(value, bool):
            raise SettingsError(
                f"Значение {name} в настройках не является логическим."
            )
    for name, value in (
        ("compare_english_path", raw_compare_english_path),
        ("compare_russian_path", raw_compare_russian_path),
    ):
        if not isinstance(value, str):
            raise SettingsError(
                f"Значение {name} в настройках не является текстом."
            )
    if (
        not isinstance(raw_layout_focus_mode, str)
        or raw_layout_focus_mode not in {"length", "newline", "exact"}
    ):
        raise SettingsError(
            "Значение layout_focus_mode должно быть length, newline "
            "или exact."
        )
    if not isinstance(raw_layout_focus_preview_cli_path, str):
        raise SettingsError(
            "Значение layout_focus_preview_cli_path не является текстом."
        )
    if (
        not isinstance(raw_layout_focus_preview_priority, str)
        or raw_layout_focus_preview_priority
        not in {"auto_ru", "auto_en", "ru", "en"}
    ):
        raise SettingsError(
            "Некорректное значение layout_focus_preview_priority."
        )
    for name, value in (
        ("layout_focus_limit", raw_layout_focus_limit),
        ("layout_event_limit", raw_layout_event_limit),
        ("layout_welcome_limit", raw_layout_welcome_limit),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise SettingsError(
                f"Значение {name} должно быть положительным целым числом."
            )
    return AppSettings(
        excluded_characters=frozenset(characters),
        notepad_plus_plus_path=raw_editor_path,
        notepad_plus_plus_fullscreen=raw_editor_fullscreen,
        context_mod_path=raw_context_mod_path,
        hoi4_install_path=raw_hoi4_install_path,
        show_unknown_context_warnings=raw_show_unknown_context,
        layout_focus_enabled=raw_layout_focus_enabled,
        layout_focus_mode=raw_layout_focus_mode,
        layout_focus_limit=raw_layout_focus_limit,
        layout_focus_preview_cli_path=(
            raw_layout_focus_preview_cli_path
        ),
        layout_focus_preview_priority=raw_layout_focus_preview_priority,
        layout_events_enabled=raw_layout_events_enabled,
        layout_event_limit=raw_layout_event_limit,
        layout_welcome_enabled=raw_layout_welcome_enabled,
        layout_welcome_limit=raw_layout_welcome_limit,
        compare_english_path=raw_compare_english_path,
        compare_russian_path=raw_compare_russian_path,
    )


def save_settings(
    path: Path,
    settings: AppSettings,
) -> None:
    normalized = sorted(
        {
            character
            for value in settings.excluded_characters
            for character in value
        },
        key=ord,
    )
    data = {
        "format_version": 1,
        "excluded_characters": normalized,
        "notepad_plus_plus_path": settings.notepad_plus_plus_path,
        "notepad_plus_plus_fullscreen": settings.notepad_plus_plus_fullscreen,
        "context_mod_path": settings.context_mod_path,
        "hoi4_install_path": settings.hoi4_install_path,
        "show_unknown_context_warnings": (
            settings.show_unknown_context_warnings
        ),
        "layout_focus_enabled": settings.layout_focus_enabled,
        "layout_focus_mode": settings.layout_focus_mode,
        "layout_focus_limit": settings.layout_focus_limit,
        "layout_focus_preview_cli_path": (
            settings.layout_focus_preview_cli_path
        ),
        "layout_focus_preview_priority": (
            settings.layout_focus_preview_priority
        ),
        "layout_events_enabled": settings.layout_events_enabled,
        "layout_event_limit": settings.layout_event_limit,
        "layout_welcome_enabled": settings.layout_welcome_enabled,
        "layout_welcome_limit": settings.layout_welcome_limit,
        "compare_english_path": settings.compare_english_path,
        "compare_russian_path": settings.compare_russian_path,
    }

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError as error:
        raise SettingsError(f"Не удалось сохранить настройки: {error}") from error


def load_excluded_characters(path: Path) -> frozenset[str]:
    return load_settings(path).excluded_characters


def save_excluded_characters(path: Path, characters: Iterable[str]) -> None:
    existing = load_settings(path)
    save_settings(
        path,
        AppSettings(
            excluded_characters=frozenset(characters),
            notepad_plus_plus_path=existing.notepad_plus_plus_path,
            notepad_plus_plus_fullscreen=existing.notepad_plus_plus_fullscreen,
            context_mod_path=existing.context_mod_path,
            hoi4_install_path=existing.hoi4_install_path,
            show_unknown_context_warnings=(
                existing.show_unknown_context_warnings
            ),
            layout_focus_enabled=existing.layout_focus_enabled,
            layout_focus_mode=existing.layout_focus_mode,
            layout_focus_limit=existing.layout_focus_limit,
            layout_focus_preview_cli_path=(
                existing.layout_focus_preview_cli_path
            ),
            layout_focus_preview_priority=(
                existing.layout_focus_preview_priority
            ),
            layout_events_enabled=existing.layout_events_enabled,
            layout_event_limit=existing.layout_event_limit,
            layout_welcome_enabled=existing.layout_welcome_enabled,
            layout_welcome_limit=existing.layout_welcome_limit,
            compare_english_path=existing.compare_english_path,
            compare_russian_path=existing.compare_russian_path,
        ),
    )
