from __future__ import annotations

import unittest
from pathlib import Path

from hoi4_l10n_checker.paradox_script import (
    ancestor_names,
    block_name,
    font_names,
    has_ancestor_kind,
    localisation_calls,
    parse_blocks,
    property_line,
    token_value,
    tokenize_script,
)


class ParadoxScriptTests(unittest.TestCase):
    def test_parses_nested_blocks_properties_and_source_lines(self) -> None:
        source_path = Path("interface/example.gui")
        text = (
            "container = {\n"
            '    name = "ROOT"\n'
            "    # ignored comment\n"
            "    child = {\n"
            '        name = "CHILD"\n'
            '        font = "hoi_16mbs"\n'
            '        buttonFont = "hoi_18mbs"\n'
            '        text = "TEST_KEY"\n'
            "    }\n"
            "}\n"
        )

        root_block, child = parse_blocks(text, source_path)

        self.assertEqual("container", root_block.kind)
        self.assertEqual("ROOT", block_name(root_block))
        self.assertIs(root_block, child.parent)
        self.assertEqual(source_path, child.source_path)
        self.assertEqual(4, child.line)
        self.assertEqual(8, property_line(child, "text", "TEST_KEY"))
        self.assertEqual({"hoi_16mbs", "hoi_18mbs"}, font_names(child))
        self.assertEqual(["root"], list(ancestor_names(child)))
        self.assertTrue(has_ancestor_kind(child, frozenset({"container"})))

    def test_tokenizer_and_localisation_calls_ignore_non_calls(self) -> None:
        tokens = tokenize_script(
            'text = "A \\"quoted\\" value" # ignored\nfont = hoi_16mbs'
        )

        self.assertNotIn("#", tokens)
        self.assertEqual('A "quoted" value', token_value(tokens[2]))
        self.assertEqual(
            {"GetFocusName", "GetTooltip", "GetWithPipe"},
            localisation_calls(
                "[Root.GetFocusName] [GetTooltip()] "
                "[Root.GetWithPipe|Y] [?Skip] [@Skip]"
            ),
        )


if __name__ == "__main__":
    unittest.main()
