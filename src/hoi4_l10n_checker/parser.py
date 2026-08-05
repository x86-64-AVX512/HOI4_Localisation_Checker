from __future__ import annotations

import re
from pathlib import Path

from .models import (
    Diagnostic,
    LocalisationEntry,
    ParsedFile,
    RenderedCharacter,
)

UTF8_BOM = b"\xef\xbb\xbf"
UTF16_LE_BOM = b"\xff\xfe"
UTF16_BE_BOM = b"\xfe\xff"
ALLOWED_ESCAPES = {"n", '"', "\\"}

_LANGUAGE_HEADER = re.compile(r"^\s*(l_[A-Za-z0-9_]+)\s*:\s*(?:#.*)?$")
_KEY = re.compile(r"^[^\s:#]+$")
_TEXT_ICON_TAIL = re.compile(r"[A-Za-z0-9_./:-]")
_FLAG_TAIL = re.compile(r"[A-Za-z0-9_]")


def _byte_position(data: bytes, offset: int) -> tuple[int, int]:
    before = data[:offset]
    line = before.count(b"\n") + 1
    previous_newline = before.rfind(b"\n")
    column = offset - previous_newline
    return line, column


def _text_position(text: str, offset: int) -> tuple[int, int]:
    before = text[:offset]
    line = before.count("\n") + 1
    previous_newline = before.rfind("\n")
    column = offset - previous_newline
    return line, column


def _decode_utf8(path: Path, data: bytes) -> tuple[str, list[Diagnostic]]:
    diagnostics: list[Diagnostic] = []

    if data.startswith(UTF8_BOM):
        payload = data[len(UTF8_BOM) :]
        payload_offset = len(UTF8_BOM)
    else:
        payload = data
        payload_offset = 0
        if data.startswith(UTF16_LE_BOM) or data.startswith(UTF16_BE_BOM):
            message = "Файл имеет BOM UTF-16 вместо обязательного UTF-8 BOM."
        else:
            message = "В начале файла отсутствует обязательный UTF-8 BOM."
        diagnostics.append(
            Diagnostic(
                severity="error",
                code="MISSING_UTF8_BOM",
                path=path,
                line=1,
                column=1,
                message=message,
            )
        )

    chunks: list[str] = []
    cursor = 0
    while cursor < len(payload):
        try:
            chunks.append(payload[cursor:].decode("utf-8", errors="strict"))
            cursor = len(payload)
        except UnicodeDecodeError as error:
            valid_end = cursor + error.start
            if valid_end > cursor:
                chunks.append(payload[cursor:valid_end].decode("utf-8", errors="strict"))

            absolute_offset = payload_offset + valid_end
            line, column = _byte_position(data, absolute_offset)
            bad_bytes = payload[valid_end : cursor + max(error.end, error.start + 1)]
            diagnostics.append(
                Diagnostic(
                    severity="error",
                    code="INVALID_UTF8",
                    path=path,
                    line=line,
                    column=column,
                    message=(
                        "Повреждённая последовательность UTF-8: "
                        f"{bad_bytes.hex(' ').upper()} (байт {absolute_offset})."
                    ),
                )
            )
            chunks.append("\ufffd")
            cursor += max(error.end, error.start + 1)

    text = "".join(chunks)
    for match in re.finditer("\ufeff", text):
        line, column = _text_position(text, match.start())
        diagnostics.append(
            Diagnostic(
                severity="error",
                code="EMBEDDED_BOM",
                path=path,
                line=line,
                column=column,
                message="BOM U+FEFF обнаружен внутри текста.",
                character="\ufeff",
            )
        )

    return text, diagnostics


def _first_non_space(text: str, start: int = 0) -> int:
    index = start
    while index < len(text) and text[index].isspace():
        index += 1
    return index


