from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Literal

from .models import Diagnostic, LocalisationEntry
from .parser import parse_localisation_file

ComparisonCategory = Literal[
    "missing_russian",
    "missing_english",
    "duplicate_english",
    "duplicate_russian",
    "parse_error",
]
ComparisonProgress = Callable[[int, int, Path], None]
ComparisonLanguage = Literal["english", "russian"]

_BLOCKING_PARSE_CODES = frozenset(
    {
        "FILE_READ_ERROR",
        "INVALID_UTF8",
        "MALFORMED_ENTRY",
        "INVALID_KEY",
        "MISSING_OPENING_QUOTE",
        "UNCLOSED_QUOTE",
        "MISSING_LANGUAGE_HEADER",
        "NO_LANGUAGE_HEADER",
    }
)


@dataclass(frozen=True, slots=True)
class ComparisonIssue:
    category: ComparisonCategory
    code: str
    label: str
    key: str
    language: str
    path: Path
    line: int
    column: int
    raw_value: str
    message: str
    severity: Literal["warning", "error"] = "warning"
    english_path: Path | None = None
    english_line: int = 0
    english_column: int = 0
    russian_path: Path | None = None
    russian_line: int = 0
    russian_column: int = 0

    def sort_key(self) -> tuple[str, str, str, int, int]:
        category_order = {
            "missing_russian": "1",
            "missing_english": "2",
            "duplicate_english": "3",
            "duplicate_russian": "4",
            "parse_error": "5",
        }
        return (
            category_order[self.category],
            self.key.casefold(),
            str(self.path).casefold(),
            self.line,
            self.column,
        )

    def as_diagnostic(self) -> Diagnostic:
        return Diagnostic(
            severity=self.severity,
            code=self.code,
            path=self.path,
            line=self.line,
            column=self.column,
            message=self.message,
            key=self.key,
        )

    def diagnostic_for(
        self,
        language: ComparisonLanguage,
    ) -> Diagnostic | None:
        if language == "english":
            path = self.english_path
            line = self.english_line
            column = self.english_column
        else:
            path = self.russian_path
            line = self.russian_line
            column = self.russian_column
        if path is None:
            return None
        return Diagnostic(
            severity=self.severity,
            code=self.code,
            path=path,
            line=max(line, 1),
            column=max(column, 1),
            message=self.message,
            key=self.key,
        )


@dataclass(slots=True)
class LocalisationComparisonResult:
    english_root: Path
    russian_root: Path
    files_checked: int
    english_files: int
    russian_files: int
    english_keys: int
    russian_keys: int
    common_keys: int
    missing_russian: int
    missing_english: int
    duplicate_english: int
    duplicate_russian: int
    parse_errors: int
    issues: list[ComparisonIssue]

    @property
    def difference_count(self) -> int:
        return self.missing_russian + self.missing_english

    @property
    def duplicate_count(self) -> int:
        return self.duplicate_english + self.duplicate_russian


def _collect_files(localisation_root: Path) -> list[Path]:
    return sorted(
        (
            path
            for path in localisation_root.rglob("*")
            if path.is_file() and path.suffix.casefold() == ".yml"
        ),
        key=lambda path: str(path).casefold(),
    )


