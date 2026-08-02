from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path


KNOWN_LANGUAGES = (
    "l_english",
    "l_braz_por",
    "l_french",
    "l_german",
    "l_japanese",
    "l_korean",
    "l_polish",
    "l_russian",
    "l_simp_chinese",
    "l_spanish",
)

LANGUAGE_REQUIRED = {
    "l_english": "",
    "l_braz_por": "ÁÂÃÀÇÉÊÍÓÔÕÚáâãàçéêíóôõú",
    "l_french": "ÀÂÇÉÈÊËÎÏÔÙÛÜŸàâçéèêëîïôùûüÿŒœ",
    "l_german": "ÄÖÜäöüß",
    "l_japanese": "あいうえおアイウエオ日本語",
    "l_korean": "가나다라마바사아자차카타파하",
    "l_polish": "ĄĆĘŁŃÓŚŹŻąćęłńóśźż",
    "l_russian": (
        "АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ"
        "абвгдеёжзийклмнопрстуфхцчшщъыьэюя"
    ),
    "l_simp_chinese": "的一是在不了有人这中大为上个国我以要他",
    "l_spanish": "ÁÉÍÑÓÚÜáéíñóúü¿¡",
}

EXCLUDED_NAME_PARTS = (
    "arrow",
    "debug",
    "gauge",
    "icon",
    "invisible",
    "mapfont",
    "symbol",
)

