from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from hoi4_l10n_checker.settings import (
    AppSettings,
    load_excluded_characters,
    load_settings,
    save_excluded_characters,
    save_settings,
    settings_path_for,
)


class SettingsTests(unittest.TestCase):
    def test_settings_path_is_inside_application_folder(self) -> None:
        app_root = Path("portable") / "LocalisationChecker"

        self.assertEqual(
            app_root / "settings.json",
            settings_path_for(app_root),
        )

    def test_excluded_characters_are_saved_and_loaded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "settings" / "settings.json"
            expected = frozenset({"—", "…", "\u200b", "🦄"})

            save_excluded_characters(path, expected)
            loaded = load_excluded_characters(path)

            self.assertEqual(expected, loaded)

    def test_missing_settings_file_has_no_exclusions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "missing.json"

            self.assertEqual(frozenset(), load_excluded_characters(path))

    def test_editor_settings_are_saved_and_preserved_by_exception_updates(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "settings.json"
            editor = r"C:\Portable\Notepad++\notepad++.exe"
            save_settings(
                path,
                AppSettings(
                    excluded_characters=frozenset({"—"}),
                    notepad_plus_plus_path=editor,
                    notepad_plus_plus_fullscreen=True,
                    context_mod_path=r"C:\Mods\eaw_dev",
                    hoi4_install_path=r"D:\Steam\Hearts of Iron IV",
                    show_unknown_context_warnings=True,
                    layout_focus_enabled=True,
                    layout_focus_mode="newline",
                    layout_focus_limit=347,
                    layout_focus_preview_cli_path=(
                        r"C:\Preview\EaWFocusTextPreviewCLI.exe"
                    ),
                    layout_focus_preview_priority="auto_en",
                    layout_events_enabled=False,
                    layout_event_limit=3300,
                    layout_welcome_enabled=True,
                    layout_welcome_limit=3350,
                    compare_english_path=r"C:\Mod\localisation\english",
                    compare_russian_path=r"C:\Mod\localisation\russian",
                    export_directory=r"D:\Checker exports",
                ),
            )

            save_excluded_characters(path, {"…"})
            loaded = load_settings(path)

            self.assertEqual(frozenset({"…"}), loaded.excluded_characters)
            self.assertEqual(editor, loaded.notepad_plus_plus_path)
            self.assertTrue(loaded.notepad_plus_plus_fullscreen)
            self.assertEqual(r"C:\Mods\eaw_dev", loaded.context_mod_path)
            self.assertEqual(
                r"D:\Steam\Hearts of Iron IV",
                loaded.hoi4_install_path,
            )
            self.assertTrue(loaded.show_unknown_context_warnings)
            self.assertTrue(loaded.layout_focus_enabled)
            self.assertEqual("newline", loaded.layout_focus_mode)
            self.assertEqual(347, loaded.layout_focus_limit)
            self.assertEqual(
                r"C:\Preview\EaWFocusTextPreviewCLI.exe",
                loaded.layout_focus_preview_cli_path,
            )
            self.assertEqual(
                "auto_en",
                loaded.layout_focus_preview_priority,
            )
            self.assertFalse(loaded.layout_events_enabled)
            self.assertEqual(3300, loaded.layout_event_limit)
            self.assertTrue(loaded.layout_welcome_enabled)
            self.assertEqual(3350, loaded.layout_welcome_limit)
            self.assertEqual(
                r"C:\Mod\localisation\english",
                loaded.compare_english_path,
            )
            self.assertEqual(
                r"C:\Mod\localisation\russian",
                loaded.compare_russian_path,
            )
            self.assertEqual(
                r"D:\Checker exports",
                loaded.export_directory,
            )
            self.assertNotIn(
                "layout_focus_preview_policy",
                json.loads(path.read_text(encoding="utf-8")),
            )

    def test_editor_is_not_fullscreen_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "settings.json"
            path.write_text(
                (
                    '{\n'
                    '  "format_version": 1,\n'
                    '  "excluded_characters": [],\n'
                    '  "notepad_plus_plus_path": ""\n'
                    '}\n'
                ),
                encoding="utf-8",
            )

            self.assertFalse(load_settings(path).notepad_plus_plus_fullscreen)
            self.assertFalse(
                load_settings(path).show_unknown_context_warnings
            )
            self.assertTrue(load_settings(path).layout_focus_enabled)
            self.assertEqual("length", load_settings(path).layout_focus_mode)
            self.assertEqual(350, load_settings(path).layout_focus_limit)
            self.assertEqual(
                "",
                load_settings(path).layout_focus_preview_cli_path,
            )
            self.assertEqual(
                "auto_ru",
                load_settings(path).layout_focus_preview_priority,
            )
            self.assertTrue(load_settings(path).layout_events_enabled)
            self.assertEqual(3400, load_settings(path).layout_event_limit)
            self.assertTrue(load_settings(path).layout_welcome_enabled)
            self.assertEqual(3400, load_settings(path).layout_welcome_limit)
            self.assertEqual("", load_settings(path).compare_english_path)
            self.assertEqual("", load_settings(path).compare_russian_path)
            self.assertEqual("", load_settings(path).export_directory)

    def test_legacy_cli_policy_is_ignored_and_not_saved(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "settings.json"
            path.write_text(
                json.dumps(
                    {
                        "format_version": 1,
                        "excluded_characters": [],
                        "layout_focus_preview_policy": "strict",
                    }
                ),
                encoding="utf-8",
            )

            settings = load_settings(path)
            save_settings(path, settings)

            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertNotIn("layout_focus_preview_policy", saved)


if __name__ == "__main__":
    unittest.main()
