"""Authoring of flat scripted-localisation assemblies for country events/welcome."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from .paradox_script import parse_blocks
from .parser import parse_localisation_file

BYTE_LIMIT = 6144
MANIFEST = ".localisation-checker/long_texts.json"
_KEY = re.compile(r"^[A-Za-z0-9_.'-]+$")
_GETTER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_TOKEN = re.compile(
    r"\[(?:[^\[\]]|\[[^\]]*\])*\]|\$[^$\n]+\$|£[^£\s]+£?"
    r"|@[A-Za-z0-9_]+|§.|\\.|.", re.DOTALL
)


def decode_value(raw: str) -> str:
    """Decode only the game escapes, never unicode_escape."""
    escapes = {"n": "\n", "N": "\n", "t": "\t", "T": "\t", '"': '"', "\\": "\\"}
    return re.sub(
        r"\\(.)",
        lambda match: escapes.get(match[1], match[0]),
        raw,
    )


def encode_value(text: str) -> str:
    return (
        text.replace("\\", "\\\\").replace('"', '\\"')
        .replace("\r\n", "\n").replace("\r", "\n")
        .replace("\n", "\\n").replace("\t", "\\t")
    )


def byte_size(text: str) -> int:
    return len(text.encode("utf-8"))


def split_text(text: str, target: int = 4000) -> list[str]:
    if not 1 <= target < BYTE_LIMIT:
        raise ValueError("Размер части должен быть от 1 до 6143 байт.")
    tokens = [match.group() for match in _TOKEN.finditer(text)]
    result: list[str] = []
    start = 0
    while start < len(tokens):
        size = 0
        end = start
        preferred: dict[int, int] = {}
        while end < len(tokens):
            token_size = byte_size(tokens[end])
            if size + token_size > target:
                break
            size += token_size
            end += 1
            if tokens[end - 1] == "\n":
                rank = 3 if end >= 2 and tokens[end - 2] == "\n" else 2
                preferred[rank] = end
            elif tokens[end - 1].isspace():
                rank = 2 if end >= 2 and tokens[end - 2] in ".!?" else 1
                preferred[rank] = end
        if end == start:
            raise ValueError(
                "Одна неделимая вставка превышает выбранный размер части."
            )
        if end < len(tokens):
            # Avoid many tiny fragments when the only boundary is near the start.
            for rank in (3, 2, 1):
                boundary = preferred.get(rank, start)
                if boundary > start and byte_size(
                    "".join(tokens[start:boundary])
                ) >= target // 2:
                    end = boundary
                    break
        result.append("".join(tokens[start:end]))
        start = end
    return result or [""]


@dataclass(frozen=True, slots=True)
class TextBranch:
    tag: str
    parts: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AssemblySpec:
    key: str
    source: str  # Mod-relative localisation file containing the existing key.
    prefix: str
    kind: Literal["event", "welcome"]
    branches: tuple[TextBranch, ...]
    language: str = "l_russian"

    @property
    def identity(self) -> str:
        return hashlib.sha256(
            f"{self.language}:{self.key}".encode()
        ).hexdigest()[:16]

    def validate(self) -> None:
        if not _KEY.fullmatch(self.key):
            raise ValueError("Недопустимое имя основного ключа.")
        if not _GETTER.fullmatch(self.prefix):
            raise ValueError("Префикс: латинские буквы, цифры и подчёркивание.")
        if self.language not in {"l_russian", "l_english"}:
            raise ValueError("Поддерживаются русский и английский языки.")
        if self.kind not in {"event", "welcome"} or not self.branches:
            raise ValueError("Выберите ивент страны или вступительный экран.")
        if self.kind == "event" and (
            len(self.branches) != 1 or self.branches[0].tag
        ):
            raise ValueError("Ивент использует одну безусловную ветку.")
        if self.kind == "welcome" and self.key != "EAW_WS_TAB_1_TXT":
            raise ValueError("Шаблон EaW собирается в EAW_WS_TAB_1_TXT.")
        tags: set[str] = set()
        for branch in self.branches:
            if self.kind == "welcome" and not re.fullmatch(
                r"[A-Z0-9]{3}", branch.tag
            ):
                raise ValueError("Укажите трёхсимвольный original_tag страны.")
            if branch.tag in tags or not branch.parts:
                raise ValueError("Ветки должны иметь уникальные теги и части.")
            tags.add(branch.tag)
            for part in branch.parts:
                if byte_size(part) >= BYTE_LIMIT:
                    raise ValueError("Каждая часть должна быть меньше 6144 байт.")


def generated_values(spec: AssemblySpec) -> tuple[str, dict[str, str], str]:
    spec.validate()
    count = max(len(branch.parts) for branch in spec.branches)
    calls = "".join(
        f"[Root.Get{spec.prefix}Part{number:02d}]"
        for number in range(1, count + 1)
    )
    if byte_size(calls) >= BYTE_LIMIT:
        raise ValueError("Строка вызовов превышает предел 6144 байта.")
    values: dict[str, str] = {}
    script: list[str] = []
    for number in range(1, count + 1):
        script.extend([
            "defined_text = {",
            f"    name = Get{spec.prefix}Part{number:02d}",
        ])
        for branch in spec.branches:
            if number > len(branch.parts):
                continue
            suffix = f"_{branch.tag}" if branch.tag else ""
            key = f"{spec.key}{suffix}_part_{number:02d}"
            values[key] = encode_value(branch.parts[number - 1])
            trigger = (
                f"original_tag = {branch.tag}" if branch.tag else "always = yes"
            )
            script.extend([
                "    text = {",
                f"        trigger = {{ {trigger} }}",
                f"        localization_key = {key}",
                "    }",
            ])
        if spec.kind == "welcome":
            fallback = f"{spec.key}_{spec.prefix}_original"
            empty = f"{spec.key}_{spec.prefix}_empty"
            values[fallback] = "[Root.GetCountryIntro]"
            values[empty] = ""
            script.extend([
                "    text = {",
                "        trigger = { always = yes }",
                f"        localization_key = {fallback if number == 1 else empty}",
                "    }",
            ])
        script.append("}\n")
    return calls, values, "\n".join(script)


def resolve_inside(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not relative or Path(relative).is_absolute():
        raise ValueError("Нужен относительный путь внутри выбранного мода.")
    try:
        path.relative_to(root.resolve())
    except ValueError as error:
        raise ValueError("Путь выходит за пределы выбранного мода.") from error
    return path


def load_specs(root: Path) -> list[AssemblySpec]:
    path = root / MANIFEST
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("format_version") != 1:
        raise ValueError("Неизвестный формат проекта длинных текстов.")
    result: list[AssemblySpec] = []
    for item in payload["assemblies"]:
        spec = AssemblySpec(
            key=item["key"], source=item["source"], prefix=item["prefix"],
            kind=item["kind"], language=item["language"],
            branches=tuple(
                TextBranch(branch["tag"], tuple(branch["parts"]))
                for branch in item["branches"]
            ),
        )
        spec.validate()
        resolve_inside(root, spec.source)
        result.append(spec)
    return result


@dataclass(frozen=True, slots=True)
class FileChange:
    path: Path
    before: bytes | None
    after: bytes


@dataclass(frozen=True, slots=True)
class WritePlan:
    root: Path
    spec: AssemblySpec
    changes: tuple[FileChange, ...]
    notes: tuple[str, ...]


def collect_entries(root: Path):
    entries = []
    for path in sorted((root / "localisation").rglob("*.yml")):
        entries.extend(parse_localisation_file(path).entries)
    return entries


def _event_description_keys(root: Path) -> set[str]:
    keys: set[str] = set()
    for path in (root / "events").rglob("*.txt"):
        for block in parse_blocks(path.read_text(encoding="utf-8-sig")):
            owner = block
            while owner.parent is not None:
                owner = owner.parent
            if owner.kind == "country_event":
                keys.update(block.properties.get("desc", []))
                if block.kind == "desc":
                    keys.update(block.properties.get("text", []))
    return keys


def prepare_plan(root: Path, spec: AssemblySpec) -> WritePlan:
    root = root.resolve()
    spec.validate()
    if not (root / "common").is_dir() or not (root / "localisation").is_dir():
        raise ValueError("Выберите корневую папку мода с common и localisation.")
    if spec.kind == "event" and spec.key not in _event_description_keys(root):
        raise ValueError(
            "Ключ не найден в desc ивента страны. Фокусы и другие типы "
            "ивентов не входят в этот конструктор."
        )
    source = resolve_inside(root, spec.source)
    if source.suffix.casefold() != ".yml":
        raise ValueError("Источник должен быть файлом .yml.")
    parsed = parse_localisation_file(source)
    if any(
        item.severity == "error"
        and not (
            item.code == "INVALID_ESCAPE" and item.character in {"\\N", "\\T"}
        )
        for item in parsed.diagnostics
    ):
        raise ValueError("Сначала исправьте ошибки разбора исходного файла.")
    matches = [
        entry for entry in parsed.entries
        if entry.key == spec.key and entry.language == spec.language
    ]
    if len(matches) != 1:
        raise ValueError("В исходном файле нужно одно определение выбранного ключа.")
    entry = matches[0]
    language_dir = spec.language.removeprefix("l_")
    loc = resolve_inside(
        root, f"localisation/{language_dir}/checker_long_{spec.identity}_"
        f"{spec.language}.yml"
    )
    script_path = resolve_inside(
        root, f"common/scripted_localisation/checker_long_{spec.identity}.txt"
    )
    existing = load_specs(root)
    old = next(
        (item for item in existing
         if item.key == spec.key and item.language == spec.language),
        None,
    )
    if old is not None and old.source != spec.source:
        raise ValueError("Основной ключ проекта перенесён: сначала проверьте источник.")
    if old is None and (loc.exists() or script_path.exists()):
        raise ValueError("Файлы с выбранными именами уже существуют.")
    calls, values, script = generated_values(spec)
    all_entries = collect_entries(root)
    if sum(
        item.key == spec.key and item.language == spec.language
        for item in all_entries
    ) != 1:
        raise ValueError("Основной ключ повторяется в локализации мода.")
    for other in all_entries:
        if other.path.resolve() != loc and other.key in values:
            raise ValueError(f"Конфликт служебного ключа: {other.key}")
    names = {
        value
        for path in (root / "common/scripted_localisation").rglob("*.txt")
        if path.resolve() != script_path
        for block in parse_blocks(path.read_text(encoding="utf-8-sig"))
        if block.kind == "defined_text"
        for value in block.properties.get("name", [])
    }
    for block in parse_blocks(script):
        if block.properties.get("name", [""])[0] in names:
            raise ValueError("Префикс конфликтует с существующим getter.")
    notes: list[str] = []
    by_key = {
        item.key: item.raw_value for item in all_entries
        if item.language == spec.language
    }
    for raw in values.values():
        references = list(re.findall(r"\$([^$\n]+)\$", raw))
        visited: set[str] = set()
        while references:
            key = references.pop()
            if key == spec.key:
                raise ValueError("Часть ссылается на собственный основной ключ.")
            if key in visited:
                continue
            visited.add(key)
            references.extend(re.findall(
                r"\$([^$\n]+)\$", by_key.get(key, "")
            ))
        size = expanded_byte_size(raw, by_key)
        if size is None:
            notes.append(
                "Есть динамические/неизвестные подстановки: полный размер "
                "частей нужно проверить в игре."
            )
        elif size >= BYTE_LIMIT:
            raise ValueError("Часть после раскрытия $KEY$ достигает 6144 байт.")
    for branch in spec.branches:
        color = False
        for part in branch.parts:
            for code in re.findall(r"§(.)", part):
                color = code != "!"
            if color:
                notes.append(
                    "Цвет продолжается через границу части. Проверьте стык "
                    "в игре либо перенесите границу после §!."
                )
    before = source.read_bytes()
    lines = before.decode("utf-8-sig").splitlines(keepends=True)
    line = lines[entry.line - 1]
    start = entry.value_column - 1
    stop = start + len(entry.raw_value)
    lines[entry.line - 1] = line[:start] + calls + line[stop:]
    new_source = b"\xef\xbb\xbf" + "".join(lines).encode("utf-8")
    loc_text = spec.language + ":\n" + "".join(
        f' {key}:0 "{raw}"\n' for key, raw in values.items()
    )
    existing = [
        item for item in existing
        if not (item.key == spec.key and item.language == spec.language)
    ] + [spec]
    manifest = json.dumps(
        {"format_version": 1, "assemblies": [asdict(item) for item in existing]},
        ensure_ascii=False, indent=2,
    ) + "\n"
    changes = tuple(
        FileChange(path, path.read_bytes() if path.exists() else None, content)
        for path, content in (
            (source, new_source),
            (loc, b"\xef\xbb\xbf" + loc_text.encode("utf-8")),
            (script_path, script.encode("utf-8")),
            (resolve_inside(root, MANIFEST), manifest.encode("utf-8")),
        )
    )
    return WritePlan(root, spec, changes, tuple(sorted(set(notes))))


def expanded_byte_size(raw: str, values: dict[str, str]) -> int | None:
    def measure(value: str, stack: tuple[str, ...]) -> int | None:
        if len(stack) >= 30:
            raise ValueError("Слишком глубокая цепочка $KEY$.")
        size = 0
        start = 0
        for match in re.finditer(r"\$([^$\n]+)\$", value):
            literal = decode_value(value[start:match.start()])
            if "[" in literal:
                return None
            size += byte_size(literal)
            key = match[1]
            if key in stack:
                raise ValueError("Цикл $KEY$: " + " → ".join((*stack, key)))
            if key not in values:
                return None
            referenced_size = measure(values[key], (*stack, key))
            if referenced_size is None:
                return None
            size += referenced_size
            start = match.end()
            if size >= BYTE_LIMIT:
                return size
        tail = decode_value(value[start:])
        if "[" in tail:
            return None
        return size + byte_size(tail)
    return measure(raw, ())


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=".checker-")
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def apply_plan(plan: WritePlan) -> Path:
    """Check snapshots, back up all originals, then write; roll back on failure."""
    for change in plan.changes:
        resolve_inside(plan.root, change.path.relative_to(plan.root).as_posix())
        current = change.path.read_bytes() if change.path.exists() else None
        if current != change.before:
            raise ValueError("Файл изменился после предпросмотра: " + str(change.path))
    backup = plan.root / ".localisation-checker/backups" / datetime.now().strftime(
        "%Y%m%d-%H%M%S-%f"
    )
    backup.mkdir(parents=True)
    listing = []
    for change in plan.changes:
        relative = change.path.relative_to(plan.root).as_posix()
        listing.append({
            "path": relative, "created": change.before is None,
            "backup": relative + ".bak" if change.before is not None else None,
        })
        if change.before is not None:
            _atomic_write(backup / (relative + ".bak"), change.before)
    _atomic_write(
        backup / "changes.json",
        json.dumps(listing, ensure_ascii=False, indent=2).encode("utf-8"),
    )
    written: list[FileChange] = []
    try:
        for change in plan.changes:
            _atomic_write(change.path, change.after)
            written.append(change)
    except OSError:
        for change in reversed(written):
            if change.before is None:
                change.path.unlink(missing_ok=True)
            else:
                _atomic_write(change.path, change.before)
        raise
    return backup