def _relative_key(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix().casefold()


def _neutral_file_name(path: Path) -> str:
    return (
        path.name.casefold()
        .replace("_l_english", "_l_language")
        .replace("_l_russian", "_l_language")
    )


def _neutral_relative_key(path: Path, root: Path) -> str:
    relative = path.relative_to(root)
    return (
        relative.with_name(_neutral_file_name(relative))
        .as_posix()
        .casefold()
    )


def _language_file_name(path: Path, target_language: str) -> str:
    name = path.name
    lowered = name.casefold()
    for marker in ("_l_english", "_l_russian"):
        index = lowered.find(marker)
        if index >= 0:
            return (
                name[:index]
                + f"_l_{target_language}"
                + name[index + len(marker):]
            )
    return name


def _counterpart_files(
    source_files: list[Path],
    source_root: Path,
    target_files: list[Path],
    target_root: Path,
    target_language: str,
) -> dict[Path, Path]:
    target_by_relative = {
        _relative_key(path, target_root): path
        for path in target_files
    }
    target_by_neutral_relative: dict[str, list[Path]] = defaultdict(list)
    target_by_neutral_name: dict[str, list[Path]] = defaultdict(list)
    for path in target_files:
        target_by_neutral_relative[
            _neutral_relative_key(path, target_root)
        ].append(path)
        target_by_neutral_name[_neutral_file_name(path)].append(path)

    counterparts: dict[Path, Path] = {}
    for source in source_files:
        relative = source.relative_to(source_root)
        candidate_keys = (
            relative.as_posix().casefold(),
            relative.with_name(
                _language_file_name(relative, target_language)
            ).as_posix().casefold(),
        )
        counterpart = next(
            (
                target_by_relative[key]
                for key in candidate_keys
                if key in target_by_relative
            ),
            None,
        )
        if counterpart is None:
            neutral_relative = _neutral_relative_key(
                source,
                source_root,
            )
            relative_matches = target_by_neutral_relative.get(
                neutral_relative,
                [],
            )
            if len(relative_matches) == 1:
                counterpart = relative_matches[0]
        if counterpart is None:
            name_matches = target_by_neutral_name.get(
                _neutral_file_name(source),
                [],
            )
            if len(name_matches) == 1:
                counterpart = name_matches[0]
        if counterpart is not None:
            counterparts[source] = counterpart
    return counterparts


def _enrich_issue_locations(
    issue: ComparisonIssue,
    english: dict[str, list[LocalisationEntry]],
    russian: dict[str, list[LocalisationEntry]],
    english_to_russian: dict[Path, Path],
    russian_to_english: dict[Path, Path],
) -> ComparisonIssue:
    english_occurrences = english.get(issue.key)
    russian_occurrences = russian.get(issue.key)
    english_entry = (
        english_occurrences[0]
        if english_occurrences
        else None
    )
    russian_entry = (
        russian_occurrences[0]
        if russian_occurrences
        else None
    )

    english_path = (
        english_entry.path
        if english_entry is not None
        else None
    )
    english_line = english_entry.line if english_entry is not None else 0
    english_column = (
        english_entry.value_column
        if english_entry is not None
        else 0
    )
    russian_path = (
        russian_entry.path
        if russian_entry is not None
        else None
    )
    russian_line = russian_entry.line if russian_entry is not None else 0
    russian_column = (
        russian_entry.value_column
        if russian_entry is not None
        else 0
    )

    primary_is_english = (
        issue.category in {"missing_russian", "duplicate_english"}
        or (
            issue.category == "parse_error"
            and issue.language == _language_label("l_english")
        )
    )
    primary_is_russian = (
        issue.category in {"missing_english", "duplicate_russian"}
        or (
            issue.category == "parse_error"
            and issue.language == _language_label("l_russian")
        )
    )
    if primary_is_english:
        english_path = issue.path
        english_line = issue.line
        english_column = issue.column
    if primary_is_russian:
        russian_path = issue.path
        russian_line = issue.line
        russian_column = issue.column

    if english_path is not None and russian_path is None:
        russian_path = english_to_russian.get(english_path)
        if russian_path is not None:
            russian_line = max(english_line, 1)
            russian_column = 1
    if russian_path is not None and english_path is None:
        english_path = russian_to_english.get(russian_path)
        if english_path is not None:
            english_line = max(russian_line, 1)
            english_column = 1

    return replace(
        issue,
        english_path=english_path,
        english_line=english_line,
        english_column=english_column,
        russian_path=russian_path,
        russian_line=russian_line,
        russian_column=russian_column,
    )


def _language_label(language: str) -> str:
    return {
        "l_english": "Английский",
        "l_russian": "Русский",
    }.get(language, "Не определён")


def _parse_issue(
    diagnostic: Diagnostic,
    language: str,
) -> ComparisonIssue:
    return ComparisonIssue(
        category="parse_error",
        code=diagnostic.code,
        label="Ошибка разбора файла",
        key=diagnostic.key,
        language=_language_label(language),
        path=diagnostic.path,
        line=diagnostic.line,
        column=diagnostic.column,
        raw_value="",
        message=(
            "Файл нельзя считать полностью проверенным: "
            f"{diagnostic.message}"
        ),
        severity="error",
    )


def _missing_issue(
    entry: LocalisationEntry,
    *,
    missing_language: str,
) -> ComparisonIssue:
    missing_russian = missing_language == "l_russian"
    return ComparisonIssue(
        category=(
            "missing_russian"
            if missing_russian
            else "missing_english"
        ),
        code=(
            "MISSING_IN_RUSSIAN"
            if missing_russian
            else "MISSING_IN_ENGLISH"
        ),
        label=(
            "Нет в русской"
            if missing_russian
            else "Нет в английской"
        ),
        key=entry.key,
        language=_language_label(entry.language),
        path=entry.path,
        line=entry.line,
        column=entry.value_column,
        raw_value=entry.raw_value,
        message=(
            f"Ключ «{entry.key}» есть в "
            f"{_language_label(entry.language).casefold()} локализации, "
            f"но отсутствует в "
            f"{_language_label(missing_language).casefold()}."
        ),
    )


def _duplicate_issue(
    entry: LocalisationEntry,
    original: LocalisationEntry,
) -> ComparisonIssue:
    english = entry.language == "l_english"
    return ComparisonIssue(
        category=(
            "duplicate_english"
            if english
            else "duplicate_russian"
        ),
        code=(
            "DUPLICATE_ENGLISH_KEY"
            if english
            else "DUPLICATE_RUSSIAN_KEY"
        ),
        label=(
            "Дубль в английской"
            if english
            else "Дубль в русской"
        ),
        key=entry.key,
        language=_language_label(entry.language),
        path=entry.path,
        line=entry.line,
        column=entry.value_column,
        raw_value=entry.raw_value,
        message=(
            f"Ключ «{entry.key}» повторно объявлен в "
            f"{_language_label(entry.language).casefold()} локализации. "
            f"Первое объявление: {original.path}:{original.line}."
        ),
    )


class LocalisationComparator:
    def scan(
        self,
        english_root: Path,
        russian_root: Path,
        progress: ComparisonProgress | None = None,
    ) -> LocalisationComparisonResult:
        resolved_english = english_root.resolve()
        resolved_russian = russian_root.resolve()
        if not resolved_english.is_dir():
            raise ValueError(
                "Папка английской локализации недоступна: "
                f"{resolved_english}"
            )
        if not resolved_russian.is_dir():
            raise ValueError(
                "Папка русской локализации недоступна: "
                f"{resolved_russian}"
            )

        english_files = _collect_files(resolved_english)
        russian_files = _collect_files(resolved_russian)
        files_with_languages = [
            *(
                (path, "l_english")
                for path in english_files
            ),
            *(
                (path, "l_russian")
                for path in russian_files
            ),
        ]
        entries_by_language: dict[
            str,
            dict[str, list[LocalisationEntry]],
        ] = {
            "l_english": defaultdict(list),
            "l_russian": defaultdict(list),
        }
        parse_issues: list[ComparisonIssue] = []

        for index, (path, expected_language) in enumerate(
            files_with_languages,
            start=1,
        ):
            if progress is not None:
                progress(index, len(files_with_languages), path)
            parsed = parse_localisation_file(path)

            invalid_key_lines = {
                diagnostic.line
                for diagnostic in parsed.diagnostics
                if diagnostic.code == "INVALID_KEY"
            }
            for entry in parsed.entries:
                if (
                    entry.language == expected_language
                    and entry.line not in invalid_key_lines
                ):
                    entries_by_language[entry.language][entry.key].append(
                        entry
                    )

            if (
                expected_language in parsed.languages
                or not parsed.languages
            ):
                for diagnostic in parsed.diagnostics:
                    if diagnostic.code in _BLOCKING_PARSE_CODES:
                        parse_issues.append(
                            _parse_issue(
                                diagnostic,
                                expected_language,
                            )
                        )

        english = entries_by_language["l_english"]
        russian = entries_by_language["l_russian"]
        english_keys = set(english)
        russian_keys = set(russian)

        issues: list[ComparisonIssue] = []
        for key in sorted(
            english_keys - russian_keys,
            key=str.casefold,
        ):
            issues.append(
                _missing_issue(
                    english[key][0],
                    missing_language="l_russian",
                )
            )
        for key in sorted(
            russian_keys - english_keys,
            key=str.casefold,
        ):
            issues.append(
                _missing_issue(
                    russian[key][0],
                    missing_language="l_english",
                )
            )

        duplicate_english = 0
        duplicate_russian = 0
        for language, entries_by_key in entries_by_language.items():
            for occurrences in entries_by_key.values():
                original = occurrences[0]
                for duplicate in occurrences[1:]:
                    issues.append(
                        _duplicate_issue(duplicate, original)
                    )
                    if language == "l_english":
                        duplicate_english += 1
                    else:
                        duplicate_russian += 1

        unique_parse_issues = {
            (
                issue.path,
                issue.line,
                issue.column,
                issue.code,
            ): issue
            for issue in parse_issues
        }
        issues.extend(unique_parse_issues.values())
        english_to_russian = _counterpart_files(
            english_files,
            resolved_english,
            russian_files,
            resolved_russian,
            "russian",
        )
        russian_to_english = _counterpart_files(
            russian_files,
            resolved_russian,
            english_files,
            resolved_english,
            "english",
        )
        issues = [
            _enrich_issue_locations(
                issue,
                english,
                russian,
                english_to_russian,
                russian_to_english,
            )
            for issue in issues
        ]
        issues.sort(key=ComparisonIssue.sort_key)
        return LocalisationComparisonResult(
            english_root=resolved_english,
            russian_root=resolved_russian,
            files_checked=len(files_with_languages),
            english_files=len(english_files),
            russian_files=len(russian_files),
            english_keys=len(english_keys),
            russian_keys=len(russian_keys),
            common_keys=len(english_keys & russian_keys),
            missing_russian=len(english_keys - russian_keys),
            missing_english=len(russian_keys - english_keys),
            duplicate_english=duplicate_english,
            duplicate_russian=duplicate_russian,
            parse_errors=len(unique_parse_issues),
            issues=issues,
        )
