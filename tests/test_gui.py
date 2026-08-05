from __future__ import annotations

import csv
import json
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

from hoi4_l10n_checker import gui as gui_module
from hoi4_l10n_checker.background_tasks import TaskFailed, TaskProgress
from hoi4_l10n_checker.gui import CheckerApplication
from hoi4_l10n_checker.gui_compare_tab import FILTER_LABELS
from hoi4_l10n_checker.localisation_compare import (
    ComparisonIssue,
    LocalisationComparisonResult,
)
from hoi4_l10n_checker.settings import SettingsError, load_settings


class GuiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.app_root = Path(self.temporary.name)
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = CheckerApplication(self.root, self.app_root)
        self.root.update_idletasks()

    def tearDown(self) -> None:
        self.root.destroy()
        self.temporary.cleanup()

    def test_builds_all_tabs_with_safe_default_states(self) -> None:
        labels = [
            self.app.notebook.tab(tab, "text") for tab in self.app.notebook.tabs()
        ]

        self.assertEqual(
            [
                "Проверка локализации",
                "Длина текстов",
                "Сравнение ключей",
            ],
            labels,
        )
        self.assertTrue(self.app.check_tab.russian_straight_quotes_var.get())
        self.assertEqual(
            "disabled",
            str(self.app.check_tab.export_button.cget("state")),
        )
        self.assertEqual(
            "disabled",
            str(self.app.layout_tab.export_button.cget("state")),
        )
        self.assertEqual(
            "disabled",
            str(self.app.compare_tab.export_button.cget("state")),
        )

    def test_export_buttons_follow_rows_and_busy_state(self) -> None:
        tables_and_buttons = (
            (self.app.check_tab.table, self.app.check_tab.export_button),
            (self.app.layout_tab.table, self.app.layout_tab.export_button),
            (self.app.compare_tab.table, self.app.compare_tab.export_button),
        )
        for table, _ in tables_and_buttons:
            table.insert("", tk.END, values=("test",))

        self.app._refresh_export_controls()
        self.assertTrue(
            all(
                str(button.cget("state")) == "normal"
                for _, button in tables_and_buttons
            )
        )

        self.app._set_busy(True)
        self.assertTrue(
            all(
                str(button.cget("state")) == "disabled"
                for _, button in tables_and_buttons
            )
        )

        self.app._set_busy(False)
        self.assertTrue(
            all(
                str(button.cget("state")) == "normal"
                for _, button in tables_and_buttons
            )
        )

    def test_quote_option_is_saved_through_gui(self) -> None:
        self.app.check_tab.russian_straight_quotes_var.set(False)
        self.app._russian_straight_quotes_changed()

        settings = load_settings(self.app_root / "settings.json")
        saved = json.loads(
            (self.app_root / "settings.json").read_text(encoding="utf-8")
        )
        self.assertFalse(settings.check_russian_straight_quotes)
        self.assertEqual(2, saved["format_version"])

    def test_failed_setting_update_restores_gui_variable(self) -> None:
        self.app.check_tab.russian_straight_quotes_var.set(False)

        with (
            patch.object(
                self.app.settings,
                "update",
                side_effect=SettingsError("simulated failure"),
            ),
            patch.object(gui_module.messagebox, "showerror") as showerror,
        ):
            self.app._russian_straight_quotes_changed()

        self.assertTrue(
            self.app.check_tab.russian_straight_quotes_var.get()
        )
        self.assertTrue(
            self.app.settings.current.check_russian_straight_quotes
        )
        showerror.assert_called_once()

    def test_exception_controller_saves_with_application_settings(self) -> None:
        self.assertTrue(self.app.exceptions.add_text("…«"))

        settings = load_settings(self.app_root / "settings.json")
        self.assertEqual(
            frozenset({"…", "«"}),
            settings.excluded_characters,
        )
        self.assertEqual(
            "Исключения… (2)",
            self.app.check_tab.exceptions_button["text"],
        )

    def test_layout_options_are_saved_through_extracted_tab(self) -> None:
        self.app.layout_tab.focus_limit_var.set("365")
        self.app.layout_tab.event_limit_var.set("3500")

        result = self.app._layout_controls_changed()

        settings = load_settings(self.app_root / "settings.json")
        self.assertEqual("break", result)
        self.assertEqual(365, settings.layout_focus_limit)
        self.assertEqual(3500, settings.layout_event_limit)
        self.assertEqual(
            "Настройки проверки текстов сохранены.",
            self.app.layout_tab.current_file_var.get(),
        )

    def test_main_table_export_preserves_visible_values(self) -> None:
        destination = self.app_root / "exports" / "results.csv"
        destination.parent.mkdir()
        values = (
            "Предупреждение",
            "TEST_CODE",
            r"C:\mod\localisation\sample.yml",
            12,
            34,
            "TEST_KEY",
            'Описание; с "кавычками"',
        )
        self.app.check_tab.table.insert("", tk.END, values=values)

        with patch.object(
            gui_module.filedialog,
            "asksaveasfilename",
            return_value=str(destination),
        ):
            self.app._export_table_results(
                self.app.check_tab.table,
                "test",
                self.app.check_tab.current_file_var,
            )

        with destination.open(
            "r",
            encoding="utf-8-sig",
            newline="",
        ) as exported:
            rows = list(csv.reader(exported, delimiter=";"))
        self.assertEqual(2, len(rows))
        self.assertEqual(list(map(str, values)), rows[1])
        self.assertEqual(
            str(destination.parent),
            load_settings(self.app_root / "settings.json").export_directory,
        )

    def test_compare_filter_and_key_sort_change_visible_rows(self) -> None:
        issues = [
            self._comparison_issue("missing_english", "Z_KEY", 20),
            self._comparison_issue("missing_russian", "B_KEY", 10),
            self._comparison_issue("missing_russian", "A_KEY", 30),
        ]
        self.app.compare_tab.all_issues = issues
        missing_russian_label = next(
            label
            for label, value in FILTER_LABELS.items()
            if value == "missing_russian"
        )
        self.app.compare_tab.filter_var.set(missing_russian_label)

        self.app.compare_tab.apply_filter()
        self.assertEqual(
            2,
            len(self.app.compare_tab.table.get_children("")),
        )

        self.app.compare_tab.sort_by_key()
        visible_keys = [
            self.app.compare_tab.table.set(item, "key")
            for item in self.app.compare_tab.table.get_children("")
        ]
        self.assertEqual(["A_KEY", "B_KEY"], visible_keys)

    def test_compare_tab_presents_completed_result(self) -> None:
        issue = self._comparison_issue("missing_russian", "TEST_KEY", 10)
        result = LocalisationComparisonResult(
            english_root=self.app_root / "english",
            russian_root=self.app_root / "russian",
            files_checked=4,
            english_files=2,
            russian_files=2,
            english_keys=20,
            russian_keys=19,
            common_keys=19,
            missing_russian=1,
            missing_english=0,
            duplicate_english=0,
            duplicate_russian=0,
            parse_errors=0,
            issues=[issue],
        )

        self.app.compare_tab.show_result(result)

        self.assertIn("Файлов: 4", self.app.compare_tab.summary_var.get())
        self.assertIn(
            "нет в русской — 1",
            self.app.compare_tab.status_var.get(),
        )
        self.assertEqual(
            1,
            len(self.app.compare_tab.table.get_children("")),
        )
        self.assertEqual(
            "normal",
            str(self.app.compare_tab.export_button.cget("state")),
        )

    def test_progress_and_failure_events_restore_ui_state(self) -> None:
        current_path = self.app_root / "current.yml"
        self.app._set_busy(True)
        self.app.tasks.post(TaskProgress("localisation", 2, 5, current_path))
        self.app.tasks.post(
            TaskFailed("localisation", RuntimeError("simulated failure"))
        )

        with patch.object(gui_module.messagebox, "showerror") as showerror:
            self.app._poll_events()

        self.assertEqual(
            5,
            int(float(self.app.check_tab.progress.cget("maximum"))),
        )
        self.assertEqual(
            2,
            int(float(self.app.check_tab.progress.cget("value"))),
        )
        self.assertFalse(self.app.busy)
        self.assertEqual(
            "Проверка завершилась внутренней ошибкой.",
            self.app.check_tab.summary_var.get(),
        )
        showerror.assert_called_once_with("Ошибка", "simulated failure")

    def _comparison_issue(
        self,
        category: str,
        key: str,
        line: int,
    ) -> ComparisonIssue:
        language = "russian" if category == "missing_english" else "english"
        return ComparisonIssue(
            category=category,
            code=category.upper(),
            label=category,
            key=key,
            language=language,
            path=self.app_root / f"{language}.yml",
            line=line,
            column=2,
            raw_value=f"Value for {key}",
            message=f"Problem with {key}",
        )


if __name__ == "__main__":
    unittest.main()
