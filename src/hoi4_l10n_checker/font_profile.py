from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal


_CHAR_LINE = re.compile(rb"^char\s+id=(\d+)(?:\s|$)")
_ANSI_CHARSET = re.compile(rb'\bcharset="?ANSI"?(?:\s|$)', re.IGNORECASE)
_UNICODE_ENABLED = re.compile(rb"\bunicode=1(?:\s|$)")
CoverageMode = Literal["soft", "strict"]
_COVERAGE_MODES = frozenset({"soft", "strict"})


class FontProfileError(RuntimeError):
    pass


class FontProfile:
    def __init__(
        self,
        profile_path: Path,
        fonts_root: Path,
        data: dict[str, object],
    ) -> None:
        self.profile_path = profile_path
        self.fonts_root = fonts_root
        self.data = data
        self.default_language = str(data.get("default_language", "l_english"))
        self._font_cache: dict[Path, frozenset[int]] = {}
        self._coverage_cache: dict[
            tuple[str, CoverageMode],
            frozenset[int] | None,
        ] = {}
        self._family_coverage_cache: dict[
            tuple[str, str],
            frozenset[int] | None,
        ] = {}
        self._family_count_cache: dict[str, int] = {}
        self._runtime_errors: list[str] = []

    @classmethod
    def load(cls, app_root: Path) -> "FontProfile":
        profile_path = app_root / "font_profile.json"
        fonts_root = app_root / "fonts"
        if not profile_path.is_file():
            raise FontProfileError(f"Не найден файл профиля: {profile_path}")
        if not fonts_root.is_dir():
            raise FontProfileError(f"Не найдена папка шрифтов: {fonts_root}")

        try:
            data = json.loads(profile_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise FontProfileError(f"Не удалось прочитать профиль шрифтов: {error}") from error

        if not isinstance(data.get("languages"), dict):
            raise FontProfileError("В профиле отсутствует раздел languages.")
        return cls(profile_path=profile_path, fonts_root=fonts_root, data=data)

    @property
    def runtime_errors(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(self._runtime_errors))

    @property
    def available_languages(self) -> tuple[str, ...]:
        languages = self.data.get("languages", {})
        if not isinstance(languages, dict):
            return ()
        return tuple(sorted(str(language) for language in languages))

    def _language_data(self, language: str) -> tuple[str, dict[str, object] | None]:
        languages = self.data.get("languages", {})
        if not isinstance(languages, dict):
            return language, None

        selected = language if language in languages else self.default_language
        value = languages.get(selected)
        return selected, value if isinstance(value, dict) else None

    def _read_font(self, relative_path: str) -> frozenset[int] | None:
        path = (self.fonts_root / relative_path).resolve()
        try:
            path.relative_to(self.fonts_root.resolve())
        except ValueError:
            self._runtime_errors.append(
                f"Профиль ссылается на файл вне папки fonts: {relative_path}"
            )
            return None

        if path in self._font_cache:
            return self._font_cache[path]
        if not path.is_file():
            self._runtime_errors.append(f"Не найден шрифт: {relative_path}")
            return None

        glyphs: set[int] = set()
        is_ansi = False
        try:
            with path.open("rb") as font_file:
                for line in font_file:
                    if line.startswith(b"info "):
                        is_ansi = (
                            _ANSI_CHARSET.search(line) is not None
                            and _UNICODE_ENABLED.search(line) is None
                        )
                        continue
                    match = _CHAR_LINE.match(line)
                    if match:
                        font_id = int(match.group(1))
                        if is_ansi and 0 <= font_id <= 255:
                            try:
                                character = bytes([font_id]).decode("cp1252")
                            except UnicodeDecodeError:
                                continue
                            glyphs.add(ord(character))
                        else:
                            glyphs.add(font_id)
        except OSError as error:
            self._runtime_errors.append(f"Не удалось прочитать {relative_path}: {error}")
            return None

        if not glyphs:
            self._runtime_errors.append(
                f"В шрифте не найдено ни одной строки char id: {relative_path}"
            )
            return None

        result = frozenset(glyphs)
        self._font_cache[path] = result
        return result

    def coverage_for(
        self,
        language: str,
        mode: CoverageMode = "soft",
    ) -> frozenset[int] | None:
        if mode not in _COVERAGE_MODES:
            raise ValueError(f"Неизвестный режим проверки шрифтов: {mode}")

        selected, language_data = self._language_data(language)
        cache_key = (selected, mode)
        if cache_key in self._coverage_cache:
            return self._coverage_cache[cache_key]
        if language_data is None:
            self._coverage_cache[cache_key] = None
            self._family_count_cache[selected] = 0
            return None

        raw_families = language_data.get("families", {})
        if not isinstance(raw_families, dict) or not raw_families:
            self._runtime_errors.append(
                f"Для языка {selected} не заданы семейства интерфейсных шрифтов."
            )
            self._coverage_cache[cache_key] = None
            self._family_count_cache[selected] = 0
            return None

        family_sets: list[set[int]] = []
        profile_is_complete = True
        raw_context_only = self.data.get("context_only_families", [])
        context_only = (
            {
                str(family_name).casefold()
                for family_name in raw_context_only
            }
            if isinstance(raw_context_only, list)
            else set()
        )
        for family_name, raw_paths in raw_families.items():
            if str(family_name).casefold() in context_only:
                continue
            if not isinstance(raw_paths, list) or not raw_paths:
                self._runtime_errors.append(
                    f"Для семейства {family_name} ({selected}) не указаны файлы."
                )
                profile_is_complete = False
                continue

            family_union: set[int] = set()
            for raw_path in raw_paths:
                glyphs = self._read_font(str(raw_path))
                if glyphs is None:
                    profile_is_complete = False
                else:
                    family_union.update(glyphs)
            if family_union:
                family_sets.append(family_union)

        self._family_count_cache[selected] = len(family_sets)
        if not profile_is_complete or not family_sets:
            self._coverage_cache[cache_key] = None
            return None

        if mode == "soft":
            safe: set[int] = set()
            for family in family_sets:
                safe.update(family)
        else:
            family_sets.sort(key=len)
            safe = family_sets[0].copy()
            for family in family_sets[1:]:
                safe.intersection_update(family)

        result = frozenset(safe)
        self._coverage_cache[cache_key] = result
        return result

    def family_count_for(self, language: str) -> int:
        selected, _ = self._language_data(language)
        if selected not in self._family_count_cache:
            self.coverage_for(selected)
        return self._family_count_cache.get(selected, 0)

    def coverage_for_family(
        self,
        language: str,
        family_name: str,
    ) -> frozenset[int] | None:
        selected, language_data = self._language_data(language)
        normalized_name = family_name.casefold()
        cache_key = (selected, normalized_name)
        if cache_key in self._family_coverage_cache:
            return self._family_coverage_cache[cache_key]
        if language_data is None:
            self._family_coverage_cache[cache_key] = None
            return None

        raw_families = language_data.get("families", {})
        if not isinstance(raw_families, dict):
            self._family_coverage_cache[cache_key] = None
            return None

        raw_paths: object | None = None
        matched_name = family_name
        for candidate_name, candidate_paths in raw_families.items():
            if str(candidate_name).casefold() == normalized_name:
                matched_name = str(candidate_name)
                raw_paths = candidate_paths
                break
        if not isinstance(raw_paths, list) or not raw_paths:
            self._family_coverage_cache[cache_key] = None
            return None

        coverage: set[int] = set()
        complete = True
        for raw_path in raw_paths:
            glyphs = self._read_font(str(raw_path))
            if glyphs is None:
                complete = False
            else:
                coverage.update(glyphs)
        if not complete or not coverage:
            self._runtime_errors.append(
                f"Не удалось получить покрытие семейства "
                f"{matched_name} ({selected})."
            )
            self._family_coverage_cache[cache_key] = None
            return None

        result = frozenset(coverage)
        self._family_coverage_cache[cache_key] = result
        return result