def _parse_entry_line(
    path: Path,
    line_number: int,
    line: str,
    language: str,
) -> tuple[LocalisationEntry | None, list[Diagnostic]]:
    diagnostics: list[Diagnostic] = []
    colon = line.find(":")
    if colon < 0:
        first = _first_non_space(line)
        diagnostics.append(
            Diagnostic(
                severity="error",
                code="MALFORMED_ENTRY",
                path=path,
                line=line_number,
                column=first + 1,
                message="Строка локализации не содержит разделитель «:».",
            )
        )
        return None, diagnostics

    raw_key = line[:colon]
    key = raw_key.strip()
    key_column = len(raw_key) - len(raw_key.lstrip()) + 1
    if not key or not _KEY.fullmatch(key):
        diagnostics.append(
            Diagnostic(
                severity="error",
                code="INVALID_KEY",
                path=path,
                line=line_number,
                column=key_column,
                message="Некорректный или пустой ключ локализации.",
                key=key,
            )
        )

    cursor = colon + 1
    cursor = _first_non_space(line, cursor)
    while cursor < len(line) and line[cursor].isdigit():
        cursor += 1
    cursor = _first_non_space(line, cursor)

    if cursor >= len(line) or line[cursor] != '"':
        diagnostics.append(
            Diagnostic(
                severity="error",
                code="MISSING_OPENING_QUOTE",
                path=path,
                line=line_number,
                column=min(cursor + 1, len(line) + 1),
                message="После ключа отсутствует открывающая кавычка.",
                key=key,
            )
        )
        return None, diagnostics

    opening_quote = cursor
    cursor += 1
    closing_quote = -1

    while cursor < len(line):
        character = line[cursor]
        if character == "\\":
            if cursor + 1 >= len(line):
                diagnostics.append(
                    Diagnostic(
                        severity="error",
                        code="TRAILING_BACKSLASH",
                        path=path,
                        line=line_number,
                        column=cursor + 1,
                        message="Обратный слеш находится в конце строки.",
                        key=key,
                        character="\\",
                    )
                )
                cursor += 1
                continue

            escaped = line[cursor + 1]
            if escaped not in ALLOWED_ESCAPES:
                diagnostics.append(
                    Diagnostic(
                        severity="error",
                        code="INVALID_ESCAPE",
                        path=path,
                        line=line_number,
                        column=cursor + 1,
                        message=f"Неизвестная escape-последовательность «\\{escaped}».",
                        key=key,
                        character=f"\\{escaped}",
                    )
                )
            cursor += 2
            continue

        if character == '"':
            trailing_start = _first_non_space(line, cursor + 1)
            if trailing_start >= len(line) or line[trailing_start] == "#":
                closing_quote = cursor
                break
        cursor += 1

    if closing_quote < 0:
        diagnostics.append(
            Diagnostic(
                severity="error",
                code="UNCLOSED_QUOTE",
                path=path,
                line=line_number,
                column=opening_quote + 1,
                message="Строка локализации содержит незакрытую кавычку.",
                key=key,
            )
        )
        return None, diagnostics

    entry = LocalisationEntry(
        path=path,
        line=line_number,
        language=language,
        key=key,
        raw_value=line[opening_quote + 1 : closing_quote],
        value_column=opening_quote + 2,
    )
    return entry, diagnostics


def parse_localisation_file(path: Path) -> ParsedFile:
    diagnostics: list[Diagnostic] = []
    entries: list[LocalisationEntry] = []
    languages: set[str] = set()

    try:
        data = path.read_bytes()
    except OSError as error:
        return ParsedFile(
            path=path,
            entries=[],
            diagnostics=[
                Diagnostic(
                    severity="error",
                    code="FILE_READ_ERROR",
                    path=path,
                    line=1,
                    column=1,
                    message=f"Не удалось прочитать файл: {error}",
                )
            ],
            languages=set(),
        )

    text, decoding_diagnostics = _decode_utf8(path, data)
    diagnostics.extend(decoding_diagnostics)

    current_language = ""
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue

        header = _LANGUAGE_HEADER.fullmatch(line)
        if header:
            current_language = header.group(1)
            languages.add(current_language)
            continue

        if not current_language:
            first = _first_non_space(line)
            diagnostics.append(
                Diagnostic(
                    severity="error",
                    code="MISSING_LANGUAGE_HEADER",
                    path=path,
                    line=line_number,
                    column=first + 1,
                    message="Запись находится до заголовка языка вида «l_english:».",
                )
            )
            language = "l_unknown"
        else:
            language = current_language

        entry, line_diagnostics = _parse_entry_line(
            path=path,
            line_number=line_number,
            line=line,
            language=language,
        )
        diagnostics.extend(line_diagnostics)
        if entry is not None:
            entries.append(entry)

    if not languages:
        diagnostics.append(
            Diagnostic(
                severity="error",
                code="NO_LANGUAGE_HEADER",
                path=path,
                line=1,
                column=1,
                message="В файле не найден заголовок языка вида «l_english:».",
            )
        )

    return ParsedFile(
        path=path,
        entries=entries,
        diagnostics=diagnostics,
        languages=languages,
    )


def iter_rendered_characters(entry: LocalisationEntry):
    value = entry.raw_value
    cursor = 0

    while cursor < len(value):
        character = value[cursor]
        column = entry.value_column + cursor

        if character == "\\" and cursor + 1 < len(value):
            escaped = value[cursor + 1]
            if escaped == "n":
                cursor += 2
                continue
            if escaped == '"':
                yield RenderedCharacter('"', column)
                cursor += 2
                continue
            if escaped == "\\":
                yield RenderedCharacter("\\", column)
                cursor += 2
                continue
            cursor += 2
            continue

        if character == "§" and cursor + 1 < len(value):
            cursor += 2
            continue

        if character == "£":
            cursor += 1
            while cursor < len(value) and _TEXT_ICON_TAIL.fullmatch(value[cursor]):
                cursor += 1
            if cursor + 1 < len(value) and value[cursor] == "|" and value[cursor + 1].isalpha():
                cursor += 2
            continue

        if character == "$":
            end = value.find("$", cursor + 1)
            if end >= 0:
                cursor = end + 1
                continue

        if character == "[":
            depth = 1
            end = cursor + 1
            while end < len(value) and depth:
                if value[end] == "[":
                    depth += 1
                elif value[end] == "]":
                    depth -= 1
                end += 1
            if depth == 0:
                cursor = end
                continue

        if character == "@" and cursor + 1 < len(value):
            end = cursor + 1
            while end < len(value) and _FLAG_TAIL.fullmatch(value[end]):
                end += 1
            if end > cursor + 1:
                cursor = end
                continue

        yield RenderedCharacter(character, column)
        cursor += 1
