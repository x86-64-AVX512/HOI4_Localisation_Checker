from __future__ import annotations

import tkinter as tk
import unittest

from hoi4_l10n_checker.gui_exceptions import (
    CharacterExceptionsController,
)
from hoi4_l10n_checker.settings import SettingsError


class CharacterExceptionsControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = tk.Tk()
        self.root.withdraw()
        self.persist_count = 0
        self.persisted_characters: list[frozenset[str]] = []
        self.counts: list[int] = []
        self.statuses: list[str] = []
        self.errors: list[tuple[str, str]] = []
        self.selected_character = "…"
        self.controller = CharacterExceptionsController(
            root=self.root,
            characters={"—"},
            persist=self._persist,
            set_count=self.counts.append,
            set_status=self.statuses.append,
            selected_character=lambda: self.selected_character,
            show_error=lambda title, message: self.errors.append(
                (title, message)
            ),
        )

    def tearDown(self) -> None:
        self.controller.close_dialog()
        self.root.update_idletasks()
        self.root.destroy()

    def _persist(self, characters: frozenset[str]) -> None:
        self.persist_count += 1
        self.persisted_characters.append(characters)

    def test_character_labels_explain_special_and_printable_symbols(
        self,
    ) -> None:
        self.assertIn(
            "обычный пробел — U+0020",
            self.controller.character_label(" "),
        )
        self.assertIn(
            "неразрывный пробел — U+00A0",
            self.controller.character_label("\u00a0"),
        )
        self.assertIn(
            "пробел нулевой ширины — U+200B",
            self.controller.character_label("\u200b"),
        )
        self.assertIn(
            "«…» — U+2026",
            self.controller.character_label("…"),
        )

    def test_add_text_persists_new_characters_and_updates_status(self) -> None:
        added = self.controller.add_text("…«…")

        self.assertTrue(added)
        self.assertEqual(frozenset({"—", "…", "«"}), self.controller.characters)
        self.assertEqual(1, self.persist_count)
        self.assertEqual(self.controller.characters, self.persisted_characters[-1])
        self.assertEqual(3, self.counts[-1])
        self.assertIn("U+00AB, U+2026", self.statuses[-1])

        self.assertFalse(self.controller.add_text("…"))
        self.assertEqual(1, self.persist_count)

    def test_failed_save_restores_previous_characters(self) -> None:
        def fail(_characters: frozenset[str]) -> None:
            raise SettingsError("test failure")

        controller = CharacterExceptionsController(
            root=self.root,
            characters={"—"},
            persist=fail,
            set_count=self.counts.append,
            set_status=self.statuses.append,
            selected_character=lambda: "…",
            show_error=lambda title, message: self.errors.append(
                (title, message)
            ),
        )

        added = controller.add_text("…")

        self.assertFalse(added)
        self.assertEqual(frozenset({"—"}), controller.characters)
        self.assertEqual(1, self.counts[-1])
        self.assertEqual("Исключения не сохранены", self.errors[-1][0])

    def test_dialog_lists_and_removes_selected_character(self) -> None:
        self.controller.add_text("«")
        self.controller.open_dialog()
        self.root.update_idletasks()

        self.assertIsNotNone(self.controller.listbox)
        listbox = self.controller.listbox
        assert listbox is not None
        self.assertEqual(2, listbox.size())
        listbox.selection_set(0)

        self.controller.remove_selected()

        self.assertEqual(frozenset({"—"}), self.controller.characters)
        self.assertEqual(1, listbox.size())
        self.assertIn("U+00AB", self.statuses[-1])

    def test_add_selected_character_uses_current_table_selection(self) -> None:
        self.controller.add_selected_character()

        self.assertIn("…", self.controller.characters)
        self.assertEqual(1, self.persist_count)


if __name__ == "__main__":
    unittest.main()
