from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hoi4_l10n_checker.settings import (
    CURRENT_SETTINGS_FORMAT_VERSION,
    AppSettings,
    SettingsError,
    SettingsStore,
    load_excluded_characters,
    load_settings,
    save_excluded_characters,
    save_settings,
    settings_path_for,
)


class SettingsTests(unittest.TestCase):
    def test_settings_store_updates_one_snapshot_without_losing_fields(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "settings.json"
            save_settings(
                path,
                AppSettings(
                    context_mod_path=r"C:\Mods\EaW",
                    layout_focus_limit=350,
                ),
            )
            store = SettingsStore.load(path)

            updated = store.update(layout_focus_limit=365)

            self.assertIs(updated, store.current)
            self.assertEqual(365, updated.layout_focus_limit)
            self.assertEqual(r"C:\Mods\EaW", updated.context_mod_path)
            self.assertEqual(updated, load_settings(path))

    def test_settings_store_keeps_memory_snapshot_when_save_fails(
        self,
    ) -> None:
        path = Path("settings.json")
        original = AppSettings(export_directory=r"C:\Old")
        store = SettingsStore(path, original)

        with patch(
            "hoi4_l10n_checker.settings.save_settings",
            side_effect=SettingsError("simulated failure"),
        ):
            with self.assertRaisesRegex(SettingsError, "simulated failure"):
                store.update(export_directory=r"D:\New")

        self.assertIs(original, store.current)

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
                    check_russian_straight_quotes=False,
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
                    layout_english_path=r"C:\Mod\localisation\english",
                    layout_russian_path=r"C:\Mod\localisation\russian",
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
            self.assertFalse(loaded.check_russian_straight_quotes)
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
                loaded.layout_english_path,
            )
            self.assertEqual(
                r"C:\Mod\localisation\russian",
                loaded.layout_russian_path,
            )
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
            self.assertTrue(
                load_settings(path).check_russian_straight_quotes
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
            self.assertEqual("", load_settings(path).layout_english_path)
            self.assertEqual("", load_settings(path).layout_russian_path)
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
            self.assertEqual(
                CURRENT_SETTINGS_FORMAT_VERSION,
                saved["format_version"],
            )

    def test_settings_without_version_are_migrated_from_version_one(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "settings.json"
            path.write_text(
                json.dumps(
                    {
                        "excluded_characters": ["…"],
                        "notepad_plus_plus_fullscreen": True,
                    }
                ),
                encoding="utf-8",
            )

            settings = load_settings(path)
            save_settings(path, settings)
            saved = json.loads(path.read_text(encoding="utf-8"))

            self.assertEqual(frozenset({"…"}), settings.excluded_characters)
            self.assertTrue(settings.notepad_plus_plus_fullscreen)
            self.assertEqual(
                CURRENT_SETTINGS_FORMAT_VERSION,
                saved["format_version"],
            )

    def test_newer_settings_format_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "settings.json"
            path.write_text(
                json.dumps(
                    {
                        "format_version": (
                            CURRENT_SETTINGS_FORMAT_VERSION + 1
                        ),
                        "excluded_characters": [],
                    }
                ),
                encoding="utf-8",
            )
            original = path.read_bytes()

            with self.assertRaisesRegex(
                SettingsError,
                "новее поддерживаемого",
            ):
                load_settings(path)
            with self.assertRaisesRegex(
                SettingsError,
                "новее поддерживаемого",
            ):
                save_settings(path, AppSettings())
            self.assertEqual(original, path.read_bytes())

    def test_invalid_settings_root_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "settings.json"
            path.write_text("[]\n", encoding="utf-8")
            original = path.read_bytes()

            with self.assertRaisesRegex(
                SettingsError,
                "должно быть объектом JSON",
            ):
                load_settings(path)
            with self.assertRaisesRegex(
                SettingsError,
                "должно быть объектом JSON",
            ):
                save_settings(path, AppSettings())
            self.assertEqual(original, path.read_bytes())

    def test_failed_atomic_replace_preserves_existing_settings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "settings.json"
            save_settings(
                path,
                AppSettings(export_directory=r"C:\Old exports"),
            )
            original = path.read_bytes()

            with patch(
                "hoi4_l10n_checker.settings.os.replace",
                side_effect=OSError("simulated replace failure"),
            ):
                with self.assertRaisesRegex(
                    SettingsError,
                    "simulated replace failure",
                ):
                    save_settings(
                        path,
                        AppSettings(export_directory=r"D:\New exports"),
                    )

            self.assertEqual(original, path.read_bytes())
            self.assertEqual(
                [],
                list(root.glob(".settings.json.*.tmp")),
            )


if __name__ == "__main__":
    unittest.main()
