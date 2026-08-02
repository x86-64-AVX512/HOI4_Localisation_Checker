from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hoi4_l10n_checker.notepad_plus_plus import (
    find_notepad_plus_plus,
    open_location,
)


class NotepadPlusPlusTests(unittest.TestCase):
    def test_configured_executable_is_preferred(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            executable = Path(temporary) / "notepad++.exe"
            executable.write_bytes(b"test")

            found = find_notepad_plus_plus(str(executable))

            self.assertEqual(executable.resolve(), found)

    def test_open_location_uses_line_column_and_requests_selection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            executable = root / "notepad++.exe"
            file_path = root / "sample.yml"
            executable.write_bytes(b"test")
            file_path.write_text("line one\nline two\n", encoding="utf-8")

            with (
                patch(
                    "hoi4_l10n_checker.notepad_plus_plus.subprocess.Popen"
                ) as popen,
                patch(
                    "hoi4_l10n_checker.notepad_plus_plus._notepad_window_for_file",
                    return_value=123,
                ),
                patch(
                    "hoi4_l10n_checker.notepad_plus_plus._set_scintilla_location",
                    return_value=True,
                ) as set_location,
            ):
                result = open_location(
                    executable,
                    file_path,
                    line=2,
                    column=6,
                    select_character=True,
                    fullscreen=True,
                    wait_seconds=0.1,
                )

            popen.assert_called_once_with(
                [
                    str(executable),
                    "-n2",
                    "-c6",
                    str(file_path),
                ]
            )
            set_location.assert_called_once_with(
                123,
                line=2,
                column=6,
                selection_length=1,
                fullscreen=True,
            )
            self.assertTrue(result.exact_position_set)
            self.assertTrue(result.character_selected)


if __name__ == "__main__":
    unittest.main()