REQUIRED_ASCII = frozenset(
    ord(character)
    for character in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789.,!?-:;'\"()"
)
CHAR_LINE = re.compile(rb"^char\s+id=(\d+)(?:\s|$)")
GUI_FONT = re.compile(
    r"\b(?:font|buttonFont)\s*=\s*\"([^\"]+)\"",
    flags=re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class Token:
    kind: str
    value: str


@dataclass(frozen=True, slots=True)
class FontDefinition:
    kind: str
    name: str
    references: tuple[str, ...]
    languages: tuple[str, ...]
    source: str


def tokenize(text: str) -> list[Token]:
    tokens: list[Token] = []
    cursor = 0
    while cursor < len(text):
        character = text[cursor]
        if character.isspace():
            cursor += 1
            continue
        if character == "#":
            newline = text.find("\n", cursor + 1)
            cursor = len(text) if newline < 0 else newline + 1
            continue
        if character == '"':
            cursor += 1
            value: list[str] = []
            while cursor < len(text):
                if text[cursor] == "\\" and cursor + 1 < len(text):
                    value.append(text[cursor + 1])
                    cursor += 2
                    continue
                if text[cursor] == '"':
                    cursor += 1
                    break
                value.append(text[cursor])
                cursor += 1
            tokens.append(Token("string", "".join(value)))
            continue
        if character in "{}=":
            tokens.append(
                Token(
                    {"{": "lbrace", "}": "rbrace", "=": "equals"}[character],
                    character,
                )
            )
            cursor += 1
            continue

        start = cursor
        while (
            cursor < len(text)
            and not text[cursor].isspace()
            and text[cursor] not in '{}="#'
        ):
            cursor += 1
        if start == cursor:
            cursor += 1
        else:
            tokens.append(Token("word", text[start:cursor]))
    return tokens


def _matching_brace(tokens: list[Token], opening: int) -> int:
    depth = 0
    for index in range(opening, len(tokens)):
        if tokens[index].kind == "lbrace":
            depth += 1
        elif tokens[index].kind == "rbrace":
            depth -= 1
            if depth == 0:
                return index
    return len(tokens) - 1


def _block_properties(tokens: list[Token]) -> dict[str, object]:
    properties: dict[str, object] = {}
    cursor = 0
    while cursor + 2 < len(tokens):
        if (
            tokens[cursor].kind == "word"
            and tokens[cursor + 1].kind == "equals"
        ):
            name = tokens[cursor].value
            value_token = tokens[cursor + 2]
            if value_token.kind == "lbrace":
                end = _matching_brace(tokens, cursor + 2)
                values = [
                    token.value
                    for token in tokens[cursor + 3 : end]
                    if token.kind in {"word", "string"}
                ]
                properties[name] = values
                cursor = end + 1
                continue
            properties[name] = value_token.value
            cursor += 3
            continue
        cursor += 1
    return properties


def extract_font_definitions(path: Path, label: str) -> list[FontDefinition]:
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    tokens = tokenize(text)
    definitions: list[FontDefinition] = []
    cursor = 0

    while cursor + 2 < len(tokens):
        token = tokens[cursor]
        if (
            token.kind == "word"
            and token.value in {"bitmapfont", "bitmapfont_override"}
            and tokens[cursor + 1].kind == "equals"
            and tokens[cursor + 2].kind == "lbrace"
        ):
            end = _matching_brace(tokens, cursor + 2)
            properties = _block_properties(tokens[cursor + 3 : end])
            name = str(properties.get("name", ""))
            raw_files = properties.get("fontfiles")
            raw_path = properties.get("path")
            if isinstance(raw_files, list):
                references = tuple(str(value) for value in raw_files)
            elif isinstance(raw_path, str):
                references = (raw_path,)
            else:
                references = ()
            raw_languages = properties.get("languages", [])
            languages = (
                tuple(str(value) for value in raw_languages)
                if isinstance(raw_languages, list)
                else ()
            )
            if name and references:
                definitions.append(
                    FontDefinition(
                        kind=token.value,
                        name=name,
                        references=references,
                        languages=languages,
                        source=label,
                    )
                )
            cursor = end + 1
            continue
        cursor += 1

    return definitions


def effective_files(
    base_root: Path,
    mod_root: Path,
    pattern: str,
) -> dict[str, Path]:
    files: dict[str, Path] = {}
    if base_root.is_dir():
        for path in base_root.rglob(pattern):
            if path.is_file():
                files[path.relative_to(base_root).as_posix().casefold()] = path
    if mod_root.is_dir():
        for path in mod_root.rglob(pattern):
            if path.is_file():
                files[path.relative_to(mod_root).as_posix().casefold()] = path
    return files


def read_glyphs(path: Path, cache: dict[Path, frozenset[int]]) -> frozenset[int]:
    if path in cache:
        return cache[path]
    glyphs: set[int] = set()
    with path.open("rb") as font_file:
        for line in font_file:
            match = CHAR_LINE.match(line)
            if match:
                glyphs.add(int(match.group(1)))
    result = frozenset(glyphs)
    cache[path] = result
    return result


def normalise_reference(reference: str) -> str:
    value = reference.replace("\\", "/")
    if value.casefold().startswith("gfx/fonts/"):
        value = value[len("gfx/fonts/") :]
    if not value.casefold().endswith(".fnt"):
        value += ".fnt"
    return value


def resolve_reference(
    reference: str,
    base_fonts: Path,
    mod_fonts: Path,
) -> tuple[str, Path] | None:
    relative = normalise_reference(reference)
    mod_path = mod_fonts / Path(relative)
    if mod_path.is_file():
        return f"mod/{relative}", mod_path
    base_path = base_fonts / Path(relative)
    if base_path.is_file():
        return f"base/{relative}", base_path
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--game-root", type=Path, required=True)
    parser.add_argument("--mod-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()

    game_root = arguments.game_root.resolve()
    mod_root = arguments.mod_root.resolve()
    base_interface = game_root / "interface"
    mod_interface = mod_root / "interface"
    base_fonts = game_root / "gfx" / "fonts"
    mod_fonts = mod_root / "gfx" / "fonts"

    effective_gfx = effective_files(base_interface, mod_interface, "*.gfx")
    definitions: list[FontDefinition] = []
    for relative, path in sorted(effective_gfx.items()):
        origin = "mod" if path.is_relative_to(mod_interface) else "base"
        definitions.extend(
            extract_font_definitions(path, f"{origin}:interface/{relative}")
        )

    effective_gui = effective_files(base_interface, mod_interface, "*.gui")
    used_names: set[str] = set()
    for path in effective_gui.values():
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        used_names.update(GUI_FONT.findall(text))
    used_names.update(
        {
            "ToolTip_Font",
            "eaw_diplo_16mbs",
            "loadscreen_header",
            "loadscreen_tip",
        }
    )

    defaults: dict[str, FontDefinition] = {}
    overrides: dict[tuple[str, str], FontDefinition] = {}
    for definition in definitions:
        if definition.kind == "bitmapfont":
            defaults[definition.name] = definition
        else:
            for language in definition.languages:
                overrides[(definition.name, language)] = definition

    glyph_cache: dict[Path, frozenset[int]] = {}
    eligible_names: list[str] = []
    skipped: dict[str, str] = {}
    for name in sorted(used_names, key=str.casefold):
        default = defaults.get(name)
        if default is None:
            skipped[name] = "definition not found"
            continue
        if any(part in name.casefold() for part in EXCLUDED_NAME_PARTS):
            skipped[name] = "technical font"
            continue

        resolved = [
            resolve_reference(reference, base_fonts, mod_fonts)
            for reference in default.references
        ]
        if not resolved or any(item is None for item in resolved):
            skipped[name] = "font file not found"
            continue

        union: set[int] = set()
        for item in resolved:
            assert item is not None
            union.update(read_glyphs(item[1], glyph_cache))
        if not REQUIRED_ASCII.issubset(union):
            skipped[name] = "does not contain the basic UI alphabet"
            continue
        eligible_names.append(name)

    language_profiles: dict[str, object] = {}
    missing_references: list[str] = []
    language_skips: dict[str, dict[str, str]] = {}
    for language in KNOWN_LANGUAGES:
        families: dict[str, list[str]] = {}
        skipped_for_language: dict[str, str] = {}
        required_script = {
            ord(character) for character in LANGUAGE_REQUIRED.get(language, "")
        }
        for name in eligible_names:
            definition = overrides.get((name, language), defaults[name])
            paths: list[str] = []
            family_union: set[int] = set()
            complete = True
            for reference in definition.references:
                resolved = resolve_reference(reference, base_fonts, mod_fonts)
                if resolved is None:
                    missing_references.append(
                        f"{name} ({language}): {reference} from {definition.source}"
                    )
                    complete = False
                    break
                paths.append(resolved[0])
                family_union.update(read_glyphs(resolved[1], glyph_cache))
            if complete and not required_script.issubset(family_union):
                skipped_for_language[name] = (
                    "does not contain the language's basic writing system"
                )
                complete = False
            if complete and paths:
                families[name] = paths
        language_profiles[language] = {"families": families}
        language_skips[language] = skipped_for_language

    output = {
        "format_version": 1,
        "name": "Equestria at War / Hearts of Iron IV UI fonts",
        "default_language": "l_english",
        "languages": language_profiles,
        "metadata": {
            "eligible_logical_fonts": len(eligible_names),
            "definitions_found": len(definitions),
            "used_font_names_found": len(used_names),
            "skipped_fonts": skipped,
            "language_specific_skips": language_skips,
            "missing_references": sorted(set(missing_references)),
        },
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(output, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        f"Wrote {arguments.output} with {len(eligible_names)} logical UI fonts "
        f"and {len(KNOWN_LANGUAGES)} language profiles."
    )
    if missing_references:
        print(f"Missing references: {len(set(missing_references))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
