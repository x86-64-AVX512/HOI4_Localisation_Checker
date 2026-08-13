from __future__ import annotations

import tkinter as tk

_VALID_FOREGROUND = "#137333"
_INVALID_FOREGROUND = "#B42318"
_LAVA_RED = "#CF1020"


class RequirementIndicator:
    """A path/status label that can draw attention to a blocked action."""

    def __init__(
        self,
        parent: tk.Misc,
        *,
        anchor: str = tk.W,
    ) -> None:
        self.variable = tk.StringVar(master=parent)
        self.widget = tk.Label(
            parent,
            textvariable=self.variable,
            anchor=anchor,
            justify=tk.LEFT,
            padx=4,
            pady=2,
        )
        self._normal_background = str(self.widget.cget("background"))
        self._normal_foreground = _INVALID_FOREGROUND
        self._flash_after_id: str | None = None
        self._flash_steps_remaining = 0
        self.valid = False
        self.message = ""

    def grid(self, **options: object) -> None:
        self.widget.grid(**options)

    def pack(self, **options: object) -> None:
        self.widget.pack(**options)

    def set(self, valid: bool, message: str) -> None:
        self.valid = valid
        self.message = message
        self._normal_foreground = (
            _VALID_FOREGROUND if valid else _INVALID_FOREGROUND
        )
        self.variable.set(f"{'✓' if valid else '✕'} {message}")
        if self._flash_after_id is None:
            self._restore_colours()

    def flash(self, cycles: int = 4, interval_ms: int = 220) -> None:
        if self.valid:
            return
        self.stop_flashing()
        self._flash_steps_remaining = max(cycles, 1) * 2
        self._flash_step(interval_ms)

    def stop_flashing(self) -> None:
        if self._flash_after_id is not None:
            try:
                self.widget.after_cancel(self._flash_after_id)
            except tk.TclError:
                pass
        self._flash_after_id = None
        self._flash_steps_remaining = 0
        self._restore_colours()

    def _flash_step(self, interval_ms: int) -> None:
        if self._flash_steps_remaining <= 0:
            self._flash_after_id = None
            self._restore_colours()
            return
        highlighted = self._flash_steps_remaining % 2 == 0
        try:
            self.widget.configure(
                background=(
                    _LAVA_RED if highlighted else self._normal_background
                ),
                foreground=(
                    "white" if highlighted else self._normal_foreground
                ),
            )
            self._flash_steps_remaining -= 1
            self._flash_after_id = self.widget.after(
                interval_ms,
                self._flash_step,
                interval_ms,
            )
        except tk.TclError:
            self._flash_after_id = None

    def _restore_colours(self) -> None:
        try:
            self.widget.configure(
                background=self._normal_background,
                foreground=self._normal_foreground,
            )
        except tk.TclError:
            pass
