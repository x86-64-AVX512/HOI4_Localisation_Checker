from __future__ import annotations

import unittest
from collections import defaultdict
from pathlib import Path

from hoi4_l10n_checker.font_context_gui import (
    index_gui_blocks,
    merge_tooltip_roles,
)
from hoi4_l10n_checker.font_context_types import (
    ROLE_FOCUS_DESCRIPTION,
    ROLE_TOOLTIP,
    ROLE_WELCOME_TEXT,
    ROLE_WELCOME_TITLE,
    RoleEvidence,
)
from hoi4_l10n_checker.paradox_script import parse_blocks


class FontContextGuiTests(unittest.TestCase):
    def test_indexes_role_fonts_direct_keys_and_dynamic_functions(self) -> None:
        source_path = Path("interface/example.gui")
        blocks = parse_blocks(
            (
                "containerWindowType = {\n"
                '    name = "national_focus_detail_view"\n'
                "    instantTextBoxType = {\n"
                '        name = "desc"\n'
                '        font = "hoi_18mbs"\n'
                '        text = "[GetDynamicText]"\n'
                "    }\n"
                "}\n"
                "containerWindowType = {\n"
                '    name = "welcome_screen_window"\n'
                "    instantTextBoxType = {\n"
                '        name = "tab_1_text"\n'
                '        font = "hoi_20b"\n'
                '        text = "WELCOME_KEY"\n'
                "    }\n"
                "    instantTextBoxType = {\n"
                '        name = "tab_2_text"\n'
                '        font = "hoi_20b"\n'
                '        text = "[GetWelcomeText]"\n'
                "    }\n"
                "    instantTextBoxType = {\n"
                '        name = "tab_1_header"\n'
                '        font = "hoi_24header"\n'
                '        text = "WELCOME_HEADER"\n'
                "    }\n"
                "    instantTextBoxType = {\n"
                '        name = "tab_2_header"\n'
                '        font = "hoi_24header"\n'
                '        text = "[GetWelcomeTitle]"\n'
                "    }\n"
                "}\n"
            ),
            source_path,
        )
        key_fonts: dict[str, set[str]] = defaultdict(set)
        key_roles: dict[str, set[str]] = defaultdict(set)
        role_evidence: dict[tuple[str, str], set[RoleEvidence]] = defaultdict(set)
        role_fonts: dict[str, set[str]] = defaultdict(set)
        tooltip_keys: set[str] = set()
        dynamic_fonts: dict[str, set[str]] = defaultdict(set)
        dynamic_roles: dict[str, set[str]] = defaultdict(set)

        index_gui_blocks(
            blocks,
            frozenset({"WELCOME_KEY", "WELCOME_HEADER"}),
            key_fonts,
            key_roles,
            role_evidence,
            role_fonts,
            tooltip_keys,
            dynamic_fonts,
            dynamic_roles,
        )

        self.assertEqual({"hoi_18mbs"}, role_fonts[ROLE_FOCUS_DESCRIPTION])
        self.assertEqual({"hoi_20b"}, key_fonts["WELCOME_KEY"])
        self.assertEqual({ROLE_WELCOME_TEXT}, key_roles["WELCOME_KEY"])
        self.assertEqual(
            {ROLE_WELCOME_TITLE},
            key_roles["WELCOME_HEADER"],
        )
        self.assertEqual(
            {"hoi_24header"},
            role_fonts[ROLE_WELCOME_TITLE],
        )
        self.assertEqual({"hoi_18mbs"}, dynamic_fonts["GetDynamicText"])
        self.assertEqual(
            {ROLE_WELCOME_TEXT},
            dynamic_roles["GetWelcomeText"],
        )
        self.assertEqual(
            {ROLE_WELCOME_TITLE},
            dynamic_roles["GetWelcomeTitle"],
        )
        evidence = next(iter(role_evidence[("WELCOME_KEY", ROLE_WELCOME_TEXT)]))
        self.assertEqual(source_path, evidence.source_path)
        self.assertEqual(14, evidence.line)

    def test_tooltip_font_is_shared_with_supported_roles(self) -> None:
        role_fonts: dict[str, set[str]] = defaultdict(set)
        role_fonts[ROLE_TOOLTIP].add("hoi_tooltip")

        merge_tooltip_roles(role_fonts)

        self.assertIn("hoi_tooltip", role_fonts[ROLE_FOCUS_DESCRIPTION])


if __name__ == "__main__":
    unittest.main()
