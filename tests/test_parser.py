from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from hoi4_l10n_checker.parser import parse_localisation_file


class ParserTests(unittest.TestCase):
    def write_file(self, root: Path, name: str, text: str) -> Path:
        path = root / name
        path.write_bytes(b"\xef\xbb\xbf" + text.encode("utf-8"))
        return path

    def test_valid_file_and_escaped_quote(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = self.write_file(
                root,
                "valid.yml",
                'l_english:\n KEY:0 "Line one\\nHe said \\"hello\\"."\n',
            )

            parsed = parse_localisation_file(path)

            self.assertEqual([], parsed.diagnostics)
            self.assertEqual(1, len(parsed.entries))
            self.assertEqual("KEY", parsed.entries[0].key)

    def test_invalid_escapes_are_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = self.write_file(
                root,
                "escapes.yml",
                'l_russian:\n KEY:0 "Ошибка \\k и \\ш."\n',
            )

            parsed = parse_localisation_file(path)
            invalid = [
                diagnostic
                for diagnostic in parsed.diagnostics
                if diagnostic.code == "INVALID_ESCAPE"
            ]

            self.assertEqual(2, len(invalid))
            self.assertEqual({"\\k", "\\ш"}, {item.character for item in invalid})

    def test_inner_quotes_are_allowed_but_unclosed_quote_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = self.write_file(
                root,
                "quotes.yml",
                (
                    'l_english:\n'
                    ' BAD:0 "He said "hello"."\n'
                    ' UNCLOSED:0 "No ending\n'
                ),
            )

            parsed = parse_localisation_file(path)
            codes = [diagnostic.code for diagnostic in parsed.diagnostics]

            self.assertNotIn("UNESCAPED_QUOTE", codes)
            self.assertIn("UNCLOSED_QUOTE", codes)
            self.assertEqual("He said \"hello\".", parsed.entries[0].raw_value)

    def test_comment_quotes_do_not_change_the_value_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = self.write_file(
                root,
                "comments.yml",
                'l_english:\n KEY:0 "Value" # Comment with "quotes"\n',
            )

            parsed = parse_localisation_file(path)

            self.assertEqual([], parsed.diagnostics)
            self.assertEqual("Value", parsed.entries[0].raw_value)

    def test_missing_and_embedded_bom_are_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            missing = root / "missing.yml"
            missing.write_bytes(b'l_english:\n KEY:0 "Value"\n')
            embedded = self.write_file(
                root,
                "embedded.yml",
                'l_english:\n KEY:0 "Before\ufeffAfter"\n',
            )

            missing_result = parse_localisation_file(missing)
            embedded_result = parse_localisation_file(embedded)

            self.assertIn(
                "MISSING_UTF8_BOM",
                {item.code for item in missing_result.diagnostics},
            )
            self.assertIn(
                "EMBEDDED_BOM",
                {item.code for item in embedded_result.diagnostics},
            )

    def test_invalid_utf8_reports_byte_location(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "broken.yml"
            path.write_bytes(
                b'\xef\xbb\xbfl_english:\n KEY:0 "Before ' + b"\xff" + b' after"\n'
            )

            parsed = parse_localisation_file(path)
            invalid = [
                diagnostic
                for diagnostic in parsed.diagnostics
                if diagnostic.code == "INVALID_UTF8"
            ]

            self.assertEqual(1, len(invalid))
            self.assertEqual(2, invalid[0].line)


if __name__ == "__main__":
    unittest.main()
