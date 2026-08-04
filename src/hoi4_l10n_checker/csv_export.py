from __future__ import annotations

import csv
from collections.abc import Iterable, Sequence
from pathlib import Path


def export_csv(
    path: Path,
    headers: Sequence[str],
    rows: Iterable[Sequence[object]],
) -> int:
    """Write table rows in an Excel-friendly UTF-8 CSV file."""
    row_count = 0
    with path.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.writer(
            output,
            delimiter=";",
            lineterminator="\n",
        )
        writer.writerow(headers)
        for row in rows:
            writer.writerow(row)
            row_count += 1
    return row_count
