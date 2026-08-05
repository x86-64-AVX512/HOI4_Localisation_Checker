from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

_GUI_TOKEN = re.compile(r'"(?:\\.|[^"\\])*"|#[^\r\n]*|[{}=]|[^\s{}="#]+')
_LOCALISATION_EXPRESSION = re.compile(r"\[([^\]\r\n]+)\]")
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
__all__ = [
    "ParsedBlock",
    "ancestor_names",
    "block_name",
    "font_names",
    "has_ancestor_kind",
    "localisation_calls",
    "parse_blocks",
    "property_line",
    "read_script_blocks",
    "token_value",
    "tokenize_script",
    "tokenize_script_with_lines",
]


@dataclass(slots=True)
class ParsedBlock:
    kind: str
    parent: ParsedBlock | None
    properties: dict[str, list[str]]
    property_lines: dict[str, list[int]]
    source_path: Path | None
    line: int


def tokenize_script(text: str) -> list[str]:
    return [token for token, _ in tokenize_script_with_lines(text)]


def tokenize_script_with_lines(text: str) -> list[tuple[str, int]]:
    result: list[tuple[str, int]] = []
    line = 1
    previous_end = 0
    for match in _GUI_TOKEN.finditer(text):
        line += text.count("\n", previous_end, match.start())
        previous_end = match.end()
        token = match.group(0)
        if not token.startswith("#"):
            result.append((token, line))
    return result


def token_value(token: str) -> str:
    if len(token) >= 2 and token.startswith('"') and token.endswith('"'):
        return token[1:-1].replace(r"\"", '"').replace(r"\\", "\\")
    return token


def parse_blocks(
    text: str,
    source_path: Path | None = None,
) -> list[ParsedBlock]:
    token_items = tokenize_script_with_lines(text)
    tokens = [token for token, _ in token_items]
    token_lines = [line for _, line in token_items]
    blocks: list[ParsedBlock] = []
    stack: list[ParsedBlock] = []
    index = 0

    while index < len(tokens):
        token = tokens[index]
        if (
            index + 2 < len(tokens)
            and tokens[index + 1] == "="
            and tokens[index + 2] == "{"
        ):
            block = ParsedBlock(
                kind=token_value(token),
                parent=stack[-1] if stack else None,
                properties=defaultdict(list),
                property_lines=defaultdict(list),
                source_path=source_path,
                line=token_lines[index],
            )
            blocks.append(block)
            stack.append(block)
            index += 3
            continue
        if token == "}":
            if stack:
                stack.pop()
            index += 1
            continue
        if (
            stack
            and index + 2 < len(tokens)
            and tokens[index + 1] == "="
            and tokens[index + 2] != "{"
        ):
            stack[-1].properties[token.casefold()].append(
                token_value(tokens[index + 2])
            )
            stack[-1].property_lines[token.casefold()].append(token_lines[index])
            index += 3
            continue
        index += 1
    return blocks


def read_script_blocks(
    path: Path,
    read_errors: list[str],
) -> list[ParsedBlock]:
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError as error:
        read_errors.append(f"Не удалось прочитать {path}: {error}")
        return []
    return parse_blocks(text, source_path=path)


def block_name(block: ParsedBlock) -> str:
    names = block.properties.get("name", [])
    return names[0] if names else ""


def property_line(
    block: ParsedBlock,
    property_name: str,
    value: str,
) -> int:
    normalized = property_name.casefold()
    values = block.properties.get(normalized, [])
    lines = block.property_lines.get(normalized, [])
    for index, candidate in enumerate(values):
        if candidate == value and index < len(lines):
            return lines[index]
    return block.line


def ancestor_names(block: ParsedBlock) -> Iterator[str]:
    parent = block.parent
    while parent is not None:
        name = block_name(parent)
        if name:
            yield name.casefold()
        parent = parent.parent


def has_ancestor_kind(block: ParsedBlock, kinds: frozenset[str]) -> bool:
    parent = block.parent
    while parent is not None:
        if parent.kind.casefold() in kinds:
            return True
        parent = parent.parent
    return False


def font_names(block: ParsedBlock) -> set[str]:
    return {
        font
        for property_name in ("font", "buttonfont")
        for font in block.properties.get(property_name, [])
        if font
    }


def localisation_calls(value: str) -> set[str]:
    calls: set[str] = set()
    for match in _LOCALISATION_EXPRESSION.finditer(value):
        expression = match.group(1).split("|", 1)[0].strip()
        if not expression or expression[0] in {"?", "@"}:
            continue
        candidate = expression.rsplit(".", 1)[-1]
        candidate = candidate.split("(", 1)[0].strip()
        if _IDENTIFIER.fullmatch(candidate):
            calls.add(candidate)
    return calls
