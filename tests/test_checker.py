from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from hoi4_l10n_checker import FontProfile, LocalisationChecker


class CheckerTests(unittest.TestCase):
    def create_profile(self, root: Path) -> FontProfile:
        fonts = root / "fonts" / "base"
        fonts.mkdir(parents=True)
        lines = [
            'info face="Test" size=16 unicode=1',
            "chars count=95",
        ]
        lines.extend(f"char id={codepoint}" for codepoint in range(32, 127))
        (fonts / "test.fnt").write_text("\n".join(lines), encoding="ascii")
        (root / "font_profile.json").write_text(
            json.dumps(
                {
                    "format_version": 1,
                    "default_language": "l_english",
                    "languages": {
                        "l_english": {
                            "families": {"Test": ["base/test.fnt"]}
                        },
                        "l_russian": {
                            "families": {"Test": ["base/test.fnt"]}
                        },
                    },
                }
            ),
            encoding="utf-8",
        )
        return FontProfile.load(root)

    @staticmethod
    def write_localisation(path: Path, text: str) -> None:
        path.write_bytes(b"\xef\xbb\xbf" + text.encode("utf-8"))

    def test_unsafe_glyph_and_markup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            profile = self.create_profile(root)
            localisation = root / "sample.yml"
            self.write_localisation(
                localisation,
                (
                    "l_english:\n"
                    ' KEY:0 "Safe $VARIABLE$ £icon [GetName] §Ytext§! …"\n'
                ),
            )

            result = LocalisationChecker(profile).scan(localisation)
            unsafe = [
                diagnostic
                for diagnostic in result.diagnostics
                if diagnostic.code == "UNSAFE_GLYPH"
            ]

            self.assertEqual(1, len(unsafe))
            self.assertEqual("…", unsafe[0].character)
            self.assertEqual(2, unsafe[0].line)

    def test_soft_and_strict_glyph_modes_only_change_glyph_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fonts = root / "fonts" / "base"
            fonts.mkdir(parents=True)
            ascii_lines = [
                'info face="ASCII" size=16 unicode=1',
                "chars count=95",
                *(f"char id={codepoint}" for codepoint in range(32, 127)),
            ]
            extended_lines = [
                'info face="Extended" size=16 unicode=1',
                "chars count=96",
                *(f"char id={codepoint}" for codepoint in range(32, 127)),
                "char id=8230",
            ]
            (fonts / "ascii.fnt").write_text(
                "\n".join(ascii_lines),
                encoding="ascii",
            )
            (fonts / "extended.fnt").write_text(
                "\n".join(extended_lines),
                encoding="ascii",
            )
            (root / "font_profile.json").write_text(
                json.dumps(
                    {
                        "format_version": 1,
                        "default_language": "l_english",
                        "languages": {
                            "l_english": {
                                "families": {
                                    "ASCII": ["base/ascii.fnt"],
                                    "Extended": ["base/extended.fnt"],
                                }
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            localisation = root / "sample.yml"
            self.write_localisation(
                localisation,
                (
                    "l_english:\n"
                    ' KEY:0 "An ellipsis…"\n'
                    ' KEY:0 "Another ellipsis…"\n'
                ),
            )

            checker = LocalisationChecker(FontProfile.load(root))
            soft_result = checker.scan(localisation, glyph_mode="soft")
            strict_result = checker.scan(localisation, glyph_mode="strict")
            excluded_soft_result = checker.scan(
                localisation,
                glyph_mode="soft",
                excluded_characters=frozenset({"…"}),
            )
            excluded_strict_result = checker.scan(
                localisation,
                glyph_mode="strict",
                excluded_characters=frozenset({"…"}),
            )

            self.assertFalse(
                any(
                    diagnostic.code == "UNSAFE_GLYPH"
                    and diagnostic.character == "…"
                    for diagnostic in soft_result.diagnostics
                )
            )
            strict_unsafe = [
                diagnostic
                for diagnostic in strict_result.diagnostics
                if diagnostic.code == "UNSAFE_GLYPH"
                and diagnostic.character == "…"
            ]
            self.assertEqual(2, len(strict_unsafe))
            for result in (excluded_soft_result, excluded_strict_result):
                self.assertFalse(
                    any(
                        diagnostic.code == "UNSAFE_GLYPH"
                        and diagnostic.character == "…"
                        for diagnostic in result.diagnostics
                    )
                )
            self.assertEqual(
                [
                    diagnostic
                    for diagnostic in soft_result.diagnostics
                    if diagnostic.severity == "error"
                ],
                [
                    diagnostic
                    for diagnostic in strict_result.diagnostics
                    if diagnostic.severity == "error"
                ],
            )
            self.assertEqual(
                [
                    diagnostic
                    for diagnostic in soft_result.diagnostics
                    if diagnostic.severity == "error"
                ],
                [
                    diagnostic
                    for diagnostic in excluded_strict_result.diagnostics
                    if diagnostic.severity == "error"
                ],
            )

    def test_context_only_families_do_not_change_soft_or_strict_coverage(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fonts = root / "fonts" / "base"
            fonts.mkdir(parents=True)
            regular_lines = [
                'info face="Regular" size=16 unicode=1',
                "chars count=96",
                *(f"char id={codepoint}" for codepoint in range(32, 127)),
                "char id=8230",
            ]
            map_lines = [
                'info face="Map" size=16 unicode=1',
                "chars count=95",
                *(f"char id={codepoint}" for codepoint in range(32, 127)),
            ]
            (fonts / "regular.fnt").write_text(
                "\n".join(regular_lines),
                encoding="ascii",
            )
            (fonts / "map.fnt").write_text(
                "\n".join(map_lines),
                encoding="ascii",
            )
            (root / "font_profile.json").write_text(
                json.dumps(
                    {
                        "format_version": 1,
                        "default_language": "l_english",
                        "context_only_families": ["Map"],
                        "languages": {
                            "l_english": {
                                "families": {
                                    "Regular": ["base/regular.fnt"],
                                    "Map": ["base/map.fnt"],
                                }
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            profile = FontProfile.load(root)
            self.assertIn(8230, profile.coverage_for("l_english", "soft") or ())
            self.assertIn(8230, profile.coverage_for("l_english", "strict") or ())
            self.assertNotIn(
                8230,
                profile.coverage_for_family("l_english", "Map") or (),
            )
            self.assertEqual(1, profile.family_count_for("l_english"))

    def test_ansi_font_ids_are_decoded_as_windows_1252(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fonts = root / "fonts" / "base"
            fonts.mkdir(parents=True)
            lines = [
                'info face="ANSI" size=16 charset="ANSI"',
                "chars count=96",
                *(f"char id={codepoint}" for codepoint in range(32, 127)),
                "char id=151",
            ]
            (fonts / "ansi.fnt").write_text("\n".join(lines), encoding="ascii")
            (root / "font_profile.json").write_text(
                json.dumps(
                    {
                        "format_version": 1,
                        "default_language": "l_english",
                        "languages": {
                            "l_english": {
                                "families": {"ANSI": ["base/ansi.fnt"]}
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            localisation = root / "sample.yml"
            self.write_localisation(
                localisation,
                'l_english:\n KEY:0 "An em dash—"\n',
            )

            checker = LocalisationChecker(FontProfile.load(root))
            for mode in ("soft", "strict"):
                result = checker.scan(localisation, glyph_mode=mode)
                self.assertFalse(
                    any(
                        diagnostic.code == "UNSAFE_GLYPH"
                        and diagnostic.character == "—"
                        for diagnostic in result.diagnostics
                    ),
                    msg=f"U+2014 was rejected in {mode} mode",
                )

    def test_contextual_mode_filters_only_resolved_glyph_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fonts = root / "fonts" / "base"
            fonts.mkdir(parents=True)
            ascii_lines = [
                'info face="ASCII" size=16 unicode=1',
                "chars count=95",
                *(f"char id={codepoint}" for codepoint in range(32, 127)),
            ]
            extended_lines = [
                'info face="Extended" size=16 unicode=1',
                "chars count=96",
                *(f"char id={codepoint}" for codepoint in range(32, 127)),
                "char id=8230",
            ]
            (fonts / "ascii.fnt").write_text(
                "\n".join(ascii_lines),
                encoding="ascii",
            )
            (fonts / "extended.fnt").write_text(
                "\n".join(extended_lines),
                encoding="ascii",
            )
            (root / "font_profile.json").write_text(
                json.dumps(
                    {
                        "format_version": 1,
                        "default_language": "l_english",
                        "languages": {
                            "l_english": {
                                "families": {
                                    "ASCII": ["base/ascii.fnt"],
                                    "Extended": ["base/extended.fnt"],
                                }
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            (root / "descriptor.mod").write_text(
                'name="Context Test"\n',
                encoding="utf-8",
            )
            interface = root / "interface"
            interface.mkdir()
            (interface / "context.gui").write_text(
                (
                    "guiTypes = {\n"
                    "  instantTextBoxType = {\n"
                    '    font = "Extended"\n'
                    '    text = "SUPPORTED_KEY"\n'
                    "  }\n"
                    "  instantTextBoxType = {\n"
                    '    font = "ASCII"\n'
                    '    text = "MISSING_KEY"\n'
                    "  }\n"
                    "}\n"
                ),
                encoding="utf-8",
            )
            localisation = root / "localisation" / "sample.yml"
            localisation.parent.mkdir()
            self.write_localisation(
                localisation,
                (
                    "l_english:\n"
                    ' SUPPORTED_KEY:0 "Ellipsis…"\n'
                    ' MISSING_KEY:0 "Ellipsis…"\n'
                    ' UNKNOWN_KEY:0 "Ellipsis…"\n'
                ),
            )

            checker = LocalisationChecker(FontProfile.load(root))
            classic = checker.scan(localisation, glyph_mode="strict")
            contextual_without_root = checker.scan(
                localisation,
                glyph_mode="contextual",
            )
            contextual = checker.scan(
                localisation,
                glyph_mode="contextual",
                context_mod_root=root,
            )
            contextual_with_unknown = checker.scan(
                localisation,
                glyph_mode="contextual",
                context_mod_root=root,
                show_unknown_context_warnings=True,
            )
            classic_keys = {
                item.key
                for item in classic.diagnostics
                if item.code == "UNSAFE_GLYPH"
            }
            contextual_warnings = [
                item
                for item in contextual.diagnostics
                if item.code == "UNSAFE_GLYPH"
            ]

            self.assertEqual(
                {"SUPPORTED_KEY", "MISSING_KEY", "UNKNOWN_KEY"},
                classic_keys,
            )
            self.assertEqual(
                classic_keys,
                {
                    item.key
                    for item in contextual_without_root.diagnostics
                    if item.code == "UNSAFE_GLYPH"
                },
            )
            self.assertEqual(
                {"MISSING_KEY"},
                {item.key for item in contextual_warnings},
            )
            self.assertIn(
                "ASCII",
                next(
                    item.message
                    for item in contextual_warnings
                    if item.key == "MISSING_KEY"
                ),
            )
            self.assertEqual(1, contextual.contextual_filtered_warnings)
            self.assertEqual(1, contextual.contextual_unresolved_warnings)
            self.assertEqual(2, contextual.context_resolved_keys)
            self.assertEqual(
                {"UNKNOWN_KEY"},
                {
                    item.key
                    for item in contextual_with_unknown.diagnostics
                    if item.code == "UNKNOWN_FONT_CONTEXT"
                },
            )
            self.assertNotIn(
                "UNKNOWN_KEY",
                {
                    item.key
                    for item in contextual_with_unknown.diagnostics
                    if item.code == "UNSAFE_GLYPH"
                },
            )

    def test_semantic_context_checks_every_font_used_by_dynamic_key(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fonts = root / "fonts" / "base"
            fonts.mkdir(parents=True)
            ascii_lines = [
                'info face="Header" size=16 unicode=1',
                "chars count=95",
                *(f"char id={codepoint}" for codepoint in range(32, 127)),
            ]
            extended_lines = [
                'info face="Body" size=16 unicode=1',
                "chars count=96",
                *(f"char id={codepoint}" for codepoint in range(32, 127)),
                "char id=8230",
            ]
            (fonts / "header.fnt").write_text(
                "\n".join(ascii_lines),
                encoding="ascii",
            )
            (fonts / "body.fnt").write_text(
                "\n".join(extended_lines),
                encoding="ascii",
            )
            (root / "font_profile.json").write_text(
                json.dumps(
                    {
                        "format_version": 1,
                        "default_language": "l_english",
                        "languages": {
                            "l_english": {
                                "families": {
                                    "Header": ["base/header.fnt"],
                                    "Body": ["base/body.fnt"],
                                }
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            (root / "descriptor.mod").write_text(
                'name="Semantic Checker Test"\n',
                encoding="utf-8",
            )
            interface = root / "interface"
            interface.mkdir()
            (interface / "nationalfocusview.gui").write_text(
                (
                    "guiTypes = {\n"
                    "  containerWindowType = {\n"
                    '    name = "national_focus_item"\n'
                    "    instantTextBoxType = {\n"
                    '      name = "name"\n'
                    '      font = "Body"\n'
                    "    }\n"
                    "  }\n"
                    "  containerWindowType = {\n"
                    '    name = "national_focus_detail_view"\n'
                    "    instantTextBoxType = {\n"
                    '      name = "name"\n'
                    '      font = "Header"\n'
                    "    }\n"
                    "    instantTextBoxType = {\n"
                    '      name = "desc"\n'
                    '      font = "Body"\n'
                    "    }\n"
                    "  }\n"
                    "}\n"
                ),
                encoding="utf-8",
            )
            focus_file = root / "common" / "national_focus" / "test.txt"
            focus_file.parent.mkdir(parents=True)
            focus_file.write_text(
                "focus_tree = { focus = { id = DYNAMIC_FOCUS } }\n",
                encoding="utf-8",
            )
            localisation = root / "localisation" / "sample.yml"
            localisation.parent.mkdir()
            self.write_localisation(
                localisation,
                (
                    "l_english:\n"
                    ' DYNAMIC_FOCUS:0 "Name…"\n'
                    ' DYNAMIC_FOCUS_desc:0 "Description…"\n'
                ),
            )

            result = LocalisationChecker(FontProfile.load(root)).scan(
                localisation,
                glyph_mode="contextual",
                context_mod_root=root,
            )
            glyph_warnings = [
                item
                for item in result.diagnostics
                if item.code == "UNSAFE_GLYPH"
            ]

            self.assertEqual(
                ["DYNAMIC_FOCUS"],
                [item.key for item in glyph_warnings],
            )
            self.assertIn("Header", glyph_warnings[0].message)
            self.assertEqual(1, result.contextual_filtered_warnings)
            self.assertEqual(0, result.contextual_unresolved_warnings)
            self.assertEqual(2, result.context_semantic_keys)

    def test_duplicate_keys_are_scoped_by_language(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            profile = self.create_profile(root)
            selected = root / "localisation"
            selected.mkdir()
            self.write_localisation(
                selected / "one.yml",
                'l_english:\n SAME_KEY:0 "One"\n',
            )
            self.write_localisation(
                selected / "two.yml",
                'l_english:\n SAME_KEY:0 "Two"\n',
            )
            self.write_localisation(
                selected / "russian.yml",
                'l_russian:\n SAME_KEY:0 "Three"\n',
            )

            result = LocalisationChecker(profile).scan(selected)
            duplicates = [
                diagnostic
                for diagnostic in result.diagnostics
                if diagnostic.code == "DUPLICATE_KEY"
            ]

            self.assertEqual(2, len(duplicates))
            self.assertTrue(all(item.key == "SAME_KEY" for item in duplicates))

    def test_possible_mojibake_is_separate_warning(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            profile = self.create_profile(root)
            localisation = root / "mojibake.yml"
            self.write_localisation(
                localisation,
                'l_russian:\n KEY:0 "РўРµРєСЃС‚"\n',
            )

            result = LocalisationChecker(profile).scan(localisation)

            self.assertIn(
                "POSSIBLE_MOJIBAKE",
                {diagnostic.code for diagnostic in result.diagnostics},
            )


if __name__ == "__main__":
    unittest.main()
