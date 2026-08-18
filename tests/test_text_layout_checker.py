from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from hoi4_l10n_checker.focus_preview_cli import (
    FOCUS_PREVIEW_PROTOCOL,
    FocusPreviewBatchResult,
    FocusPreviewResult,
)
from hoi4_l10n_checker.text_layout_checker import (
    TextLayoutChecker,
    TextLayoutOptions,
)


class FakePreviewRunner:
    def __init__(self) -> None:
        self.items = []
        self.policy = ""

    def check(self, items, *, policy):
        self.items = list(items)
        self.policy = policy
        results = []
        for item in self.items:
            red = item.key == "FOCUS_A_desc"
            results.append(
                FocusPreviewResult(
                    request_id=item.request_id,
                    key=item.key,
                    status="red" if red else "green",
                    fits=not red,
                    fits_visual=not red,
                    fits_strict=not red,
                    description_lines=7 if red else 1,
                    description_height_px=126 if red else 18,
                    formal_overflow_px=56 if red else 0,
                    panel_overlap_px=13 if red else 0,
                    intersects_effect_panel=red,
                    missing_glyphs=("🦄",) if red else (),
                )
            )
        return FocusPreviewBatchResult(
            protocol=FOCUS_PREVIEW_PROTOCOL,
            version="0.7.5",
            results=tuple(results),
            errors=(),
            total=len(results),
            green=sum(item.status == "green" for item in results),
            yellow=0,
            red=sum(item.status == "red" for item in results),
            failed_policy=sum(not item.fits for item in results),
        )


