from __future__ import annotations

import sys
from pathlib import Path


def _source_root() -> Path:
    return Path(__file__).resolve().parent


def _application_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return _source_root()


SOURCE_DIRECTORY = _source_root() / "src"
if str(SOURCE_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SOURCE_DIRECTORY))

from hoi4_l10n_checker.gui import run_gui  # noqa: E402

if __name__ == "__main__":
    run_gui(_application_root())

