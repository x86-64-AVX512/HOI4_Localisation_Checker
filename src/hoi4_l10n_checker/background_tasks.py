from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypeAlias

TaskName = Literal["localisation", "layout", "comparison"]


@dataclass(frozen=True, slots=True)
class TaskProgress:
    task: TaskName
    current: int
    total: int
    path: Path


@dataclass(frozen=True, slots=True)
class TaskNotice:
    source: str
    kind: str
    payload: object


@dataclass(frozen=True, slots=True)
class TaskSucceeded:
    task: TaskName
    result: object


@dataclass(frozen=True, slots=True)
class TaskFailed:
    task: TaskName
    error: Exception


BackgroundEvent: TypeAlias = (
    TaskProgress | TaskNotice | TaskSucceeded | TaskFailed
)
TaskWork: TypeAlias = Callable[["TaskReporter"], object]


class TaskReporter:
    """Thread-safe event publisher bound to one named background task."""

    def __init__(
        self,
        task: TaskName,
        publish: Callable[[BackgroundEvent], None],
    ) -> None:
        self.task = task
        self._publish = publish

    def progress(self, current: int, total: int, path: Path) -> None:
        self._publish(
            TaskProgress(
                task=self.task,
                current=current,
                total=total,
                path=path,
            )
        )

    def notify(self, kind: str, payload: object) -> None:
        self._publish(
            TaskNotice(
                source=self.task,
                kind=kind,
                payload=payload,
            )
        )


class BackgroundTaskRunner:
    """Serialises long-running checks and returns typed events to Tkinter."""

    def __init__(self) -> None:
        self._events: queue.Queue[BackgroundEvent] = queue.Queue()
        self._worker: threading.Thread | None = None
        self._lock = threading.Lock()

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._worker is not None and self._worker.is_alive()

    def start(self, task: TaskName, work: TaskWork) -> bool:
        with self._lock:
            if self._worker is not None and self._worker.is_alive():
                return False
            worker = threading.Thread(
                target=self._run,
                args=(task, work),
                daemon=True,
                name=f"hoi4-l10n-{task}",
            )
            self._worker = worker
            worker.start()
        return True

    def post_notice(self, source: str, kind: str, payload: object) -> None:
        self.post(
            TaskNotice(source=source, kind=kind, payload=payload)
        )

    def post(self, event: BackgroundEvent) -> None:
        self._events.put(event)

    def drain(self) -> tuple[BackgroundEvent, ...]:
        events: list[BackgroundEvent] = []
        while True:
            try:
                events.append(self._events.get_nowait())
            except queue.Empty:
                return tuple(events)

    def join(self, timeout: float | None = None) -> None:
        with self._lock:
            worker = self._worker
        if worker is not None:
            worker.join(timeout)

    def _publish(self, event: BackgroundEvent) -> None:
        self._events.put(event)

    def _run(self, task: TaskName, work: TaskWork) -> None:
        reporter = TaskReporter(task, self._publish)
        try:
            result = work(reporter)
        except Exception as error:
            self._publish(TaskFailed(task=task, error=error))
            return
        self._publish(TaskSucceeded(task=task, result=result))
