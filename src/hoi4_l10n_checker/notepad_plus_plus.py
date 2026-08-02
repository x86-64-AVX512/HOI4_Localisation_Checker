from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


class NotepadPlusPlusError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class OpenResult:
    exact_position_set: bool
    character_selected: bool


def _set_notepad_fullscreen(
    notepad_window: int,
    fullscreen: bool,
) -> None:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    send_message = user32.SendMessageW
    send_message.restype = ctypes.c_ssize_t
    send_message.argtypes = [
        wintypes.HWND,
        wintypes.UINT,
        ctypes.c_size_t,
        ctypes.c_ssize_t,
    ]
    get_window_long = user32.GetWindowLongPtrW
    get_window_long.restype = ctypes.c_ssize_t
    get_window_long.argtypes = [wintypes.HWND, ctypes.c_int]

    wm_user = 0x0400
    nppmsg = wm_user + 1000
    nppm_menu_command = nppmsg + 48
    idm_view_fullscreen_toggle = 44032
    gwl_style = -16
    ws_caption = 0x00C00000

    style = get_window_long(wintypes.HWND(notepad_window), gwl_style)
    currently_fullscreen = not bool(style & ws_caption)
    if currently_fullscreen != fullscreen:
        send_message(
            wintypes.HWND(notepad_window),
            nppm_menu_command,
            0,
            idm_view_fullscreen_toggle,
        )


def _registry_candidates() -> list[Path]:
    if sys.platform != "win32":
        return []

    import winreg

    candidates: list[Path] = []
    subkey = r"Software\Microsoft\Windows\CurrentVersion\App Paths\notepad++.exe"
    access_modes = (
        winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0),
        winreg.KEY_READ | getattr(winreg, "KEY_WOW64_32KEY", 0),
    )
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for access in access_modes:
            try:
                with winreg.OpenKey(hive, subkey, 0, access) as key:
                    value, _ = winreg.QueryValueEx(key, None)
            except OSError:
                continue
            if isinstance(value, str) and value:
                candidates.append(Path(value))
    return candidates


def find_notepad_plus_plus(configured_path: str = "") -> Path | None:
    candidates: list[Path] = []
    if configured_path:
        candidates.append(Path(configured_path))

    from_path = shutil.which("notepad++.exe")
    if from_path:
        candidates.append(Path(from_path))
    candidates.extend(_registry_candidates())

    for environment_name in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        base = os.environ.get(environment_name)
        if not base:
            continue
        if environment_name == "LOCALAPPDATA":
            candidates.append(Path(base) / "Programs" / "Notepad++" / "notepad++.exe")
        else:
            candidates.append(Path(base) / "Notepad++" / "notepad++.exe")

    seen: set[str] = set()
    for candidate in candidates:
        normalized = str(candidate).casefold()
        if normalized in seen:
            continue
        seen.add(normalized)
        if candidate.is_file():
            return candidate.resolve()
    return None


def _notepad_window_for_file(file_name: str) -> int | None:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(
        wintypes.BOOL,
        wintypes.HWND,
        wintypes.LPARAM,
    )
    enum_windows = user32.EnumWindows
    enum_windows.restype = wintypes.BOOL
    enum_windows.argtypes = [callback_type, wintypes.LPARAM]
    get_class_name = user32.GetClassNameW
    get_class_name.restype = ctypes.c_int
    get_class_name.argtypes = [
        wintypes.HWND,
        wintypes.LPWSTR,
        ctypes.c_int,
    ]
    get_window_text = user32.GetWindowTextW
    get_window_text.restype = ctypes.c_int
    get_window_text.argtypes = [
        wintypes.HWND,
        wintypes.LPWSTR,
        ctypes.c_int,
    ]
    is_window_visible = user32.IsWindowVisible
    is_window_visible.restype = wintypes.BOOL
    is_window_visible.argtypes = [wintypes.HWND]

    windows: list[tuple[int, str]] = []

    @callback_type
    def callback(hwnd: int, _lparam: int) -> bool:
        class_buffer = ctypes.create_unicode_buffer(64)
        get_class_name(hwnd, class_buffer, len(class_buffer))
        if class_buffer.value != "Notepad++" or not is_window_visible(hwnd):
            return True
        title_buffer = ctypes.create_unicode_buffer(2048)
        get_window_text(hwnd, title_buffer, len(title_buffer))
        windows.append((int(hwnd), title_buffer.value))
        return True

    enum_windows(callback, 0)
    expected = file_name.casefold()
    for hwnd, title in windows:
        if expected in title.casefold():
            return hwnd
    return None


