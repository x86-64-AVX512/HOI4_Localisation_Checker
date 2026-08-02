from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Diagnostic:
    severity: str
    code: str
    path: Path
    line: int
    column: int
    message: str
    key: str = ""
    character: str = ""
    text_kind: str = ""
    measured_length: int = 0
    limit: int = 0
    selection_length: int = 0
    role_confidence: str = ""
    role_evidence: str = ""
    preview_status: str = ""
    preview_lines: int = 0
    preview_height_px: int = 0
    preview_overlap_px: int = 0
    missing_glyphs: str = ""

    def sort_key(self) -> tuple[str, int, int, str, str]:
        return (
            str(self.path).casefold(),
            self.line,
            self.column,
            self.code,
            self.character,
        )

    def as_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["path"] = str(self.path)
        return result


@dataclass(frozen=True, slots=True)
class LocalisationEntry:
    path: Path
    line: int
    language: str
    key: str
    raw_value: str
    value_column: int


@dataclass(frozen=True, slots=True)
class RenderedCharacter:
    character: str
    column: int


@dataclass(slots=True)
class ParsedFile:
    path: Path
    entries: list[LocalisationEntry]
    diagnostics: list[Diagnostic]
    languages: set[str]
