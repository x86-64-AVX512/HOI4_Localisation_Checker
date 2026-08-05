from __future__ import annotations

import threading
import unittest
from pathlib import Path

from hoi4_l10n_checker.background_tasks import (
    BackgroundTaskRunner,
    TaskFailed,
    TaskNotice,
    TaskProgress,
    TaskReporter,
    TaskSucceeded,
)


class BackgroundTaskRunnerTests(unittest.TestCase):
    def test_reports_progress_notice_and_success_in_order(self) -> None:
        runner = BackgroundTaskRunner()
        started = threading.Event()
        release = threading.Event()
        current_path = Path("current.yml")

        def work(reporter: TaskReporter) -> int:
            reporter.progress(2, 5, current_path)
            reporter.notify("preview_started", 12)
            started.set()
            self.assertTrue(release.wait(2))
            return 42

        self.assertTrue(runner.start("layout", work))
        self.assertTrue(started.wait(2))
        self.assertTrue(runner.is_running)
        self.assertFalse(runner.start("comparison", work))
        release.set()
        runner.join(2)

        events = runner.drain()
        self.assertFalse(runner.is_running)
        self.assertEqual(3, len(events))
        self.assertEqual(
            TaskProgress("layout", 2, 5, current_path),
            events[0],
        )
        self.assertEqual(
            TaskNotice("layout", "preview_started", 12),
            events[1],
        )
        self.assertEqual(TaskSucceeded("layout", 42), events[2])

    def test_converts_worker_exception_to_failure_event(self) -> None:
        runner = BackgroundTaskRunner()

        def work(_reporter: TaskReporter) -> None:
            raise ValueError("simulated failure")

        self.assertTrue(runner.start("localisation", work))
        runner.join(2)

        events = runner.drain()
        self.assertEqual(1, len(events))
        failure = events[0]
        self.assertIsInstance(failure, TaskFailed)
        if isinstance(failure, TaskFailed):
            self.assertEqual("localisation", failure.task)
            self.assertEqual("simulated failure", str(failure.error))


if __name__ == "__main__":
    unittest.main()