class TextLayoutCheckerTests(unittest.TestCase):
    @staticmethod
    def write_localisation(path: Path, lines: list[str]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(
            b"\xef\xbb\xbf"
            + ("l_english:\n" + "\n".join(lines) + "\n").encode("utf-8")
        )

    def create_mod(self, root: Path) -> tuple[Path, Path]:
        mod = root / "mod"
        localisation = mod / "localisation" / "english" / "sample.yml"
        self.write_localisation(
            localisation,
            [
                ' FOCUS_A_desc:0 "12345\\n6"',
                r' FOCUS_ESCAPED_desc:0 "12345\\n6"',
                ' EVENT_DESC:0 "123456"',
                ' WELCOME_WRAPPER:0 "[Root.GetIntro]"',
                ' WELCOME_BODY:0 "1234567"',
            ],
        )

        focus = mod / "common" / "national_focus" / "test.txt"
        focus.parent.mkdir(parents=True)
        focus.write_text(
            (
                "focus_tree = {\n"
                " focus = { id = FOCUS_A }\n"
                " focus = { id = FOCUS_ESCAPED }\n"
                "}\n"
            ),
            encoding="utf-8",
        )
        event = mod / "events" / "test.txt"
        event.parent.mkdir(parents=True)
        event.write_text(
            "country_event = { id = test.1 desc = EVENT_DESC }\n",
            encoding="utf-8",
        )
        gui = mod / "interface" / "welcome.gui"
        gui.parent.mkdir(parents=True)
        gui.write_text(
            (
                "guiTypes = {\n"
                " containerWindowType = {\n"
                '  name = "eaw_ws_tab_1_slider"\n'
                "  instantTextboxType = {\n"
                '   name = "tab_1_text"\n'
                '   font = "hoi_20bs"\n'
                '   text = "WELCOME_WRAPPER"\n'
                "  }\n"
                " }\n"
                "}\n"
            ),
            encoding="utf-8",
        )
        scripted = (
            mod
            / "common"
            / "scripted_localisation"
            / "welcome.txt"
        )
        scripted.parent.mkdir(parents=True)
        scripted.write_text(
            (
                "defined_text = {\n"
                " name = GetIntro\n"
                " text = { localization_key = WELCOME_BODY }\n"
                "}\n"
            ),
            encoding="utf-8",
        )
        return mod, localisation

    def test_length_checks_can_be_enabled_independently(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            mod, localisation = self.create_mod(Path(temporary))

            result = TextLayoutChecker().scan(
                localisation,
                mod_root=mod,
                options=TextLayoutOptions(
                    focus_enabled=True,
                    focus_mode="length",
                    focus_limit=5,
                    events_enabled=True,
                    event_limit=5,
                    welcome_enabled=True,
                    welcome_limit=6,
                ),
            )

            long_by_key = {
                diagnostic.key: diagnostic
                for diagnostic in result.diagnostics
                if diagnostic.code == "TEXT_TOO_LONG"
            }
            self.assertEqual(
                {
                    "FOCUS_A_desc",
                    "FOCUS_ESCAPED_desc",
                    "EVENT_DESC",
                    "WELCOME_BODY",
                },
                set(long_by_key),
            )
            self.assertEqual("Фокус", long_by_key["FOCUS_A_desc"].text_kind)
            self.assertEqual(
                "Определено по структуре",
                long_by_key["FOCUS_A_desc"].role_confidence,
            )
            self.assertIn(
                "common",
                long_by_key["FOCUS_A_desc"].role_evidence,
            )
            self.assertIn(
                "test.txt:2",
                long_by_key["FOCUS_A_desc"].role_evidence,
            )
            self.assertIn(
                "id + _desc",
                long_by_key["FOCUS_A_desc"].role_evidence,
            )
            self.assertEqual("Ивент", long_by_key["EVENT_DESC"].text_kind)
            self.assertEqual(
                "Подтверждено",
                long_by_key["EVENT_DESC"].role_confidence,
            )
            self.assertIn(
                "events",
                long_by_key["EVENT_DESC"].role_evidence,
            )
            self.assertIn(
                "test.txt:1",
                long_by_key["EVENT_DESC"].role_evidence,
            )
            self.assertEqual(
                "Вступительный экран",
                long_by_key["WELCOME_BODY"].text_kind,
            )
            self.assertEqual(
                "Подтверждено",
                long_by_key["WELCOME_BODY"].role_confidence,
            )
            self.assertIn(
                "scripted_localisation",
                long_by_key["WELCOME_BODY"].role_evidence,
            )
            self.assertIn(
                "welcome.txt:3",
                long_by_key["WELCOME_BODY"].role_evidence,
            )
            self.assertNotIn("WELCOME_WRAPPER", long_by_key)

            event_only = TextLayoutChecker().scan(
                localisation,
                mod_root=mod,
                options=TextLayoutOptions(
                    focus_enabled=False,
                    events_enabled=True,
                    event_limit=5,
                    welcome_enabled=False,
                ),
            )
            self.assertEqual(
                ["EVENT_DESC"],
                [item.key for item in event_only.diagnostics],
            )
            self.assertEqual(0, event_only.focus_checked)
            self.assertEqual(1, event_only.events_checked)
            self.assertEqual(0, event_only.welcome_checked)

    def test_russian_diagnostics_are_paired_with_english_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            mod, english = self.create_mod(root)
            russian = mod / "localisation" / "russian" / "sample.yml"
            russian.parent.mkdir(parents=True)
            russian.write_bytes(
                b"\xef\xbb\xbf"
                + (
                    'l_russian:\n FOCUS_A_desc:0 "123456789"\n'
                    ' FOCUS_MISSING_desc:0 "123456789"\n'
                ).encode("utf-8")
            )
            focus_path = mod / "common" / "national_focus" / "test.txt"
            focus_path.write_text(
                focus_path.read_text(encoding="utf-8")
                + "focus = { id = FOCUS_MISSING }\n",
                encoding="utf-8",
            )

            result = TextLayoutChecker().scan(
                russian,
                english_target=english,
                mod_root=mod,
                options=TextLayoutOptions(
                    focus_enabled=True,
                    focus_mode="length",
                    focus_limit=5,
                    events_enabled=False,
                    welcome_enabled=False,
                ),
            )

            self.assertEqual(1, result.english_files_checked)
            self.assertEqual(5, result.english_entries_checked)
            diagnostic = next(
                item for item in result.diagnostics
                if item.key == "FOCUS_A_desc"
            )
            issue = result.issue_for(diagnostic)
            english_location = issue.diagnostic_for("english")
            self.assertIsNotNone(english_location)
            assert english_location is not None
            self.assertEqual(english, english_location.path)
            self.assertEqual("FOCUS_A_desc", english_location.key)

            missing = next(
                item for item in result.diagnostics
                if item.key == "FOCUS_MISSING_desc"
            )
            fallback = result.issue_for(missing).diagnostic_for("english")
            self.assertIsNotNone(fallback)
            assert fallback is not None
            self.assertEqual(english, fallback.path)
            self.assertEqual(missing.line, fallback.line)

    def test_one_key_keeps_separate_evidence_for_multiple_roles(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            mod, localisation = self.create_mod(Path(temporary))
            (mod / "events" / "test.txt").write_text(
                (
                    "country_event = {\n"
                    " id = test.1\n"
                    " desc = FOCUS_A_desc\n"
                    "}\n"
                ),
                encoding="utf-8",
            )

            result = TextLayoutChecker().scan(
                localisation,
                mod_root=mod,
                options=TextLayoutOptions(
                    focus_enabled=True,
                    focus_mode="length",
                    focus_limit=5,
                    events_enabled=True,
                    event_limit=5,
                    welcome_enabled=False,
                ),
            )

            shared = [
                item
                for item in result.diagnostics
                if item.key == "FOCUS_A_desc"
            ]
            self.assertEqual(2, len(shared))
            self.assertEqual(
                {"Фокус", "Ивент"},
                {item.text_kind for item in shared},
            )
            evidence_by_kind = {
                item.text_kind: item.role_evidence
                for item in shared
            }
            self.assertIn("national_focus", evidence_by_kind["Фокус"])
            self.assertIn("events", evidence_by_kind["Ивент"])

    def test_focus_newline_mode_replaces_length_check(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            mod, localisation = self.create_mod(Path(temporary))

            result = TextLayoutChecker().scan(
                localisation,
                mod_root=mod,
                options=TextLayoutOptions(
                    focus_enabled=True,
                    focus_mode="newline",
                    focus_limit=1,
                    events_enabled=False,
                    welcome_enabled=False,
                ),
            )

            self.assertEqual(1, len(result.diagnostics))
            diagnostic = result.diagnostics[0]
            self.assertEqual("FOCUS_NEWLINE", diagnostic.code)
            self.assertEqual("FOCUS_A_desc", diagnostic.key)
            self.assertEqual("\\n", diagnostic.character)
            self.assertEqual(2, diagnostic.selection_length)
            self.assertFalse(
                any(
                    item.code == "TEXT_TOO_LONG"
                    for item in result.diagnostics
                )
            )

    def test_title_newlines_are_checked_independently_by_role(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            mod, localisation = self.create_mod(Path(temporary))
            titles = localisation.parent / "titles.yml"
            self.write_localisation(
                titles,
                [
                    ' FOCUS_A:0 "Focus\\nTitle"',
                    r' FOCUS_ESCAPED:0 "Focus\\nTitle"',
                    ' EVENT_TITLE:0 "Event\\nTitle"',
                    ' WELCOME_TITLE:0 "Welcome\\nTitle"',
                    ' NO_ROLE_TITLE:0 "Ignored\\nTitle"',
                ],
            )
            (mod / "events" / "test.txt").write_text(
                (
                    "country_event = {\n"
                    " id = test.1\n"
                    " title = EVENT_TITLE\n"
                    " desc = EVENT_DESC\n"
                    "}\n"
                ),
                encoding="utf-8",
            )
            with (mod / "interface" / "welcome.gui").open(
                "a",
                encoding="utf-8",
            ) as gui:
                gui.write(
                    "containerWindowType = {\n"
                    ' name = "welcome_screen_window"\n'
                    " instantTextboxType = {\n"
                    '  name = "tab_1_header"\n'
                    '  font = "hoi_24header"\n'
                    '  text = "WELCOME_TITLE"\n'
                    " }\n"
                    "}\n"
                )

            result = TextLayoutChecker().scan(
                localisation.parent,
                mod_root=mod,
                options=TextLayoutOptions(
                    focus_enabled=False,
                    events_enabled=False,
                    welcome_enabled=False,
                    title_newline_enabled=True,
                ),
            )

            self.assertEqual(4, result.titles_checked)
            self.assertEqual(3, result.title_newline_warning_count)
            warnings = {
                diagnostic.key: diagnostic
                for diagnostic in result.diagnostics
            }
            self.assertEqual(
                {"FOCUS_A", "EVENT_TITLE", "WELCOME_TITLE"},
                set(warnings),
            )
            self.assertEqual(
                "Заголовок фокуса",
                warnings["FOCUS_A"].text_kind,
            )
            self.assertEqual(
                "Заголовок ивента",
                warnings["EVENT_TITLE"].text_kind,
            )
            self.assertEqual(
                "Заголовок вступительного экрана",
                warnings["WELCOME_TITLE"].text_kind,
            )
            self.assertTrue(
                all(item.character == "\\n" for item in warnings.values())
            )
            self.assertTrue(
                all(item.selection_length == 2 for item in warnings.values())
            )

    def test_exact_focus_mode_checks_every_focus_and_shows_only_red(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            mod, localisation = self.create_mod(Path(temporary))
            preview = FakePreviewRunner()

            result = TextLayoutChecker(
                preview_factory=lambda _path: preview,
            ).scan(
                localisation,
                mod_root=mod,
                options=TextLayoutOptions(
                    focus_enabled=True,
                    focus_mode="exact",
                    focus_limit=100,
                    focus_preview_cli_path=Path("preview.exe"),
                    focus_preview_priority="auto_ru",
                    events_enabled=False,
                    welcome_enabled=False,
                ),
            )

            self.assertEqual(2, len(preview.items))
            self.assertEqual(
                {"FOCUS_A_desc", "FOCUS_ESCAPED_desc"},
                {item.key for item in preview.items},
            )
            self.assertTrue(
                all(item.glyph_priority == "en" for item in preview.items)
            )
            self.assertEqual("visual", preview.policy)
            self.assertEqual(2, result.preview_checked)
            self.assertEqual(1, result.preview_green)
            self.assertEqual(1, result.preview_red)
            self.assertEqual(1, len(result.diagnostics))

            diagnostic = result.diagnostics[0]
            self.assertEqual("FOCUS_PREVIEW_RED", diagnostic.code)
            self.assertEqual("FOCUS_A_desc", diagnostic.key)
            self.assertEqual("red", diagnostic.preview_status)
            self.assertEqual(7, diagnostic.preview_lines)
            self.assertEqual(126, diagnostic.preview_height_px)
            self.assertEqual(13, diagnostic.preview_overlap_px)
            self.assertEqual("🦄", diagnostic.missing_glyphs)
            self.assertIn("порог 100 не превышен", diagnostic.message)
            self.assertIn("13 px", diagnostic.message)

    def test_at_least_one_check_must_be_enabled(self) -> None:
        options = TextLayoutOptions(
            focus_enabled=False,
            events_enabled=False,
            welcome_enabled=False,
        )

        with self.assertRaises(ValueError):
            options.validate()


if __name__ == "__main__":
    unittest.main()
