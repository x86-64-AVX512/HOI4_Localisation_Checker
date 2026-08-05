from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROFILE = PROJECT_ROOT / "font_profile.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "fonts"


class FontPreparationError(RuntimeError):
    pass


def profile_references(profile_path: Path) -> tuple[str, ...]:
    try:
        data = json.loads(profile_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise FontPreparationError(
            f"Не удалось прочитать профиль шрифтов: {error}"
        ) from error

    languages = data.get("languages")
    if not isinstance(languages, dict):
        raise FontPreparationError(
            "В font_profile.json отсутствует объект languages."
        )

    references: set[str] = set()
    for language_data in languages.values():
        if not isinstance(language_data, dict):
            continue
        families = language_data.get("families")
        if not isinstance(families, dict):
            continue
        for paths in families.values():
            if not isinstance(paths, list):
                continue
            for raw_path in paths:
                if not isinstance(raw_path, str):
                    continue
                normalized = raw_path.replace("\\", "/")
                parts = Path(normalized).parts
                if (
                    len(parts) < 2
                    or parts[0] not in {"base", "mod"}
                    or ".." in parts
                    or Path(normalized).suffix.casefold() != ".fnt"
                ):
                    raise FontPreparationError(
                        f"Недопустимый путь в профиле: {raw_path}"
                    )
                references.add(Path(*parts).as_posix())
    if not references:
        raise FontPreparationError(
            "Профиль не содержит ссылок на .fnt-файлы."
        )
    return tuple(sorted(references, key=str.casefold))


def missing_resources(
    profile_path: Path,
    output_root: Path,
) -> list[str]:
    return [
        reference
        for reference in profile_references(profile_path)
        if not (output_root / Path(reference)).is_file()
    ]


def prepare_resources(
    profile_path: Path,
    output_root: Path,
    game_root: Path,
    mod_root: Path,
) -> int:
    source_roots = {
        "base": game_root.resolve() / "gfx" / "fonts",
        "mod": mod_root.resolve() / "gfx" / "fonts",
    }
    for label, source_root in source_roots.items():
        if not source_root.is_dir():
            raise FontPreparationError(
                f"Не найдена папка {label}-шрифтов: {source_root}"
            )

    copied = 0
    absent: list[str] = []
    for reference in profile_references(profile_path):
        relative = Path(reference)
        origin = relative.parts[0]
        font_relative = Path(*relative.parts[1:])
        source = source_roots[origin] / font_relative
        destination = output_root.resolve() / relative
        if not source.is_file():
            absent.append(reference)
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        copied += 1

    if absent:
        sample = "\n".join(f"  - {item}" for item in absent[:20])
        suffix = (
            f"\n  ... и ещё {len(absent) - 20}"
            if len(absent) > 20
            else ""
        )
        raise FontPreparationError(
            "Не удалось найти часть ресурсов из профиля:\n"
            f"{sample}{suffix}"
        )
    return copied


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description=(
            "Подготовить локальные .fnt-ресурсы HOI4/EaW для "
            "LocalisationChecker."
        )
    )
    parser.add_argument(
        "--profile",
        type=Path,
        default=DEFAULT_PROFILE,
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
    )
    parser.add_argument("--game-root", type=Path)
    parser.add_argument("--mod-root", type=Path)
    parser.add_argument("--check-only", action="store_true")
    arguments = parser.parse_args()

    try:
        if arguments.check_only:
            missing = missing_resources(
                arguments.profile.resolve(),
                arguments.output.resolve(),
            )
            if missing:
                print(
                    f"Не хватает .fnt-файлов: {len(missing)}. "
                    "Запустите скрипт с --game-root и --mod-root."
                )
                return 1
            print("Все .fnt-ресурсы из профиля подготовлены.")
            return 0

        if arguments.game_root is None or arguments.mod_root is None:
            parser.error(
                "для копирования обязательны --game-root и --mod-root"
            )
        copied = prepare_resources(
            arguments.profile.resolve(),
            arguments.output.resolve(),
            arguments.game_root,
            arguments.mod_root,
        )
    except FontPreparationError as error:
        print(f"Ошибка: {error}")
        return 1

    print(f"Подготовлено .fnt-файлов: {copied}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
