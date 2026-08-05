from __future__ import annotations

import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from tkinter import ttk

from hoi4_l10n_checker.gui_layout_tab import TextLayoutTab
from hoi4_l10n_checker.models import Diagnostic
from hoi4_l10n_checker.text_layout_checker import (
    TextLayoutOptions,
    TextLayoutResult,
)


class TextLayoutTabTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root_path = Path(self.temporary.name)
        self.root = tk.Tk()
        self.root.withdraw()
        self.notebook = ttk.Notebook(self.root)
        self.tab = TextLayoutTab(
            root=self.root,
            notebook=self.notebook,
            options=TextLayoutOptions(),
            on_choose_file=lambda: None,
            on_choose_folder=lambda: None,
            on_controls_changed=lambda _event=None: "break",
            on_select_context_mod=lambda: None,
            on_select_preview_cli=lambda: None,
            on_open_diagnostic=lambda _diagnostic, _status: "break",
            on_export=lambda _table, _prefix, _status: None,
        )
        self.root.update_idletasks()

    def tearDown(self) -> None:
        self.root.destroy()
        self.temporary.cleanup()

    def test_captures_options_and_updates_control_states(self) -> None:
        options = self.tab.capture_options("")

        self.assertEqual("length", options.focus_mode)
        self.assertEqual(350, options.focus_limit)
        self.assertEqual("auto_ru", options.focus_preview_priority)
        self.assertEqual(
            "disabled",
            str(self.tab.preview_cli_button.cget("state")),
        )

        self.tab.focus_mode_var.set("exact")
        self.tab.refresh_controls()
        self.assertEqual(
            "normal",
            str(self.tab.preview_cli_button.cget("state")),
        )
        self.assertEqual(
            "disabled",
            str(self.tab.focus_limit_entry.cget("state")),
        )

        self.tab.event_limit_var.set("не число")
        with self.assertRaisesRegex(ValueError, "ивентов"):
            self.tab.capture_options("")

        self.tab.event_limit_var.set("3400")
        self.tab.focus_enabled_var.set(False)
        self.tab.events_enabled_var.set(False)
        self.tab.welcome_enabled_var.set(False)
        self.tab.refresh_controls()
        self.assertEqual("disabled", str(self.tab.file_button.cget("state")))

    def test_presents_and_sorts_layout_results(self) -> None:
        diagnostics = [
            self._diagnostic("SHORT_KEY", 200, 10),
            self._diagnostic("LONG_KEY", 500, 20),
        ]
        result = TextLayoutResult(
            root=self.root_path,
            files_checked=3,
            entries_checked=30,
            focus_checked=10,
            events_checked=12,
            welcome_checked=8,
            diagnostics=diagnostics,
            context_gui_files=4,
            context_script_files=5,
        )

        self.tab.show_result(result)
        self.tab.sort_by_length()

        visible_keys = [
            self.tab.table.set(item, "key")
            for item in self.tab.table.get_children("")
        ]
        self.assertEqual(["LONG_KEY", "SHORT_KEY"], visible_keys)
        self.assertIn("Файлов: 3", self.tab.summary_var.get())
        self.assertIn("GUI-файлов: 4", self.tab.current_file_var.get())
        self.assertEqual(
            "normal",
            str(self.tab.export_button.cget("state")),
        )

    def _diagnostic(self, key: str, length: int, line: int) -> Diagnostic:
        return Diagnostic(
            severity="warning",
            code="TEXT_TOO_LONG",
            path=self.root_path / "sample.yml",
            line=line,
            column=3,
            message=f"{key} is too long",
            key=key,
            text_kind="Фокус",
            measured_length=length,
            limit=350,
            role_confidence="Высокая",
            role_evidence="test fixture",
        )


if __name__ == "__main__":
    unittest.main()
