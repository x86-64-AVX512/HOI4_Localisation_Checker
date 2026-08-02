from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.prepare_font_resources import (
    FontPreparationError,
    missing_resources,
    prepare_resources,
    profile_references,
)


class PrepareFontResourcesTests(unittest.TestCase):
    @staticmethod
    def write_profile(path: Path, references: list[str]) -> None:
        path.write_text(
            json.dumps(
                {
                    "languages": {
                        "l_english": {
                            "families": {"test": references}
                        }
                    }
                }
            ),
            encoding="utf-8",
        )

    def test_copies_only_profile_resources(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            profile = root / "font_profile.json"
            output = root / "fonts"
            game = root / "game"
            mod = root / "mod"
            base_font = game / "gfx" / "fonts" / "base_font.fnt"
            mod_font = mod / "gfx" / "fonts" / "mod_font.fnt"
            base_font.parent.mkdir(parents=True)
            mod_font.parent.mkdir(parents=True)
            base_font.write_text("base", encoding="utf-8")
            mod_font.write_text("mod", encoding="utf-8")
            self.write_profile(
                profile,
                ["base/base_font.fnt", "mod/mod_font.fnt"],
            )

            copied = prepare_resources(
                profile,
                output,
                game,
                mod,
            )

            self.assertEqual(2, copied)
            self.assertEqual(
                "base",
                (output / "base" / "base_font.fnt").read_text(
                    encoding="utf-8"
                ),
            )
            self.assertEqual(
                "mod",
                (output / "mod" / "mod_font.fnt").read_text(
                    encoding="utf-8"
                ),
            )
            self.assertEqual([], missing_resources(profile, output))

    def test_rejects_paths_outside_font_resource_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            profile = Path(temporary) / "font_profile.json"
            self.write_profile(profile, ["base/../secret.fnt"])

            with self.assertRaises(FontPreparationError):
                profile_references(profile)


if __name__ == "__main__":
    unittest.main()
