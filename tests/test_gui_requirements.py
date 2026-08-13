from __future__ import annotations

import tkinter as tk
import unittest

from hoi4_l10n_checker.gui_requirements import RequirementIndicator


class RequirementIndicatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = tk.Tk()
        self.root.withdraw()
        self.indicator = RequirementIndicator(self.root)

    def tearDown(self) -> None:
        self.indicator.stop_flashing()
        self.root.destroy()

    def test_uses_checkmark_and_cross_for_requirement_state(self) -> None:
        self.indicator.set(False, "путь не выбран")
        self.assertEqual("✕ путь не выбран", self.indicator.variable.get())

        self.indicator.set(True, r"C:\Mod")
        self.assertEqual("✓ C:\\Mod", self.indicator.variable.get())

    def test_invalid_requirement_flashes_lava_red(self) -> None:
        self.indicator.set(False, "путь не выбран")

        self.indicator.flash(cycles=1, interval_ms=1)

        self.assertEqual("#CF1020", self.indicator.widget.cget("background"))
        self.indicator.stop_flashing()
        self.assertNotEqual(
            "#CF1020",
            self.indicator.widget.cget("background"),
        )


if __name__ == "__main__":
    unittest.main()
