from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from hoi4_l10n_checker.csv_export import export_csv


class CsvExportTests(unittest.TestCase):
    def test_writes_utf8_bom_semicolon_csv_and_preserves_row_order(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "results.csv"

            count = export_csv(
                path,
                ("Ключ", "Описание"),
                (
                    ("SECOND", 'Текст; с "кавычками"'),
                    ("FIRST", "Строка 1\nСтрока 2"),
                ),
            )

            raw = path.read_bytes()
            text = raw.decode("utf-8-sig")
            self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
            self.assertEqual(2, count)
            self.assertEqual(
                (
                    'Ключ;Описание\n'
                    'SECOND;"Текст; с ""кавычками"""\n'
                    'FIRST;"Строка 1\nСтрока 2"\n'
                ),
                text,
            )


if __name__ == "__main__":
    unittest.main()
