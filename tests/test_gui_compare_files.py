from __future__ import annotations

import tempfile
import tkinter as tk
import unittest
from pathlib import Path

from hoi4_l10n_checker.gui_compare_files import ComparisonFilesDialog


class ComparisonFilesDialogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root_path = Path(self.temporary.name)
        self.english = self.root_path / "english"
        self.russian = self.root_path / "russian"
        self.english.mkdir()
        self.russian.mkdir()
        self.root = tk.Tk()
        self.root.withdraw()

    def tearDown(self) -> None:
        self.root.destroy()
        self.temporary.cleanup()

    def test_filters_and_excludes_selected_files_without_persistence(self) -> None:
        english_music = self.english / "music_l_english.yml"
        russian_music = self.russian / "music_l_russian.yml"
        (self.english / "main_l_english.yml").touch()
        english_music.touch()
        (self.russian / "main_l_russian.yml").touch()
        russian_music.touch()
        dialog = ComparisonFilesDialog(
            self.root,
            {"english": self.english, "russian": self.russian},
            {"english": set(), "russian": set()},
        )

        dialog.filter_var.set("music")
        self.root.update_idletasks()
        visible = dialog.table.get_children("")
        self.assertEqual(2, len(visible))

        dialog.table.selection_set(visible)
        dialog._set_selected(True)
        dialog._accept()

        self.assertIsNotNone(dialog.result)
        assert dialog.result is not None
        self.assertEqual(
            {english_music.resolve()},
            dialog.result["english"],
        )
        self.assertEqual(
            {russian_music.resolve()},
            dialog.result["russian"],
        )


if __name__ == "__main__":
    unittest.main()
