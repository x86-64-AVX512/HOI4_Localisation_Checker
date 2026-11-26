from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from hoi4_l10n_checker.localisation_compare import LocalisationComparator
from hoi4_l10n_checker.long_text import (
    AssemblySpec,
    TextBranch,
    apply_plan,
    collect_entries,
    decode_value,
    encode_value,
    generated_values,
    load_specs,
    prepare_plan,
    split_text,
)
from hoi4_l10n_checker.scripted_assemblies import analyse_assemblies
from hoi4_l10n_checker.text_layout_checker import TextLayoutChecker, TextLayoutOptions


class LongTextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "common/scripted_localisation").mkdir(parents=True)
        (self.root / "events").mkdir()
        self.ru = self.root / "localisation/russian"
        self.en = self.root / "localisation/english"
        self.ru.mkdir(parents=True)
        self.en.mkdir()
        self.source = self.ru / "events_l_russian.yml"
        self.source.write_bytes(
            b"\xef\xbb\xbf"
            + 'l_russian:\n EVENT_DESC:0 "Исходное описание." # комментарий\n'
            .encode("utf-8")
        )
        (self.en / "events_l_english.yml").write_bytes(
            b'\xef\xbb\xbfl_english:\n EVENT_DESC:0 "Original description."\n'
        )
        (self.root / "events/test.txt").write_text(
            "country_event = { id = test.1 desc = EVENT_DESC }",
            encoding="utf-8",
        )
        self.spec = AssemblySpec(
            "EVENT_DESC", "localisation/russian/events_l_russian.yml", "TestLong",
            "event", (TextBranch("", ("Первая часть.\n\n", "Вторая часть.")),),
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_split_preserves_unicode_whitespace_and_atomic_insertions(self) -> None:
        text = ("Первый абзац.\n\nВторой: [Root.GetName] $OTHER$ £icon£ §Yцвет§! " * 60)
        parts = split_text(text, 220)
        self.assertEqual(text, "".join(parts))
        self.assertTrue(all(len(part.encode("utf-8")) <= 220 for part in parts))
        self.assertEqual(
            text.count("[Root.GetName]"),
            sum(part.count("[Root.GetName]") for part in parts),
        )
        self.assertEqual(text, decode_value(encode_value(text)))
        with self.assertRaises(ValueError):
            split_text("[Root.Get" + "A" * 100 + "]", 20)

    def test_plan_updates_existing_key_and_backups_originals(self) -> None:
        before = self.source.read_bytes()
        plan = prepare_plan(self.root, self.spec)
        self.assertEqual(before, self.source.read_bytes())
        backup = apply_plan(plan)
        self.assertEqual(
            before,
            (backup / (self.spec.source + ".bak")).read_bytes(),
        )
        self.assertEqual(1, len(load_specs(self.root)))
        parsed = collect_entries(self.root)
        main = [entry for entry in parsed if entry.key == "EVENT_DESC"
                and entry.language == "l_russian"]
        self.assertEqual(1, len(main))
        self.assertIn("[Root.GetTestLongPart01]", main[0].raw_value)
        self.assertIn("# комментарий", self.source.read_text(encoding="utf-8-sig"))
        self.assertTrue(self.source.read_bytes().startswith(b"\xef\xbb\xbf"))
        index = analyse_assemblies(self.root, parsed)
        self.assertEqual([], index.diagnostics)
        self.assertEqual(
            encode_value("".join(self.spec.branches[0].parts)),
            index.variants[("l_russian", "EVENT_DESC")][0].raw_value,
        )

    def test_rejects_changed_file_after_preview(self) -> None:
        plan = prepare_plan(self.root, self.spec)
        self.source.write_bytes(self.source.read_bytes() + b"\n# another edit")
        with self.assertRaisesRegex(ValueError, "после предпросмотра"):
            apply_plan(plan)

    def test_rolls_back_after_write_failure(self) -> None:
        from hoi4_l10n_checker import long_text
        plan = prepare_plan(self.root, self.spec)
        before = self.source.read_bytes()
        real_write = long_text._atomic_write
        count = 0

        def write(path, data):
            nonlocal count
            if path in [change.path for change in plan.changes]:
                count += 1
                if count == 2:
                    raise OSError("simulated")
            real_write(path, data)

        with patch.object(long_text, "_atomic_write", side_effect=write):
            with self.assertRaises(OSError):
                apply_plan(plan)
        self.assertEqual(before, self.source.read_bytes())
        self.assertFalse(plan.changes[1].path.exists())

    def test_cannot_generate_focus_or_escape_mod_root(self) -> None:
        for spec in (
            replace(self.spec, key="FOCUS_DESC"),
            replace(self.spec, source="../outside.yml"),
        ):
            with self.assertRaises(ValueError):
                prepare_plan(self.root, spec)

    def test_cannot_overwrite_foreign_key_or_getter(self) -> None:
        (self.root / "common/scripted_localisation/conflict.txt").write_text(
            "defined_text = { name = GetTestLongPart01 text = { "
            "trigger = { always = yes } localization_key = OTHER } }",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "конфликтует"):
            prepare_plan(self.root, self.spec)

    def test_known_dollar_expansion_and_cycles_block_generation(self) -> None:
        self.source.write_bytes(
            self.source.read_bytes()
            + (' HUGE:0 "' + "Я" * 4000 + '"\n'
               ' INDIRECT:0 "$EVENT_DESC$"\n').encode()
        )
        for part in ("$HUGE$", "$INDIRECT$"):
            spec = replace(self.spec, branches=(TextBranch("", (part,)),))
            with self.assertRaises(ValueError):
                prepare_plan(self.root, spec)

    def test_managed_assembly_can_be_edited_without_duplicate_keys(self) -> None:
        apply_plan(prepare_plan(self.root, self.spec))
        changed = replace(
            self.spec, branches=(TextBranch("", ("Новое.", " Продолжение.", " Конец.")),)
        )
        apply_plan(prepare_plan(self.root, changed))
        index = analyse_assemblies(self.root, collect_entries(self.root))
        self.assertEqual([], index.diagnostics)
        self.assertEqual(
            "Новое. Продолжение. Конец.",
            decode_value(index.variants[("l_russian", "EVENT_DESC")][0].raw_value),
        )
        self.assertEqual(1, len(load_specs(self.root)))

    def test_getter_cycle_through_dollar_reference_is_reported(self) -> None:
        plan = prepare_plan(self.root, self.spec)
        apply_plan(plan)
        loc = plan.changes[1].path
        loc.write_bytes(
            loc.read_bytes().replace(
                encode_value("Первая часть.\n\n").encode(),
                b"$EVENT_DESC$",
            )
        )
        index = analyse_assemblies(self.root, collect_entries(self.root))
        self.assertTrue(index.diagnostics)
        self.assertNotIn(("l_russian", "EVENT_DESC"), index.variants)

    def test_comparison_omits_only_verified_russian_helpers(self) -> None:
        apply_plan(prepare_plan(self.root, self.spec))
        regular = LocalisationComparator().scan(self.en, self.ru)
        self.assertEqual(2, regular.missing_english)
        contextual = LocalisationComparator().scan(
            self.en, self.ru, mod_root=self.root,
        )
        self.assertEqual(0, contextual.missing_english)
        self.assertEqual(2, contextual.assembly_helpers_omitted)
        self.assertEqual(0, contextual.parse_errors)
        # Recognition also works when the authoring manifest is unavailable.
        (self.root / ".localisation-checker/long_texts.json").unlink()
        manual = LocalisationComparator().scan(self.en, self.ru, mod_root=self.root)
        self.assertEqual(2, manual.assembly_helpers_omitted)

    def test_english_calls_require_english_parts(self) -> None:
        apply_plan(prepare_plan(self.root, self.spec))
        calls, _, _ = generated_values(self.spec)
        (self.en / "events_l_english.yml").write_bytes(
            b"\xef\xbb\xbf" + f'l_english:\n EVENT_DESC:0 "{calls}"\n'.encode()
        )
        result = LocalisationComparator().scan(self.en, self.ru, mod_root=self.root)
        self.assertEqual(0, result.assembly_helpers_omitted)
        self.assertGreater(result.parse_errors, 0)
        self.assertEqual(2, result.missing_english)

    def test_broken_script_never_silently_hides_helpers(self) -> None:
        plan = prepare_plan(self.root, self.spec)
        apply_plan(plan)
        script = plan.changes[2].path
        script.write_text(script.read_text(encoding="utf-8")[:-2], encoding="utf-8")
        result = LocalisationComparator().scan(self.en, self.ru, mod_root=self.root)
        self.assertEqual(0, result.assembly_helpers_omitted)
        self.assertGreater(result.parse_errors, 0)

    def test_length_counts_assembled_event_instead_of_individual_parts(self) -> None:
        apply_plan(prepare_plan(self.root, self.spec))
        result = TextLayoutChecker().scan(
            self.ru, self.root,
            TextLayoutOptions(focus_enabled=False, events_enabled=True,
                              event_limit=20, welcome_enabled=False),
        )
        self.assertEqual(1, result.events_checked)
        warnings = [item for item in result.diagnostics if item.code == "TEXT_TOO_LONG"]
        self.assertEqual(["EVENT_DESC"], [item.key for item in warnings])
        self.assertGreater(warnings[0].measured_length, 20)

    def test_welcome_handles_shorter_branches_and_single_fallback(self) -> None:
        self.source.write_bytes(
            b"\xef\xbb\xbf" + 'l_russian:\n EAW_WS_TAB_1_TXT:0 '
            '"[Root.GetCountryIntro]"\n'.encode()
        )
        spec = replace(
            self.spec, kind="welcome", key="EAW_WS_TAB_1_TXT",
            branches=(
                TextBranch("EQS", ("Эквестрия первая.", " Вторая.")),
                TextBranch("CRY", ("Кристальная.",)),
            ),
        )
        apply_plan(prepare_plan(self.root, spec))
        index = analyse_assemblies(self.root, collect_entries(self.root))
        self.assertEqual([], index.diagnostics)
        variants = {
            item.label: decode_value(item.raw_value)
            for item in index.variants[("l_russian", spec.key)]
        }
        self.assertEqual("Кристальная.", variants["CRY"])
        self.assertEqual("Эквестрия первая. Вторая.", variants["EQS"])
        (self.root / "interface").mkdir()
        (self.root / "interface/eaw_welcome_screen.gui").write_text(
            'guiTypes = { containerWindowType = { name = "eaw_ws_window" '
            'instantTextboxType = { name = "tab_1_text" font = "hoi_16mbs" '
            'text = EAW_WS_TAB_1_TXT } } }', encoding="utf-8",
        )
        layout = TextLayoutChecker().scan(
            self.ru, self.root,
            TextLayoutOptions(
                focus_enabled=False, events_enabled=False,
                welcome_enabled=True, welcome_limit=5,
            ),
        )
        warnings = [item for item in layout.diagnostics if item.code == "TEXT_TOO_LONG"]
        self.assertEqual(2, layout.welcome_checked)
        self.assertEqual(
            {"Вступительный экран (CRY)", "Вступительный экран (EQS)"},
            {item.text_kind for item in warnings},
        )

    def test_focus_only_checks_do_not_enter_assembly_system(self) -> None:
        with patch(
            "hoi4_l10n_checker.text_layout_checker.analyse_assemblies",
            side_effect=AssertionError("focus entered assembly system"),
        ):
            result = TextLayoutChecker().scan(
                self.ru, self.root,
                TextLayoutOptions(events_enabled=False, welcome_enabled=False),
            )
        self.assertEqual([], result.diagnostics)


if __name__ == "__main__":
    unittest.main()
