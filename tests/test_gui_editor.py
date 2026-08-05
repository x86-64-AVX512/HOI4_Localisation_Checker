from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from hoi4_l10n_checker.background_tasks import BackgroundTaskRunner, TaskNotice
from hoi4_l10n_checker.gui_editor import NotepadPlusPlusController
from hoi4_l10n_checker.localisation_compare import ComparisonIssue
from hoi4_l10n_checker.models import Diagnostic
from hoi4_l10n_checker.notepad_plus_plus import (
    NotepadPlusPlusError,
    OpenResult,
)


class FakeRoot:
    def __init__(self) -> None:
        self.bell_count = 0

    def bell(self) -> None:
        self.bell_count += 1


class FakeStatusVariable:
    def __init__(self) -> None:
        self.value = ""

    def set(self, value: str) -> None:
        self.value = value


class NotepadPlusPlusControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root_path = Path(self.temporary.name)
        self.executable = self.root_path / "notepad++.exe"
        self.executable.write_bytes(b"test")
        self.root = FakeRoot()
        self.tasks = BackgroundTaskRunner()
        self.remembered: list[Path] = []
        self.errors: list[tuple[str, str]] = []

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _controller(
        self,
        *,
        configured_path: str | None = None,
        executable_finder=None,
        location_opener=None,
        executable_selector=None,
        fullscreen: bool = True,
    ) -> NotepadPlusPlusController:
        finder = executable_finder or (
            lambda _configured: self.executable
        )
        opener = location_opener or (
            lambda **_kwargs: OpenResult(True, False)
        )
        return NotepadPlusPlusController(
            root=self.root,  # type: ignore[arg-type]
            tasks=self.tasks,
            configured_path=lambda: (
                str(self.executable)
                if configured_path is None
                else configured_path
            ),
            remember_executable=self.remembered.append,
            fullscreen=lambda: fullscreen,
            executable_finder=finder,
            location_opener=opener,
            worker_starter=lambda work: work(),
            executable_selector=executable_selector,
            show_error=lambda title, message: self.errors.append(
                (title, message)
            ),
        )

    def _handle_notices(
        self,
        controller: NotepadPlusPlusController,
    ) -> tuple[TaskNotice, ...]:
        notices = tuple(
            event
            for event in self.tasks.drain()
            if isinstance(event, TaskNotice)
        )
        for notice in notices:
            self.assertTrue(controller.handle_notice(notice))
        return notices

    def test_resolve_prompts_for_executable_and_remembers_selection(self) -> None:
        controller = self._controller(
            configured_path="",
            executable_finder=lambda _configured: None,
            executable_selector=lambda: str(self.executable),
        )

        resolved = controller.resolve_executable()

        self.assertEqual(self.executable.resolve(), resolved)
        self.assertEqual([self.executable.resolve()], self.remembered)

    def test_missing_diagnostic_file_is_reported_without_starting_worker(
        self,
    ) -> None:
        controller = self._controller()
        status = FakeStatusVariable()
        diagnostic = Diagnostic(
            severity="warning",
            code="UNSAFE_GLYPH",
            path=self.root_path / "missing.yml",
            line=2,
            column=3,
            message="test",
        )

        result = controller.open_diagnostic(
            diagnostic,
            status,  # type: ignore[arg-type]
        )

        self.assertEqual("break", result)
        self.assertEqual((), self.tasks.drain())
        self.assertEqual("Файл не найден", self.errors[0][0])

    def test_glyph_diagnostic_is_opened_and_selected(self) -> None:
        file_path = self.root_path / "sample.yml"
        file_path.write_text("l_russian:\n TEST:0 \"текст\"\n", encoding="utf-8")
        calls: list[dict[str, object]] = []

        def open_file(**kwargs):
            calls.append(kwargs)
            return OpenResult(True, True)

        controller = self._controller(location_opener=open_file)
        status = FakeStatusVariable()
        diagnostic = Diagnostic(
            severity="warning",
            code="UNSAFE_GLYPH",
            path=file_path,
            line=2,
            column=10,
            message="test",
            character="…",
        )

        result = controller.open_diagnostic(
            diagnostic,
            status,  # type: ignore[arg-type]
        )
        notices = self._handle_notices(controller)

        self.assertEqual("break", result)
        self.assertEqual(1, len(notices))
        self.assertEqual(1, calls[0]["selection_length"])
        self.assertTrue(calls[0]["fullscreen"])
        self.assertIn("фрагмент выделен", status.value)

    def test_comparison_opens_both_languages_in_requested_order(self) -> None:
        english = self.root_path / "sample_l_english.yml"
        russian = self.root_path / "sample_l_russian.yml"
        english.write_text("english", encoding="utf-8")
        russian.write_text("russian", encoding="utf-8")
        opened_paths: list[Path] = []

        def open_file(**kwargs):
            opened_paths.append(kwargs["file_path"])
            return OpenResult(True, False)

        controller = self._controller(location_opener=open_file)
        status = FakeStatusVariable()
        issue = self._comparison_issue(english, russian)

        controller.open_comparison(
            issue,
            ("english", "russian"),
            status,  # type: ignore[arg-type]
        )
        self._handle_notices(controller)

        self.assertEqual([english, russian], opened_paths)
        self.assertIn("Открыты английский и русский файлы", status.value)
        self.assertIn("активен русский", status.value)

    def test_comparison_reports_partial_failure(self) -> None:
        english = self.root_path / "sample_l_english.yml"
        russian = self.root_path / "sample_l_russian.yml"
        english.write_text("english", encoding="utf-8")
        russian.write_text("russian", encoding="utf-8")
        call_count = 0

        def open_file(**_kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise NotepadPlusPlusError("test failure")
            return OpenResult(True, False)

        controller = self._controller(location_opener=open_file)
        status = FakeStatusVariable()

        controller.open_comparison(
            self._comparison_issue(english, russian),
            ("english", "russian"),
            status,  # type: ignore[arg-type]
        )
        self._handle_notices(controller)

        self.assertIn("Открыто файлов: 1", status.value)
        self.assertEqual(
            "Не удалось открыть файл сравнения в Notepad++",
            self.errors[0][0],
        )

    @staticmethod
    def _comparison_issue(
        english: Path,
        russian: Path,
    ) -> ComparisonIssue:
        return ComparisonIssue(
            category="duplicate_english",
            code="DUPLICATE_ENGLISH_KEY",
            label="Повтор английского ключа",
            key="TEST_KEY",
            language="english",
            path=english,
            line=4,
            column=2,
            raw_value="test",
            message="test",
            english_path=english,
            english_line=4,
            english_column=2,
            russian_path=russian,
            russian_line=7,
            russian_column=3,
        )


if __name__ == "__main__":
    unittest.main()
