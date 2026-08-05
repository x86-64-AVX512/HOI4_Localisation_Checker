from __future__ import annotations

import tkinter as tk
import unicodedata
from collections.abc import Callable, Iterable
from tkinter import messagebox, ttk

from .settings import SettingsError


class CharacterExceptionsController:
    """Owns UNSAFE_GLYPH exceptions and their editor dialog."""

    def __init__(
        self,
        root: tk.Misc,
        characters: Iterable[str],
        persist: Callable[[frozenset[str]], None],
        set_count: Callable[[int], None],
        set_status: Callable[[str], None],
        selected_character: Callable[[], str],
        *,
        show_error: Callable[[str, str], object] | None = None,
    ) -> None:
        self.root = root
        self._characters = {
            character
            for value in characters
            for character in value
        }
        self._persist = persist
        self._set_count = set_count
        self._set_status = set_status
        self._selected_character = selected_character
        self._show_error = show_error or messagebox.showerror
        self.dialog: tk.Toplevel | None = None
        self.listbox: tk.Listbox | None = None
        self._listed_characters: list[str] = []

    @property
    def characters(self) -> frozenset[str]:
        return frozenset(self._characters)

    def contains(self, character: str) -> bool:
        return character in self._characters

    @staticmethod
    def character_label(character: str) -> str:
        if character == " ":
            display = "обычный пробел"
        elif character == "\u00a0":
            display = "неразрывный пробел"
        elif character == "\u200b":
            display = "пробел нулевой ширины"
        elif character.isprintable():
            display = f"«{character}»"
        else:
            display = "непечатный символ"
        unicode_name = unicodedata.name(character, "UNNAMED CHARACTER")
        return f"{display} — U+{ord(character):04X} — {unicode_name}"

    def refresh(self) -> None:
        self._set_count(len(self._characters))
        listbox = self.listbox
        if listbox is None or not listbox.winfo_exists():
            return

        self._listed_characters = sorted(self._characters, key=ord)
        listbox.delete(0, tk.END)
        for character in self._listed_characters:
            listbox.insert(tk.END, self.character_label(character))

    def add_text(self, text: str) -> bool:
        new_characters = set(text) - self._characters
        if not new_characters:
            self.root.bell()
            return False

        previous = self._characters.copy()
        self._characters.update(new_characters)
        if not self._save(previous):
            return False

        codes = self._format_codes(new_characters)
        self._set_status(
            f"Добавлено в исключения: {codes}. "
            "Будет применено при следующей проверке."
        )
        return True

    def add_selected_character(self) -> None:
        character = self._selected_character()
        if not character or character in self._characters:
            self.root.bell()
            return
        self.add_text(character)

    def remove_selected(self) -> None:
        listbox = self.listbox
        if listbox is None or not listbox.winfo_exists():
            return
        selected_indices = listbox.curselection()
        if not selected_indices:
            self.root.bell()
            return

        removed = {
            self._listed_characters[index]
            for index in selected_indices
        }
        previous = self._characters.copy()
        self._characters.difference_update(removed)
        if not self._save(previous):
            return

        codes = self._format_codes(removed)
        self._set_status(
            f"Удалено из исключений: {codes}. "
            "Будет применено при следующей проверке."
        )

    def open_dialog(self) -> None:
        dialog = self.dialog
        if dialog is not None and dialog.winfo_exists():
            dialog.lift()
            dialog.focus_force()
            return

        dialog = tk.Toplevel(self.root)
        self.dialog = dialog
        dialog.title("Исключения UNSAFE_GLYPH")
        dialog.geometry("680x390")
        dialog.minsize(560, 320)
        dialog.transient(self.root)
        dialog.protocol("WM_DELETE_WINDOW", self.close_dialog)

        outer = ttk.Frame(dialog, padding=12)
        outer.pack(fill=tk.BOTH, expand=True)
        ttk.Label(
            outer,
            text=(
                "Добавленные символы не считаются небезопасными ни в мягком, "
                "ни в жёстком режиме. Можно вставить сразу несколько символов."
            ),
            justify=tk.LEFT,
            wraplength=640,
        ).pack(fill=tk.X)

        input_frame = ttk.Frame(outer)
        input_frame.pack(fill=tk.X, pady=(10, 8))
        input_var = tk.StringVar()
        entry = ttk.Entry(input_frame, textvariable=input_var)
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

        def add_from_entry(_event: object | None = None) -> str:
            if self.add_text(input_var.get()):
                input_var.set("")
            return "break"

        ttk.Button(
            input_frame,
            text="Добавить символы",
            command=add_from_entry,
        ).pack(side=tk.LEFT, padx=(8, 0))
        entry.bind("<Return>", add_from_entry)

        list_frame = ttk.Frame(outer)
        list_frame.pack(fill=tk.BOTH, expand=True)
        self.listbox = tk.Listbox(
            list_frame,
            selectmode=tk.EXTENDED,
            exportselection=False,
        )
        scrollbar = ttk.Scrollbar(
            list_frame,
            orient=tk.VERTICAL,
            command=self.listbox.yview,
        )
        self.listbox.configure(yscrollcommand=scrollbar.set)
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        buttons = ttk.Frame(outer)
        buttons.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(
            buttons,
            text="Удалить выбранные",
            command=self.remove_selected,
        ).pack(side=tk.LEFT)
        ttk.Button(
            buttons,
            text="Закрыть",
            command=self.close_dialog,
        ).pack(side=tk.RIGHT)

        self.refresh()
        dialog.grab_set()
        entry.focus_set()

    def close_dialog(self) -> None:
        dialog = self.dialog
        self.dialog = None
        self.listbox = None
        self._listed_characters = []
        if dialog is not None and dialog.winfo_exists():
            dialog.grab_release()
            dialog.destroy()

    def _save(self, previous: set[str]) -> bool:
        try:
            self._persist(self.characters)
        except SettingsError as error:
            self._characters = previous
            self.refresh()
            self._show_error("Исключения не сохранены", str(error))
            return False
        self.refresh()
        return True

    @staticmethod
    def _format_codes(characters: Iterable[str]) -> str:
        return ", ".join(
            f"U+{ord(character):04X}"
            for character in sorted(characters, key=ord)
        )