def _focused_scintilla(notepad_window: int) -> int | None:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)

    class GuiThreadInfo(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("flags", wintypes.DWORD),
            ("hwndActive", wintypes.HWND),
            ("hwndFocus", wintypes.HWND),
            ("hwndCapture", wintypes.HWND),
            ("hwndMenuOwner", wintypes.HWND),
            ("hwndMoveSize", wintypes.HWND),
            ("hwndCaret", wintypes.HWND),
            ("rcCaret", wintypes.RECT),
        ]

    process_id = wintypes.DWORD()
    get_window_thread_process_id = user32.GetWindowThreadProcessId
    get_window_thread_process_id.restype = wintypes.DWORD
    get_window_thread_process_id.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(wintypes.DWORD),
    ]
    thread_id = get_window_thread_process_id(
        wintypes.HWND(notepad_window),
        ctypes.byref(process_id),
    )
    if not thread_id:
        return None

    info = GuiThreadInfo()
    info.cbSize = ctypes.sizeof(info)
    get_gui_thread_info = user32.GetGUIThreadInfo
    get_gui_thread_info.restype = wintypes.BOOL
    get_gui_thread_info.argtypes = [
        wintypes.DWORD,
        ctypes.POINTER(GuiThreadInfo),
    ]
    if not get_gui_thread_info(thread_id, ctypes.byref(info)):
        return None

    focused = int(info.hwndFocus or 0)
    if not focused:
        return None
    class_buffer = ctypes.create_unicode_buffer(64)
    get_class_name = user32.GetClassNameW
    get_class_name.restype = ctypes.c_int
    get_class_name.argtypes = [
        wintypes.HWND,
        wintypes.LPWSTR,
        ctypes.c_int,
    ]
    get_class_name(wintypes.HWND(focused), class_buffer, len(class_buffer))
    return focused if class_buffer.value == "Scintilla" else None


def _set_scintilla_location(
    notepad_window: int,
    line: int,
    column: int,
    selection_length: int,
    fullscreen: bool,
) -> bool:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    show_window = user32.ShowWindow
    show_window.restype = wintypes.BOOL
    show_window.argtypes = [wintypes.HWND, ctypes.c_int]
    set_foreground_window = user32.SetForegroundWindow
    set_foreground_window.restype = wintypes.BOOL
    set_foreground_window.argtypes = [wintypes.HWND]

    sw_restore = 9
    is_iconic = user32.IsIconic
    is_iconic.restype = wintypes.BOOL
    is_iconic.argtypes = [wintypes.HWND]
    if is_iconic(wintypes.HWND(notepad_window)):
        show_window(wintypes.HWND(notepad_window), sw_restore)
    _set_notepad_fullscreen(notepad_window, fullscreen)
    set_foreground_window(wintypes.HWND(notepad_window))

    scintilla = _focused_scintilla(notepad_window)
    if scintilla is None:
        return False

    send_message = user32.SendMessageW
    send_message.restype = ctypes.c_ssize_t
    send_message.argtypes = [
        wintypes.HWND,
        wintypes.UINT,
        ctypes.c_size_t,
        ctypes.c_ssize_t,
    ]

    sci_position_from_line = 2167
    sci_set_sel = 2160
    sci_grab_focus = 2400
    sci_position_relative = 2670

    line_start = send_message(
        wintypes.HWND(scintilla),
        sci_position_from_line,
        max(line - 1, 0),
        0,
    )
    if line_start < 0:
        return False
    selection_start = send_message(
        wintypes.HWND(scintilla),
        sci_position_relative,
        line_start,
        max(column - 1, 0),
    )
    selection_end = selection_start
    if selection_length > 0:
        selection_end = send_message(
            wintypes.HWND(scintilla),
            sci_position_relative,
            selection_start,
            selection_length,
        )

    send_message(
        wintypes.HWND(scintilla),
        sci_set_sel,
        selection_start,
        selection_end,
    )
    send_message(wintypes.HWND(scintilla), sci_grab_focus, 0, 0)
    set_foreground_window(wintypes.HWND(notepad_window))
    return True


def open_location(
    executable: Path,
    file_path: Path,
    line: int,
    column: int,
    select_character: bool = False,
    selection_length: int = 0,
    fullscreen: bool = False,
    wait_seconds: float = 6.0,
) -> OpenResult:
    if sys.platform != "win32":
        raise NotepadPlusPlusError("Открытие в Notepad++ поддерживается только в Windows.")
    if not executable.is_file():
        raise NotepadPlusPlusError(f"Не найден Notepad++: {executable}")
    if not file_path.is_file():
        raise NotepadPlusPlusError(f"Не найден файл диагностики: {file_path}")

    try:
        subprocess.Popen(
            [
                str(executable),
                f"-n{max(line, 1)}",
                f"-c{max(column, 1)}",
                str(file_path),
            ],
        )
    except OSError as error:
        raise NotepadPlusPlusError(f"Не удалось запустить Notepad++: {error}") from error

    deadline = time.monotonic() + max(wait_seconds, 0.0)
    requested_selection_length = max(
        selection_length,
        1 if select_character else 0,
    )
    while time.monotonic() <= deadline:
        window = _notepad_window_for_file(file_path.name)
        if window is not None and _set_scintilla_location(
            window,
            line=line,
            column=column,
            selection_length=requested_selection_length,
            fullscreen=fullscreen,
        ):
            return OpenResult(
                exact_position_set=True,
                character_selected=requested_selection_length > 0,
            )
        time.sleep(0.05)

    return OpenResult(
        exact_position_set=False,
        character_selected=False,
    )
