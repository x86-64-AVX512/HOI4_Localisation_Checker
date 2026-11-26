from __future__ import annotations

import tkinter as tk
import unittest
from tkinter import ttk

from hoi4_l10n_checker.gui_long_text_tab import LongTextTab


class LongTextTabTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = tk.Tk()
        self.root.withdraw()
        self.tab = LongTextTab(self.root, ttk.Notebook(self.root))

    def tearDown(self) -> None:
        self.root.destroy()

    def test_automatic_parts_and_part_edits_update_full_text(self) -> None:
        self.tab.full_text.insert("1.0", "Абзац.\n\n" * 100)
        self.tab.target_var.set("200")
        self.tab.auto_split()
        original = self.tab.full_text.get("1.0", "end-1c")
        self.assertEqual(original, "".join(self.tab.branches[""]))
        self.assertGreater(len(self.tab.branches[""]), 1)
        self.tab.parts_table.selection_set("0")
        self.tab.select_part()
        self.tab.part_text.insert("end-1c", "Добавлено.")
        self.tab.commit_part()
        self.assertIn("Добавлено.", self.tab.full_text.get("1.0", "end-1c"))
        self.assertEqual(
            "".join(self.tab.branches[""]),
            self.tab.full_text.get("1.0", "end-1c"),
        )

    def test_switching_country_preserves_pending_full_text(self) -> None:
        self.tab.kind_var.set("Вступительный экран EaW")
        self.tab.change_kind()
        self.tab.branches["CRY"] = ["Кристальная."]
        self.tab.full_text.insert("1.0", "Эквестрия.")
        self.tab.tag_var.set("CRY")
        self.tab.select_branch()
        self.assertEqual("Эквестрия.", "".join(self.tab.branches["EQS"]))
        self.assertEqual("Кристальная.", self.tab.full_text.get("1.0", "end-1c"))

    def test_busy_blocks_authoring_while_checks_run(self) -> None:
        self.tab.set_busy(True)
        self.assertTrue(
            all(str(button.cget("state")) == "disabled" for button in self.tab.buttons)
        )
        self.tab.set_busy(False)
        self.assertEqual("normal", str(self.tab.key_entry.cget("state")))
        self.assertEqual("disabled", str(self.tab.add_branch_button.cget("state")))


if __name__ == "__main__":
    unittest.main()
