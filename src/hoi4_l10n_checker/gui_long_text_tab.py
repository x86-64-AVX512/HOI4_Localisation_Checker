from __future__ import annotations

import difflib
import re
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from .long_text import (
    _TOKEN,
    AssemblySpec,
    TextBranch,
    apply_plan,
    byte_size,
    decode_value,
    generated_values,
    load_specs,
    prepare_plan,
    split_text,
)
from .parser import parse_localisation_file


class LongTextTab:
    """Card/list editor for country-event and EaW welcome-screen assemblies."""

    def __init__(self, root: tk.Tk, notebook: ttk.Notebook) -> None:
        self.root = root
        self.frame = ttk.Frame(notebook, padding=12)
        notebook.add(self.frame, text="Конструктор длинных текстов")
        self.mod_root: Path | None = None
        self.branches: dict[str, list[str]] = {"": [""]}
        self.current_tag = ""
        self.selected_part: int | None = None
        self.busy = False
        self.updating = False
        self.mod_var = tk.StringVar(value="Папка мода не выбрана")
        self.source_var = tk.StringVar()
        self.key_var = tk.StringVar()
        self.prefix_var = tk.StringVar(value="EawLong")
        self.suggested_prefix = "EawLong"
        self.kind_var = tk.StringVar(value="Ивент страны")
        self.tag_var = tk.StringVar()
        self.target_var = tk.StringVar(value="4000")
        self.status_var = tk.StringVar(value="Выберите мод, исходный файл и ключ.")

        row = ttk.Frame(self.frame)
        row.pack(fill=tk.X)
        ttk.Label(row, textvariable=self.mod_var).pack(
            side=tk.LEFT, fill=tk.X, expand=True
        )
        self.buttons: list[ttk.Button] = []
        self._button(row, "Папка мода…", self.choose_mod).pack(side=tk.RIGHT)
        fields = ttk.Frame(self.frame)
        fields.pack(fill=tk.X, pady=8)
        fields.columnconfigure(1, weight=1)
        ttk.Label(fields, text="Исходный русский .yml:").grid(
            row=0, column=0, sticky=tk.W
        )
        self.source_entry = ttk.Entry(fields, textvariable=self.source_var)
        self.source_entry.grid(row=0, column=1, sticky="ew", padx=8)
        self._button(fields, "Файл…", self.choose_source).grid(row=0, column=2)
        ttk.Label(fields, text="Основной ключ:").grid(row=1, column=0, sticky=tk.W)
        self.key_entry = ttk.Combobox(fields, textvariable=self.key_var)
        self.key_entry.grid(row=1, column=1, sticky="ew", padx=8, pady=6)
        self._button(fields, "Загрузить текст", self.load_source).grid(
            row=1, column=2
        )
        options = ttk.Frame(self.frame)
        options.pack(fill=tk.X)
        self.kind_combo = ttk.Combobox(
            options, textvariable=self.kind_var,
            values=("Ивент страны", "Вступительный экран EaW"),
            state="readonly", width=28,
        )
        self.kind_combo.pack(side=tk.LEFT)
        self.kind_combo.bind("<<ComboboxSelected>>", self.change_kind)
        ttk.Label(options, text="Префикс getters:").pack(
            side=tk.LEFT, padx=(12, 6)
        )
        self.prefix_entry = ttk.Entry(
            options, textvariable=self.prefix_var, width=24
        )
        self.prefix_entry.pack(side=tk.LEFT)
        ttk.Label(options, text="Размер части, байт:").pack(
            side=tk.LEFT, padx=(12, 6)
        )
        self.target_entry = ttk.Entry(options, textvariable=self.target_var, width=7)
        self.target_entry.pack(side=tk.LEFT)

        branch_row = ttk.Frame(self.frame)
        branch_row.pack(fill=tk.X, pady=8)
        ttk.Label(branch_row, text="Ветка:").pack(side=tk.LEFT)
        self.branch_combo = ttk.Combobox(
            branch_row, textvariable=self.tag_var, state="readonly", width=12
        )
        self.branch_combo.pack(side=tk.LEFT, padx=8)
        self.branch_combo.bind("<<ComboboxSelected>>", self.select_branch)
        self.add_branch_button = self._button(
            branch_row, "Добавить страну…", self.add_branch
        )
        self.add_branch_button.pack(side=tk.LEFT)
        self.remove_branch_button = self._button(
            branch_row, "Удалить страну", self.remove_branch
        )
        self.remove_branch_button.pack(side=tk.LEFT, padx=8)
        self.load_country_button = self._button(
            branch_row, "Загрузить текст страны…", self.load_country_text
        )
        self.load_country_button.pack(side=tk.LEFT)
        self._button(branch_row, "Открыть сохранённую сборку…", self.open_saved).pack(
            side=tk.RIGHT
        )

        content = ttk.Panedwindow(self.frame, orient=tk.HORIZONTAL)
        content.pack(fill=tk.BOTH, expand=True)
        cards = ttk.Frame(content)
        content.add(cards, weight=1)
        self.parts_table = ttk.Treeview(
            cards, columns=("part", "bytes", "preview"),
            show="headings", selectmode="browse",
            height=10,
        )
        self.parts_table.heading("part", text="Часть")
        self.parts_table.heading("bytes", text="UTF-8 байт")
        self.parts_table.heading("preview", text="Начало текста")
        self.parts_table.column("part", width=60, stretch=False)
        self.parts_table.column("bytes", width=85, stretch=False)
        self.parts_table.column("preview", width=170, stretch=True)
        self.parts_table.tag_configure("large", foreground="#B00020")
        scrollbar = ttk.Scrollbar(
            cards, command=self.parts_table.yview, orient=tk.VERTICAL
        )
        self.parts_table.configure(yscrollcommand=scrollbar.set)
        self.parts_table.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.parts_table.bind("<<TreeviewSelect>>", self.select_part)
        editors = ttk.Notebook(content)
        content.add(editors, weight=4)
        full_frame = ttk.Frame(editors)
        part_frame = ttk.Frame(editors)
        editors.add(full_frame, text="Полный текст ветки")
        editors.add(part_frame, text="Редактор выбранной части")
        self.full_text = self._text_editor(full_frame)
        self.part_text = self._text_editor(part_frame)

        actions = ttk.Frame(self.frame)
        actions.pack(fill=tk.X, pady=8)
        for label, command in (
            ("Разбить автоматически", self.auto_split),
            ("Применить правку части", self.commit_part),
            ("Разделить у курсора", self.split_at_cursor),
            ("Объединить со следующей", self.merge_next),
            ("↑", lambda: self.move_part(-1)),
            ("↓", lambda: self.move_part(1)),
        ):
            self._button(actions, label, command).pack(side=tk.LEFT, padx=(0, 6))
        self._button(
            self.frame, "Проверить и просмотреть правки…", self.preview
        ).pack(anchor=tk.E, pady=(0, 8))
        ttk.Label(
            self.frame,
            text=(
                "Части и строка вызовов: меньше 6144 байт. Ивенты могут упираться "
                "в высоту окна; welcome требует проверки прокрутки и других стран. "
                "Фокусы не входят в конструктор."
            ),
            wraplength=1100,
        ).pack(fill=tk.X)
        ttk.Label(
            self.frame, textvariable=self.status_var, wraplength=1100
        ).pack(fill=tk.X, pady=(6, 0))
        self.refresh_parts()

    def _button(self, parent: tk.Misc, label: str, command) -> ttk.Button:
        button = ttk.Button(parent, text=label, command=command)
        self.buttons.append(button)
        return button

    @staticmethod
    def _text_editor(frame: ttk.Frame) -> tk.Text:
        text = tk.Text(frame, wrap="word", undo=True, height=12)
        scrollbar = ttk.Scrollbar(frame, command=text.yview)
        text.configure(yscrollcommand=scrollbar.set)
        text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        return text

    @staticmethod
    def _replace_text(widget: tk.Text, text: str) -> None:
        widget.delete("1.0", tk.END)
        widget.insert("1.0", text)

    def set_busy(self, busy: bool) -> None:
        self.busy = busy
        for button in self.buttons:
            button.configure(state=tk.DISABLED if busy else tk.NORMAL)
        for widget in (
            self.source_entry, self.key_entry, self.prefix_entry, self.target_entry,
            self.full_text, self.part_text,
        ):
            widget.configure(state=tk.DISABLED if busy else tk.NORMAL)
        self.kind_combo.configure(state=tk.DISABLED if busy else "readonly")
        self.branch_combo.configure(state=tk.DISABLED if busy else "readonly")
        if not busy:
            enabled = self.kind_var.get() == "Вступительный экран EaW"
            for button in (
                self.add_branch_button, self.remove_branch_button,
                self.load_country_button,
            ):
                button.configure(state=tk.NORMAL if enabled else tk.DISABLED)

    def choose_mod(self) -> None:
        selected = filedialog.askdirectory(parent=self.root, title="Папка мода")
        if selected:
            root = Path(selected).resolve()
            if not (root / "common").is_dir() or not (root / "localisation").is_dir():
                messagebox.showerror("Папка мода", "Нужны common и localisation.")
                return
            self.mod_root = root
            self.mod_var.set(str(root))
            self.source_var.set("")

    def choose_source(self) -> None:
        if self.mod_root is None:
            self.choose_mod()
        if self.mod_root is None:
            return
        selected = filedialog.askopenfilename(
            parent=self.root, title="Исходный файл локализации",
            initialdir=str(self.mod_root / "localisation/russian"),
            filetypes=[("Локализация", "*.yml")],
        )
        if selected:
            try:
                relative = Path(selected).resolve().relative_to(self.mod_root)
            except ValueError:
                messagebox.showerror("Источник", "Файл должен быть внутри мода.")
                return
            self.source_var.set(relative.as_posix())
            from .long_text import _event_description_keys
            event_keys = _event_description_keys(self.mod_root)
            candidates = [
                entry.key for entry in parse_localisation_file(Path(selected)).entries
                if entry.language == "l_russian"
                and (entry.key in event_keys or entry.key == "EAW_WS_TAB_1_TXT")
            ]
            self.key_entry.configure(values=tuple(sorted(set(candidates))))

    def load_source(self) -> None:
        try:
            if self.mod_root is None:
                raise ValueError("Сначала выберите папку мода.")
            key = self.key_var.get().strip()
            from .long_text import resolve_inside
            path = resolve_inside(self.mod_root, self.source_var.get())
            parsed = parse_localisation_file(path)
            matches = [
                entry for entry in parsed.entries
                if entry.key == key and entry.language == "l_russian"
            ]
            if len(matches) != 1:
                raise ValueError("Нужно одно определение русского ключа в файле.")
            existing = next(
                (spec for spec in load_specs(self.mod_root)
                 if spec.key == key and spec.language == "l_russian"),
                None,
            )
            if existing is not None:
                self.load_spec(existing)
                return
            if self.prefix_var.get() == self.suggested_prefix:
                self.suggested_prefix = "EawLong_" + re.sub(
                    r"[^A-Za-z0-9_]", "_", key
                )
                self.prefix_var.set(self.suggested_prefix)
            tag = "EQS" if self.kind_var.get() == "Вступительный экран EaW" else ""
            value = matches[0].raw_value
            if tag:
                country_entry = next(
                    (entry for entry in parsed.entries
                     if entry.key == f"EAW_WS_{tag}_desc"
                     and entry.language == "l_russian"),
                    None,
                )
                if country_entry is None:
                    raise ValueError(
                        f"Не найден EAW_WS_{tag}_desc. Вставьте текст страны "
                        "в полный редактор вручную."
                    )
                value = country_entry.raw_value
            self.branches = {tag: [decode_value(value)]}
            self.current_tag = tag
            self.selected_part = None
            self._replace_text(self.full_text, "".join(self.branches[tag]))
            self._replace_text(self.part_text, "")
            self.refresh_parts()
            self.status_var.set("Исходный текст загружен; выберите разбиение.")
        except (OSError, ValueError, KeyError) as error:
            messagebox.showerror("Текст не загружен", str(error))

    def change_kind(self, _event=None) -> None:
        self._save_part()
        text = self.full_text.get("1.0", "end-1c")
        welcome = self.kind_var.get() == "Вступительный экран EaW"
        tag = "EQS" if welcome else ""
        self.branches = {tag: [text]}
        self.current_tag = tag
        self.selected_part = None
        if welcome:
            self.key_var.set("EAW_WS_TAB_1_TXT")
        self.refresh_parts()

    def add_branch(self) -> None:
        tag = simpledialog.askstring(
            "Страна", "original_tag (например EQS, CHN, CRY):", parent=self.root
        )
        if tag is None:
            return
        tag = tag.strip().upper()
        if not re.fullmatch(r"[A-Z0-9]{3}", tag) or tag in self.branches:
            messagebox.showerror("Страна", "Нужен новый трёхсимвольный тег.")
            return
        self._store_full_text()
        self.branches[tag] = [""]
        self.tag_var.set(tag)
        self.select_branch()

    def load_country_text(self) -> None:
        if self.mod_root is None:
            return
        key = simpledialog.askstring(
            "Описание страны", "Ключ исходного описания:",
            initialvalue=f"EAW_WS_{self.current_tag}_desc", parent=self.root,
        )
        if not key:
            return
        from .long_text import collect_entries
        entries = [
            entry for entry in collect_entries(self.mod_root)
            if entry.language == "l_russian" and entry.key == key.strip()
        ]
        if len(entries) != 1:
            messagebox.showerror(
                "Описание", "Нужно одно определение русского ключа в моде."
            )
            return
        text = decode_value(entries[0].raw_value)
        self.branches[self.current_tag] = [text]
        self.selected_part = None
        self._replace_text(self.full_text, text)
        self._replace_text(self.part_text, "")
        self.refresh_parts()

    def remove_branch(self) -> None:
        if len(self.branches) <= 1:
            return
        self.branches.pop(self.current_tag)
        self.current_tag = next(iter(self.branches))
        self.selected_part = None
        self._replace_text(self.full_text, "".join(self.branches[self.current_tag]))
        self.refresh_parts()

    def select_branch(self, _event=None) -> None:
        self._store_full_text()
        tag = self.tag_var.get()
        if tag not in self.branches:
            return
        self.current_tag = tag
        self.selected_part = None
        self._replace_text(self.full_text, "".join(self.branches[tag]))
        self._replace_text(self.part_text, "")
        self.refresh_parts()

    def refresh_parts(self) -> None:
        self.updating = True
        for item in self.parts_table.get_children():
            self.parts_table.delete(item)
        parts = self.branches[self.current_tag]
        for index, part in enumerate(parts):
            size = byte_size(part)
            self.parts_table.insert(
                "", tk.END, iid=str(index),
                values=(index + 1, size, part.replace("\n", " ")[:80]),
                tags=("large",) if size >= 6144 else (),
            )
        self.branch_combo.configure(values=tuple(self.branches))
        self.tag_var.set(self.current_tag)
        if self.selected_part is not None and self.selected_part < len(parts):
            self.parts_table.selection_set(str(self.selected_part))
        self.set_busy(self.busy)
        self.updating = False

    def select_part(self, _event=None) -> None:
        if self.updating:
            return
        selection = self.parts_table.selection()
        if not selection:
            return
        index = int(selection[0])
        if self.selected_part == index:
            return
        self._save_part()
        self.selected_part = index
        self._replace_text(
            self.part_text, self.branches[self.current_tag][index]
        )

    def _save_part(self) -> None:
        if self.selected_part is not None:
            text = self.part_text.get("1.0", "end-1c")
            if text != self.branches[self.current_tag][self.selected_part]:
                self.branches[self.current_tag][self.selected_part] = text
                self._replace_text(
                    self.full_text, "".join(self.branches[self.current_tag])
                )
                item = str(self.selected_part)
                if self.parts_table.exists(item):
                    size = byte_size(text)
                    self.parts_table.set(item, "bytes", size)
                    self.parts_table.set(item, "preview", text.replace("\n", " ")[:80])
                    self.parts_table.item(
                        item, tags=("large",) if size >= 6144 else ()
                    )

    def _store_full_text(self) -> None:
        self._save_part()
        text = self.full_text.get("1.0", "end-1c")
        if text != "".join(self.branches[self.current_tag]):
            self.branches[self.current_tag] = [text]
            self.selected_part = None

    def commit_part(self) -> None:
        self._save_part()
        self.refresh_parts()

    def auto_split(self) -> None:
        try:
            text = self.full_text.get("1.0", "end-1c")
            parts = split_text(text, int(self.target_var.get()))
            if "".join(parts) != text:
                raise ValueError("Не удалось точно восстановить исходный текст.")
            self.branches[self.current_tag] = parts
            self.selected_part = None
            self._replace_text(self.part_text, "")
            self.refresh_parts()
            self.status_var.set(
                f"Частей: {len(parts)}; байт: {byte_size(text)}. "
                "Соединение точно совпадает с исходным текстом."
            )
        except ValueError as error:
            messagebox.showerror("Разбиение", str(error))

    def split_at_cursor(self) -> None:
        if self.selected_part is None:
            return
        self._save_part()
        part = self.branches[self.current_tag][self.selected_part]
        offset = len(self.part_text.get("1.0", "insert"))
        boundaries = {match.end() for match in _TOKEN.finditer(part)}
        if not 0 < offset < len(part) or offset not in boundaries:
            messagebox.showerror(
                "Разделение", "Поставьте курсор между словами/вставками."
            )
            return
        index = self.selected_part
        self.branches[self.current_tag][index:index + 1] = [
            part[:offset], part[offset:]
        ]
        self._replace_text(self.part_text, part[:offset])
        self._replace_text(self.full_text, "".join(self.branches[self.current_tag]))
        self.commit_part()

    def merge_next(self) -> None:
        if self.selected_part is None:
            return
        self._save_part()
        index = self.selected_part
        parts = self.branches[self.current_tag]
        if index + 1 < len(parts):
            parts[index:index + 2] = [parts[index] + parts[index + 1]]
            self._replace_text(self.part_text, parts[index])
            self._replace_text(self.full_text, "".join(parts))
            self.commit_part()

    def move_part(self, step: int) -> None:
        if self.selected_part is None:
            return
        self._save_part()
        index = self.selected_part
        parts = self.branches[self.current_tag]
        target = index + step
        if 0 <= target < len(parts):
            parts[index], parts[target] = parts[target], parts[index]
            self.selected_part = target
            self._replace_text(self.part_text, parts[target])
            self._replace_text(self.full_text, "".join(parts))
            self.commit_part()

    def capture_spec(self) -> AssemblySpec:
        self._save_part()
        text = self.full_text.get("1.0", "end-1c")
        if text != "".join(self.branches[self.current_tag]):
            raise ValueError(
                "Полный текст изменён: нажмите «Разбить автоматически», "
                "чтобы обновить части."
            )
        return AssemblySpec(
            key=self.key_var.get().strip(), source=self.source_var.get().strip(),
            prefix=self.prefix_var.get().strip(),
            kind="event" if self.kind_var.get() == "Ивент страны" else "welcome",
            branches=tuple(
                TextBranch(tag, tuple(parts)) for tag, parts in self.branches.items()
            ),
        )

    def open_saved(self) -> None:
        if self.mod_root is None:
            self.choose_mod()
        if self.mod_root is None:
            return
        try:
            specs = load_specs(self.mod_root)
        except (OSError, ValueError, KeyError, TypeError) as error:
            messagebox.showerror("Проект", str(error))
            return
        if not specs:
            messagebox.showinfo("Проект", "В этом моде ещё нет сохранённых сборок.")
            return
        window = tk.Toplevel(self.root)
        window.title("Сохранённые сборки")
        listing = tk.Listbox(window, width=70, height=15)
        listing.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        for spec in specs:
            listing.insert(tk.END, spec.key)

        def load() -> None:
            if listing.curselection():
                self.load_spec(specs[listing.curselection()[0]])
                window.destroy()
        ttk.Button(window, text="Открыть", command=load).pack(pady=10)

    def load_spec(self, spec: AssemblySpec) -> None:
        self.source_var.set(spec.source)
        self.key_var.set(spec.key)
        self.prefix_var.set(spec.prefix)
        self.kind_var.set(
            "Ивент страны" if spec.kind == "event" else "Вступительный экран EaW"
        )
        self.branches = {branch.tag: list(branch.parts) for branch in spec.branches}
        # Use current generated values if a contributor edited localisation by hand.
        if self.mod_root is not None:
            values_path = (
                self.mod_root / f"localisation/{spec.language.removeprefix('l_')}"
                / f"checker_long_{spec.identity}_{spec.language}.yml"
            )
            current = {
                entry.key: decode_value(entry.raw_value)
                for entry in parse_localisation_file(values_path).entries
            }
            _, expected, _ = generated_values(spec)
            for branch in spec.branches:
                for number in range(1, len(branch.parts) + 1):
                    suffix = f"_{branch.tag}" if branch.tag else ""
                    key = f"{spec.key}{suffix}_part_{number:02d}"
                    if key in expected and key in current:
                        self.branches[branch.tag][number - 1] = current[key]
        self.current_tag = next(iter(self.branches))
        self.selected_part = None
        self._replace_text(self.full_text, "".join(self.branches[self.current_tag]))
        self._replace_text(self.part_text, "")
        self.refresh_parts()
        self.status_var.set("Сборка загружена для редактирования.")

    def preview(self) -> None:
        try:
            if self.mod_root is None:
                raise ValueError("Выберите папку мода.")
            plan = prepare_plan(self.mod_root, self.capture_spec())
        except (OSError, ValueError, KeyError, TypeError) as error:
            messagebox.showerror("Не удалось подготовить правки", str(error))
            return
        window = tk.Toplevel(self.root)
        window.title("Предпросмотр изменений")
        window.geometry("1000x720")
        content = ttk.Frame(window)
        content.pack(fill=tk.BOTH, expand=True)
        editor = self._text_editor(content)
        for note in plan.notes:
            editor.insert(tk.END, note + "\n\n")
        for change in plan.changes:
            relative = change.path.relative_to(plan.root).as_posix()
            before = (change.before or b"").decode("utf-8-sig").splitlines(True)
            after = change.after.decode("utf-8-sig").splitlines(True)
            editor.insert(tk.END, "".join(difflib.unified_diff(
                before, after, fromfile=relative, tofile=relative
            )) + "\n")
        editor.configure(state=tk.DISABLED)

        def save() -> None:
            try:
                backup = apply_plan(plan)
            except (OSError, ValueError) as error:
                messagebox.showerror("Правки не сохранены", str(error))
                return
            self.status_var.set(f"Сборка сохранена. Резервная копия: {backup}")
            window.destroy()
        ttk.Button(
            window, text="Сохранить в мод с резервной копией", command=save
        ).pack(side=tk.BOTTOM, pady=10)
