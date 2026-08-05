from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Iterable

CURRENT_SETTINGS_FORMAT_VERSION = 2


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
    check_russian_straight_quotes: bool = True
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
    export_directory: str = ""


_DEFAULT_SETTINGS = AppSettings()
_BOOLEAN_FIELDS = (
    "notepad_plus_plus_fullscreen",
    "show_unknown_context_warnings",
    "check_russian_straight_quotes",
    "layout_focus_enabled",
    "layout_events_enabled",
    "layout_welcome_enabled",
)
_STRING_FIELDS = (
    "notepad_plus_plus_path",
    "context_mod_path",
    "hoi4_install_path",
    "layout_focus_preview_cli_path",
    "compare_english_path",
    "compare_russian_path",
    "export_directory",
)
_POSITIVE_INTEGER_FIELDS = (
    "layout_focus_limit",
    "layout_event_limit",
    "layout_welcome_limit",
)
_CHOICE_FIELDS = {
    "layout_focus_mode": frozenset({"length", "newline", "exact"}),
    "layout_focus_preview_priority": frozenset(
        {"auto_ru", "auto_en", "ru", "en"}
    ),
}


def settings_path_for(app_root: Path) -> Path:
    return app_root / "settings.json"


def _migrate_settings_data(raw_data: object) -> dict[str, object]:
    if not isinstance(raw_data, dict):
        raise SettingsError(
            "Корневое значение settings.json должно быть объектом JSON."
        )

    data = dict(raw_data)
    raw_version = data.get("format_version", 1)
    if isinstance(raw_version, bool) or not isinstance(raw_version, int):
        raise SettingsError(
            "Значение format_version должно быть целым числом."
        )
    if raw_version < 1:
        raise SettingsError(
            f"Некорректная версия формата настроек: {raw_version}."
        )
    if raw_version > CURRENT_SETTINGS_FORMAT_VERSION:
        raise SettingsError(
            "Формат settings.json новее поддерживаемого: "
            f"{raw_version} > {CURRENT_SETTINGS_FORMAT_VERSION}. "
            "Используйте более новую версию программы."
        )

    version = raw_version
    while version < CURRENT_SETTINGS_FORMAT_VERSION:
        if version == 1:
            data.pop("layout_focus_preview_policy", None)
            version = 2
            continue
        raise SettingsError(
            f"Неизвестен способ обновления формата настроек {version}."
        )

    data["format_version"] = CURRENT_SETTINGS_FORMAT_VERSION
    return data


def _read_boolean(data: dict[str, object], name: str) -> bool:
    default = getattr(_DEFAULT_SETTINGS, name)
    value = data.get(name, default)
    if not isinstance(value, bool):
        raise SettingsError(
            f"Значение {name} в настройках не является логическим."
        )
    return value


def _read_string(data: dict[str, object], name: str) -> str:
    default = getattr(_DEFAULT_SETTINGS, name)
    value = data.get(name, default)
    if not isinstance(value, str):
        raise SettingsError(
            f"Значение {name} в настройках не является текстом."
        )
    return value


def _read_positive_integer(data: dict[str, object], name: str) -> int:
    default = getattr(_DEFAULT_SETTINGS, name)
    value = data.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise SettingsError(
            f"Значение {name} должно быть положительным целым числом."
        )
    return value


def _read_choice(
    data: dict[str, object],
    name: str,
    allowed: frozenset[str],
) -> str:
    default = getattr(_DEFAULT_SETTINGS, name)
    value = data.get(name, default)
    if not isinstance(value, str) or value not in allowed:
        expected = ", ".join(sorted(allowed))
        raise SettingsError(
            f"Значение {name} должно быть одним из: {expected}."
        )
    return value


def _settings_from_data(data: dict[str, object]) -> AppSettings:
    raw_characters = data.get("excluded_characters")
    if not isinstance(raw_characters, list):
        raise SettingsError(
            "В настройках отсутствует список excluded_characters."
        )

    characters: set[str] = set()
    for value in raw_characters:
        if not isinstance(value, str):
            raise SettingsError(
                "Список excluded_characters содержит значение, "
                "которое не является текстом."
            )
        characters.update(value)

    values: dict[str, object] = {}
    for name in _BOOLEAN_FIELDS:
        values[name] = _read_boolean(data, name)
    for name in _STRING_FIELDS:
        values[name] = _read_string(data, name)
    for name in _POSITIVE_INTEGER_FIELDS:
        values[name] = _read_positive_integer(data, name)
    for name, allowed in _CHOICE_FIELDS.items():
        values[name] = _read_choice(data, name, allowed)

    return AppSettings(
        excluded_characters=frozenset(characters),
        **values,
    )


def load_settings(path: Path) -> AppSettings:
    if not path.is_file():
        return AppSettings()

    try:
        raw_data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SettingsError(
            f"Не удалось прочитать настройки: {error}"
        ) from error

    data = _migrate_settings_data(raw_data)
    return _settings_from_data(data)


def _settings_data(settings: AppSettings) -> dict[str, object]:
    data: dict[str, object] = {
        "format_version": CURRENT_SETTINGS_FORMAT_VERSION,
        **asdict(settings),
    }
    data["excluded_characters"] = sorted(
        {
            character
            for value in settings.excluded_characters
            for character in value
        },
        key=ord,
    )
    return data


def _atomic_write_text(path: Path, text: str) -> None:
    temporary_path: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as output:
            temporary_path = Path(output.name)
            output.write(text)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass


def save_settings(
    path: Path,
    settings: AppSettings,
) -> None:
    if path.exists():
        if not path.is_file():
            raise SettingsError(
                f"Путь настроек не является файлом: {path}"
            )
        load_settings(path)

    text = (
        json.dumps(
            _settings_data(settings),
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    try:
        _atomic_write_text(path, text)
    except OSError as error:
        raise SettingsError(
            f"Не удалось сохранить настройки: {error}"
        ) from error


class SettingsStore:
    """Keeps one settings snapshot and commits replacements atomically."""

    def __init__(self, path: Path, current: AppSettings) -> None:
        self.path = path
        self._current = current

    @classmethod
    def load(cls, path: Path) -> SettingsStore:
        return cls(path, load_settings(path))

    @property
    def current(self) -> AppSettings:
        return self._current

    def update(self, **changes: object) -> AppSettings:
        updated = replace(self._current, **changes)
        save_settings(self.path, updated)
        self._current = updated
        return updated


def load_excluded_characters(path: Path) -> frozenset[str]:
    return load_settings(path).excluded_characters


def save_excluded_characters(path: Path, characters: Iterable[str]) -> None:
    existing = load_settings(path)
    save_settings(
        path,
        replace(
            existing,
            excluded_characters=frozenset(characters),
        ),
    )
