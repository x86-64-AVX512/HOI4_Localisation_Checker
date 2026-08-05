from __future__ import annotations

import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from tkinter import ttk

from hoi4_l10n_checker.checker import ScanResult
from hoi4_l10n_checker.gui_check_tab import LocalisationCheckTab
from hoi4_l10n_checker.models import Diagnostic


class LocalisationCheckTabTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root_path = Path(self.temporary.name)
        self.root = tk.Tk()
        self.root.withdraw()
        self.notebook = ttk.Notebook(self.root)
        self.opened: list[Diagnostic | None] = []
        self.tab = LocalisationCheckTab(
            root=self.root,
            notebook=self.notebook,
            font_available=True,
            font_status="Профиль шрифтов загружен.",
            show_unknown_context=False,
            check_russian_straight_quotes=True,
            notepad_fullscreen=False,
            on_choose_file=lambda: None,
            on_choose_folder=lambda: None,
            on_open_exceptions=lambda: None,
            on_select_context_mod=lambda: None,
            on_unknown_context_changed=lambda: None,
            on_russian_quotes_changed=lambda: None,
            on_notepad_mode_changed=lambda: None,
            on_open_diagnostic=self._record_open,
            on_add_selected_exception=lambda: None,
            is_character_excluded=lambda _character: False,
            on_export=lambda _table, _prefix, _status: None,
        )
        self.root.update_idletasks()

    def tearDown(self) -> None:
        self.root.destroy()
        self.temporary.cleanup()

    def test_controls_follow_busy_state_and_keep_selected_mode(self) -> None:
        self.tab.glyph_mode_var.set("contextual")
        self.assertEqual("contextual", self.tab.glyph_mode())
        self.assertTrue(self.tab.russian_straight_quotes_var.get())

        self.tab.set_busy(True)
        self.assertEqual("disabled", str(self.tab.file_button.cget("state")))
        self.assertEqual(
            "disabled",
            str(self.tab.contextual_mode_button.cget("state")),
        )

        self.tab.set_busy(False)
        self.assertEqual("normal", str(self.tab.file_button.cget("state")))
        self.assertEqual(
            "normal",
            str(self.tab.contextual_mode_button.cget("state")),
        )
        self.assertEqual("contextual", self.tab.glyph_mode())

    def test_presents_diagnostics_and_exposes_selected_glyph(self) -> None:
        diagnostic = Diagnostic(
            severity="warning",
            code="UNSAFE_GLYPH",
            path=self.root_path / "sample.yml",
            line=12,
            column=34,
            message="Небезопасный символ «…».",
            key="TEST_KEY",
            character="…",
        )
        result = ScanResult(
            root=self.root_path,
            files_checked=3,
            entries_checked=20,
            diagnostics=[diagnostic],
        )

        self.tab.show_result(result, "soft")
        item = self.tab.table.get_children("")[0]
        self.tab.table.selection_set(item)
        self.tab.show_selected_detail()

        self.assertEqual("TEST_KEY", self.tab.selected_key())
        self.assertEqual("…", self.tab.selected_character())
        self.assertIn("sample.yml:12:34", self.tab.detail_var.get())
        self.assertIn("Файлов: 3", self.tab.summary_var.get())
        self.assertEqual(
            "normal",
            str(self.tab.copy_character_button.cget("state")),
        )
        self.assertEqual(
            "normal",
            str(self.tab.export_button.cget("state")),
        )

        self.assertEqual("break", self.tab.open_selected_diagnostic())
        self.assertEqual([diagnostic], self.opened)

    def _record_open(
        self,
        diagnostic: Diagnostic | None,
        _status_var: tk.StringVar,
    ) -> str:
        self.opened.append(diagnostic)
        return "break"


if __name__ == "__main__":
    unittest.main()
