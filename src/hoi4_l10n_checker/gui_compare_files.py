from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import ttk

from .localisation_compare import ComparisonLanguage

ComparisonFileExclusions = dict[ComparisonLanguage, set[Path]]


def collect_source_files(root: Path) -> tuple[Path, ...]:
    """Return localisation files shown by the comparison file dialog."""
    if not root.is_dir():
        return ()
    return tuple(
        sorted(
            (
                path.resolve()
                for path in root.rglob("*")
                if path.is_file() and path.suffix.casefold() == ".yml"
            ),
            key=lambda path: str(path).casefold(),
        )
    )


class ComparisonFilesDialog:
    """Modal editor for comparison-file exclusions kept by the current GUI."""

    def __init__(
        self,
        parent: tk.Misc,
        roots: dict[ComparisonLanguage, Path],
        exclusions: ComparisonFileExclusions,
    ) -> None:
        self.parent = parent
        self.roots = roots
        self.exclusions: ComparisonFileExclusions = {
            language: {path.resolve() for path in exclusions[language]}
            for language in ("english", "russian")
        }
        self.result: ComparisonFileExclusions | None = None
        self.rows: dict[str, tuple[ComparisonLanguage, Path]] = {}
        self.files: tuple[tuple[ComparisonLanguage, Path], ...] = ()

        self.window = tk.Toplevel(parent)
        self.window.title("Файлы сравнения")
        self.window.geometry("980x620")
        self.window.minsize(720, 420)
        self.window.transient(parent.winfo_toplevel())
        self.window.protocol("WM_DELETE_WINDOW", self._cancel)

        ttk.Label(
            self.window,
            text=(
                "Исключённые файлы не участвуют только в текущей сессии. "
                "Настройка не записывается в settings.json."
            ),
            justify=tk.LEFT,
        ).pack(fill=tk.X, padx=12, pady=(12, 8))

        filter_frame = ttk.Frame(self.window)
        filter_frame.pack(fill=tk.X, padx=12, pady=(0, 8))
        ttk.Label(filter_frame, text="Поиск по имени или пути:").pack(
            side=tk.LEFT
        )
        self.filter_var = tk.StringVar()
        self.filter_entry = ttk.Entry(
            filter_frame,
            textvariable=self.filter_var,
        )
        self.filter_entry.pack(
            side=tk.LEFT,
            fill=tk.X,
            expand=True,
            padx=(8, 0),
        )
        self.filter_var.trace_add("write", self._apply_filter)

        table_frame = ttk.Frame(self.window)
        table_frame.pack(fill=tk.BOTH, expand=True, padx=12)
        self.table = ttk.Treeview(
            table_frame,
            columns=("state", "language", "file"),
            show="headings",
            selectmode="extended",
        )
        self.table.heading("state", text="Состояние")
        self.table.heading("language", text="Источник")
        self.table.heading("file", text="Файл")
        self.table.column("state", width=125, minwidth=110, stretch=False)
        self.table.column("language", width=105, minwidth=90, stretch=False)
        self.table.column("file", width=650, minwidth=280, stretch=True)
        self.table.tag_configure("excluded", foreground="#B00020")
        self.table.tag_configure("included", foreground="#1B5E20")

        vertical = ttk.Scrollbar(
            table_frame,
            orient=tk.VERTICAL,
            command=self.table.yview,
        )
        horizontal = ttk.Scrollbar(
            table_frame,
            orient=tk.HORIZONTAL,
            command=self.table.xview,
        )
        self.table.configure(
            yscrollcommand=vertical.set,
            xscrollcommand=horizontal.set,
        )
        self.table.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)
        self.table.bind("<Double-1>", self._toggle_selected)

        self.summary_var = tk.StringVar()
        ttk.Label(self.window, textvariable=self.summary_var).pack(
            fill=tk.X,
            padx=12,
            pady=(8, 0),
        )

        buttons = ttk.Frame(self.window)
        buttons.pack(fill=tk.X, padx=12, pady=12)
        ttk.Button(
            buttons,
            text="Исключить выбранные",
            command=lambda: self._set_selected(True),
        ).pack(side=tk.LEFT)
        ttk.Button(
            buttons,
            text="Вернуть выбранные",
            command=lambda: self._set_selected(False),
        ).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(
            buttons,
            text="Учитывать все",
            command=self._include_all,
        ).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(
            buttons,
            text="Отмена",
            command=self._cancel,
        ).pack(side=tk.RIGHT)
        ttk.Button(
            buttons,
            text="Готово",
            command=self._accept,
        ).pack(side=tk.RIGHT, padx=(0, 8))

        self._load_files()

    def _load_files(self) -> None:
        files: list[tuple[ComparisonLanguage, Path]] = []
        available: dict[ComparisonLanguage, set[Path]] = {
            "english": set(),
            "russian": set(),
        }
        for language in ("english", "russian"):
            for path in collect_source_files(self.roots[language]):
                files.append((language, path))
                available[language].add(path)
            self.exclusions[language].intersection_update(available[language])
        self.files = tuple(files)
        self._render_rows()

    def _apply_filter(self, *_args: object) -> None:
        self._render_rows()

    def _render_rows(self) -> None:
        for item in self.table.get_children(""):
            self.table.delete(item)
        self.rows.clear()
        labels = {"english": "Английский", "russian": "Русский"}
        needle = self.filter_var.get().strip().casefold()
        for language, path in self.files:
            root = self.roots[language]
            relative = path.relative_to(root).as_posix()
            searchable = f"{labels[language]} {relative}".casefold()
            if needle and needle not in searchable:
                continue
            item = self.table.insert("", tk.END)
            self.rows[item] = (language, path)
            self.table.set(item, "language", labels[language])
            self.table.set(item, "file", relative)
            self._refresh_row(item)
        self._refresh_summary()

    def _refresh_row(self, item: str) -> None:
        language, path = self.rows[item]
        excluded = path in self.exclusions[language]
        self.table.set(item, "state", "Исключён" if excluded else "Учитывается")
        self.table.item(item, tags=("excluded" if excluded else "included",))

    def _refresh_summary(self) -> None:
        english = len(self.exclusions["english"])
        russian = len(self.exclusions["russian"])
        self.summary_var.set(
            f"Временно исключено: EN — {english}, RU — {russian}."
        )

    def _set_selected(self, excluded: bool) -> None:
        for item in self.table.selection():
            language, path = self.rows[item]
            if excluded:
                self.exclusions[language].add(path)
            else:
                self.exclusions[language].discard(path)
            self._refresh_row(item)
        self._refresh_summary()

    def _toggle_selected(self, event: tk.Event) -> str:
        item = self.table.identify_row(event.y)
        if not item:
            return "break"
        self.table.selection_set(item)
        language, path = self.rows[item]
        self._set_selected(path not in self.exclusions[language])
        return "break"

    def _include_all(self) -> None:
        for excluded in self.exclusions.values():
            excluded.clear()
        for item in self.rows:
            self._refresh_row(item)
        self._refresh_summary()

    def _accept(self) -> None:
        self.result = {
            language: set(self.exclusions[language])
            for language in ("english", "russian")
        }
        self.window.destroy()

    def _cancel(self) -> None:
        self.result = None
        self.window.destroy()

    def show(self) -> ComparisonFileExclusions | None:
        self.window.grab_set()
        self.window.wait_window()
        return self.result
