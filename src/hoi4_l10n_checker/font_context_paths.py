from __future__ import annotations

import os
import re
import sys
from pathlib import Path

_MOD_NAME = re.compile(r'^\s*name\s*=\s*"([^"]+)"', re.MULTILINE)
_REPLACE_PATH = re.compile(
    r'^\s*replace_path\s*=\s*"([^"]+)"',
    re.MULTILINE,
)
_STEAM_PATH = re.compile(r'"path"\s*"((?:\\.|[^"])*)"')
_STEAM_INSTALL_DIR = re.compile(r'"installdir"\s*"((?:\\.|[^"])*)"')

__all__ = [
    "effective_data_files",
    "effective_gui_files",
    "find_hoi4_install",
    "find_mod_root",
    "is_context_root",
    "mod_display_name",
]


def is_context_root(path: Path) -> bool:
    path = path.resolve()
    return (
        (path / "descriptor.mod").is_file()
        or (path / "interface").is_dir()
        and (path / "localisation").is_dir()
    )


def find_mod_root(target: Path) -> Path | None:
    target = target.resolve()
    current = target.parent if target.is_file() else target
    for candidate in (current, *current.parents):
        if is_context_root(candidate):
            return candidate
    return None


def mod_display_name(mod_root: Path) -> str:
    descriptor = mod_root / "descriptor.mod"
    if not descriptor.is_file():
        return mod_root.name
    try:
        text = descriptor.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return mod_root.name
    match = _MOD_NAME.search(text)
    return match.group(1).strip() if match else mod_root.name


def _decode_steam_value(value: str) -> str:
    return value.replace(r"\\", "\\")


def _steam_registry_roots() -> list[Path]:
    if sys.platform != "win32":
        return []

    import winreg

    locations = (
        (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\Valve\Steam", "InstallPath"),
        (
            winreg.HKEY_LOCAL_MACHINE,
            r"Software\WOW6432Node\Valve\Steam",
            "InstallPath",
        ),
    )
    roots: list[Path] = []
    for hive, subkey, value_name in locations:
        try:
            with winreg.OpenKey(hive, subkey) as key:
                value, _ = winreg.QueryValueEx(key, value_name)
        except OSError:
            continue
        if isinstance(value, str) and value:
            roots.append(Path(value))
    return roots


def _steam_library_roots(steam_root: Path) -> list[Path]:
    roots = [steam_root]
    library_file = steam_root / "steamapps" / "libraryfolders.vdf"
    if not library_file.is_file():
        return roots
    try:
        text = library_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return roots
    roots.extend(
        Path(_decode_steam_value(match.group(1)))
        for match in _STEAM_PATH.finditer(text)
    )
    return roots


def _game_candidate(library_root: Path) -> Path:
    steamapps = library_root / "steamapps"
    manifest = steamapps / "appmanifest_394360.acf"
    install_dir = "Hearts of Iron IV"
    if manifest.is_file():
        try:
            text = manifest.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        match = _STEAM_INSTALL_DIR.search(text)
        if match:
            install_dir = _decode_steam_value(match.group(1))
    return steamapps / "common" / install_dir


def _valid_game_root(path: Path) -> bool:
    return (path / "interface").is_dir() and (
        (path / "hoi4.exe").is_file() or (path / "localisation").is_dir()
    )


def find_hoi4_install(configured_path: str = "") -> Path | None:
    direct_candidates: list[Path] = []
    if configured_path:
        direct_candidates.append(Path(configured_path))

    for environment_name in ("ProgramFiles(x86)", "ProgramFiles"):
        base = os.environ.get(environment_name)
        if base:
            direct_candidates.append(
                Path(base) / "Steam" / "steamapps" / "common" / "Hearts of Iron IV"
            )

    steam_roots = _steam_registry_roots()
    for environment_name in ("ProgramFiles(x86)", "ProgramFiles"):
        base = os.environ.get(environment_name)
        if base:
            steam_roots.append(Path(base) / "Steam")

    for steam_root in steam_roots:
        for library_root in _steam_library_roots(steam_root):
            direct_candidates.append(_game_candidate(library_root))

    seen: set[str] = set()
    for candidate in direct_candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        normalized = str(resolved).casefold()
        if normalized in seen:
            continue
        seen.add(normalized)
        if _valid_game_root(resolved):
            return resolved
    return None


def _descriptor_replace_paths(mod_root: Path) -> tuple[str, ...]:
    descriptor = mod_root / "descriptor.mod"
    if not descriptor.is_file():
        return ()
    try:
        text = descriptor.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return ()
    return tuple(
        match.group(1).replace("\\", "/").strip("/").casefold()
        for match in _REPLACE_PATH.finditer(text)
    )


def _gui_files(root: Path) -> dict[str, Path]:
    interface_root = root / "interface"
    if not interface_root.is_dir():
        return {}
    return {
        path.relative_to(interface_root).as_posix().casefold(): path
        for path in interface_root.rglob("*.gui")
        if path.is_file()
    }


def effective_gui_files(
    mod_root: Path,
    game_root: Path | None,
) -> list[Path]:
    files: dict[str, Path] = {}
    if game_root is not None and game_root.resolve() != mod_root.resolve():
        files.update(_gui_files(game_root))

    for replace_path in _descriptor_replace_paths(mod_root):
        if replace_path == "interface":
            files.clear()
            break
        if not replace_path.startswith("interface/"):
            continue
        prefix = replace_path[len("interface/") :]
        files = {
            relative: path
            for relative, path in files.items()
            if relative != prefix and not relative.startswith(prefix + "/")
        }
    files.update(_gui_files(mod_root))
    return [files[key] for key in sorted(files)]


def _data_files(root: Path, relative_root: str) -> dict[str, Path]:
    data_root = root.joinpath(*relative_root.split("/"))
    if not data_root.is_dir():
        return {}
    return {
        path.relative_to(data_root).as_posix().casefold(): path
        for path in data_root.rglob("*.txt")
        if path.is_file()
    }


def effective_data_files(
    mod_root: Path,
    game_root: Path | None,
    relative_root: str,
) -> list[Path]:
    normalized_root = relative_root.strip("/").casefold()
    files: dict[str, Path] = {}
    if game_root is not None and game_root.resolve() != mod_root.resolve():
        files.update(_data_files(game_root, normalized_root))

    for replace_path in _descriptor_replace_paths(mod_root):
        if replace_path == normalized_root:
            files.clear()
            break
        if not replace_path.startswith(normalized_root + "/"):
            continue
        prefix = replace_path[len(normalized_root) + 1 :]
        files = {
            relative: path
            for relative, path in files.items()
            if relative != prefix and not relative.startswith(prefix + "/")
        }

    files.update(_data_files(mod_root, normalized_root))
    return [files[key] for key in sorted(files)]
