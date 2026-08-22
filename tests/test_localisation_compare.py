from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from hoi4_l10n_checker.localisation_compare import (
    LocalisationComparator,
)


class LocalisationComparatorTests(unittest.TestCase):
    @staticmethod
    def write_localisation(
        path: Path,
        language: str,
        lines: list[str],
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(
            b"\xef\xbb\xbf"
            + (
                f"{language}:\n"
                + "\n".join(lines)
                + "\n"
            ).encode("utf-8")
        )

    def test_compares_global_keys_and_reports_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            mod = Path(temporary) / "mod"
            english_root = mod / "localisation" / "unusual"
            russian_root = mod / "localisation" / "russian"
            self.write_localisation(
                english_root / "sample_l_english.yml",
                "l_english",
                [
                    ' SHARED:0 "Shared"',
                    ' ONLY_ENGLISH:0 "English"',
                    ' DUPLICATE:0 "First"',
                    ' DUPLICATE:0 "Second"',
                ],
            )
            self.write_localisation(
                russian_root / "sample_l_russian.yml",
                "l_russian",
                [
                    ' SHARED:0 "Общий"',
                    ' ONLY_RUSSIAN:0 "Русский"',
                    ' DUPLICATE:0 "Дубль"',
                ],
            )

            progress = []
            result = LocalisationComparator().scan(
                english_root,
                russian_root,
                progress=lambda current, total, path: progress.append(
                    (current, total, path)
                ),
            )

            self.assertEqual(2, result.files_checked)
            self.assertEqual(1, result.english_files)
            self.assertEqual(1, result.russian_files)
            self.assertEqual(3, result.english_keys)
            self.assertEqual(3, result.russian_keys)
            self.assertEqual(2, result.common_keys)
            self.assertEqual(1, result.missing_russian)
            self.assertEqual(1, result.missing_english)
            self.assertEqual(1, result.duplicate_english)
            self.assertEqual(0, result.duplicate_russian)
            self.assertEqual(0, result.parse_errors)
            self.assertEqual(2, len(progress))

            issues = {item.code: item for item in result.issues}
            self.assertEqual(
                "ONLY_ENGLISH",
                issues["MISSING_IN_RUSSIAN"].key,
            )
            missing_russian = issues["MISSING_IN_RUSSIAN"]
            self.assertEqual(
                (english_root / "sample_l_english.yml").resolve(),
                missing_russian.english_path,
            )
            self.assertEqual(
                (russian_root / "sample_l_russian.yml").resolve(),
                missing_russian.russian_path,
            )
            self.assertEqual(3, missing_russian.russian_line)
            self.assertEqual(
                "ONLY_RUSSIAN",
                issues["MISSING_IN_ENGLISH"].key,
            )
            missing_english = issues["MISSING_IN_ENGLISH"]
            self.assertEqual(
                (english_root / "sample_l_english.yml").resolve(),
                missing_english.english_path,
            )
            self.assertEqual(3, missing_english.english_line)
            self.assertEqual(
                (russian_root / "sample_l_russian.yml").resolve(),
                missing_english.russian_path,
            )
            duplicate = issues["DUPLICATE_ENGLISH_KEY"]
            self.assertEqual("DUPLICATE", duplicate.key)
            self.assertEqual(5, duplicate.line)
            self.assertEqual(5, duplicate.english_line)
            self.assertEqual(4, duplicate.russian_line)
            self.assertIsNotNone(
                duplicate.diagnostic_for("english")
            )
            self.assertIsNotNone(
                duplicate.diagnostic_for("russian")
            )
            self.assertIn("Первое объявление", duplicate.message)

    def test_reports_parse_errors_that_can_hide_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            mod = Path(temporary) / "mod"
            english_root = mod / "localisation" / "english"
            russian_root = mod / "localisation" / "russian"
            self.write_localisation(
                english_root / "broken.yml",
                "l_english",
                [' BROKEN:0 "No closing quote'],
            )
            self.write_localisation(
                russian_root / "valid.yml",
                "l_russian",
                [' VALID:0 "Текст"'],
            )

            result = LocalisationComparator().scan(
                english_root,
                russian_root,
            )

            errors = [
                item
                for item in result.issues
                if item.category == "parse_error"
            ]
            self.assertEqual(1, result.parse_errors)
            self.assertEqual("UNCLOSED_QUOTE", errors[0].code)
            self.assertEqual("error", errors[0].severity)

    def test_excludes_selected_files_for_current_comparison(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            mod = Path(temporary) / "mod"
            english_root = mod / "localisation" / "english"
            russian_root = mod / "localisation" / "russian"
            english_main = english_root / "main_l_english.yml"
            english_music = english_root / "music_l_english.yml"
            russian_main = russian_root / "main_l_russian.yml"
            russian_music = russian_root / "music_l_russian.yml"
            self.write_localisation(
                english_main,
                "l_english",
                [' MAIN:0 "Main"'],
            )
            self.write_localisation(
                english_music,
                "l_english",
                [' MUSIC_ONLY_EN:0 "Song"'],
            )
            self.write_localisation(
                russian_main,
                "l_russian",
                [' MAIN:0 "Основной"'],
            )
            self.write_localisation(
                russian_music,
                "l_russian",
                [' MUSIC_ONLY_RU:0 "Песня"'],
            )
            progress = []

            result = LocalisationComparator().scan(
                english_root,
                russian_root,
                progress=lambda current, total, path: progress.append(
                    (current, total, path)
                ),
                excluded_english_files=(english_music,),
                excluded_russian_files=(russian_music,),
            )

            self.assertEqual(2, result.files_checked)
            self.assertEqual(1, result.english_files)
            self.assertEqual(1, result.russian_files)
            self.assertEqual(1, result.english_files_excluded)
            self.assertEqual(1, result.russian_files_excluded)
            self.assertEqual(2, result.files_excluded)
            self.assertEqual(1, result.common_keys)
            self.assertEqual([], result.issues)
            self.assertEqual(2, len(progress))

    def test_requires_localisation_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            valid = Path(temporary) / "valid"
            valid.mkdir()
            with self.assertRaises(ValueError):
                LocalisationComparator().scan(
                    Path(temporary) / "missing",
                    valid,
                )


if __name__ == "__main__":
    unittest.main()
