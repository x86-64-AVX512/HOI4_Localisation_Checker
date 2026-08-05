from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from hoi4_l10n_checker.font_context_paths import (
    effective_data_files,
    effective_gui_files,
    find_mod_root,
    is_context_root,
    mod_display_name,
)


class FontContextPathTests(unittest.TestCase):
    def test_mod_metadata_and_nearest_root_are_resolved(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            mod_root = Path(temporary) / "example_mod"
            target = mod_root / "localisation" / "english" / "sample.yml"
            target.parent.mkdir(parents=True)
            target.write_text("l_english:\n", encoding="utf-8")
            (mod_root / "descriptor.mod").write_text(
                'name="Example Mod"\n',
                encoding="utf-8",
            )

            self.assertTrue(is_context_root(mod_root))
            self.assertEqual(mod_root.resolve(), find_mod_root(target))
            self.assertEqual("Example Mod", mod_display_name(mod_root))

    def test_effective_files_apply_mod_overrides_and_replace_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            game_root = root / "game"
            mod_root = root / "mod"
            self._write(game_root / "interface" / "base.gui")
            self._write(game_root / "interface" / "sub" / "hidden.gui")
            self._write(mod_root / "interface" / "base.gui")
            self._write(mod_root / "interface" / "mod.gui")
            self._write(game_root / "common" / "ideas" / "base.txt")
            self._write(game_root / "common" / "ideas" / "sub" / "hidden.txt")
            self._write(mod_root / "common" / "ideas" / "base.txt")
            self._write(mod_root / "common" / "ideas" / "extra.txt")
            (mod_root / "descriptor.mod").write_text(
                'replace_path="interface/sub"\nreplace_path="common/ideas/sub"\n',
                encoding="utf-8",
            )

            gui_files = effective_gui_files(mod_root, game_root)
            data_files = effective_data_files(
                mod_root,
                game_root,
                "common/ideas",
            )

            self.assertEqual(
                [
                    mod_root / "interface" / "base.gui",
                    mod_root / "interface" / "mod.gui",
                ],
                gui_files,
            )
            self.assertEqual(
                [
                    mod_root / "common" / "ideas" / "base.txt",
                    mod_root / "common" / "ideas" / "extra.txt",
                ],
                data_files,
            )

    @staticmethod
    def _write(path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("test", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
