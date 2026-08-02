from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from hoi4_l10n_checker.font_context import (
    build_font_context,
    find_hoi4_install,
    find_mod_root,
    is_context_root,
    mod_display_name,
)


class FontContextTests(unittest.TestCase):
    def test_nearest_mod_root_is_selected_for_multiple_copies(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dev = root / "eaw_dev"
            workshop = root / "workshop" / "123"
            for mod_root in (dev, workshop):
                (mod_root / "localisation").mkdir(parents=True)
                (mod_root / "descriptor.mod").write_text(
                    f'name="{mod_root.name}"\n',
                    encoding="utf-8",
                )
            selected = workshop / "localisation" / "sample.yml"
            selected.write_text("", encoding="utf-8")

            self.assertEqual(workshop.resolve(), find_mod_root(selected))
            self.assertTrue(is_context_root(dev))
            self.assertEqual("eaw_dev", mod_display_name(dev))

    def test_gui_index_collects_fonts_and_applies_mod_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            game = root / "game"
            mod = root / "mod"
            (game / "interface").mkdir(parents=True)
            (game / "localisation").mkdir()
            (game / "hoi4.exe").write_bytes(b"test")
            (mod / "interface").mkdir(parents=True)
            (mod / "localisation").mkdir()
            (mod / "descriptor.mod").write_text(
                'name="Context Test"\n',
                encoding="utf-8",
            )
            (game / "interface" / "shared.gui").write_text(
                (
                    "guiTypes = {\n"
                    "  instantTextBoxType = {\n"
                    '    font = "BaseFont"\n'
                    '    text = "OVERRIDDEN_KEY"\n'
                    "  }\n"
                    "}\n"
                ),
                encoding="utf-8",
            )
            (game / "interface" / "base_only.gui").write_text(
                (
                    "guiTypes = {\n"
                    "  buttonType = {\n"
                    '    buttonFont = "BaseButton"\n'
                    '    buttonText = "BASE_KEY"\n'
                    "  }\n"
                    "}\n"
                ),
                encoding="utf-8",
            )
            (mod / "interface" / "shared.gui").write_text(
                (
                    "guiTypes = {\n"
                    "  instantTextBoxType = {\n"
                    '    text = "OVERRIDDEN_KEY"\n'
                    '    font = "ModFont"\n'
                    "  }\n"
                    "  instantTextBoxType = {\n"
                    '    font = "OtherModFont"\n'
                    '    text = "OVERRIDDEN_KEY" # another real use\n'
                    "  }\n"
                    "  instantTextBoxType = {\n"
                    '    font = "IgnoredLiteralFont"\n'
                    '    text = "NOT_A_LOCALISATION_KEY"\n'
                    "  }\n"
                    "}\n"
                ),
                encoding="utf-8",
            )

            context = build_font_context(
                mod,
                {"OVERRIDDEN_KEY", "BASE_KEY"},
                game_root=game,
            )

            self.assertEqual(
                frozenset({"ModFont", "OtherModFont"}),
                context.fonts_for_key("OVERRIDDEN_KEY"),
            )
            self.assertEqual(
                frozenset({"BaseButton"}),
                context.fonts_for_key("BASE_KEY"),
            )
            self.assertEqual(frozenset(), context.fonts_for_key("UNKNOWN"))
            self.assertEqual(2, context.gui_files_checked)

    def test_dynamic_keys_are_mapped_from_script_type_to_gui_fonts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            mod = Path(temporary) / "mod"
            interface = mod / "interface"
            interface.mkdir(parents=True)
            (mod / "localisation").mkdir()
            (mod / "descriptor.mod").write_text(
                'name="Semantic Context Test"\n',
                encoding="utf-8",
            )
            (interface / "semantic.gui").write_text(
                (
                    "guiTypes = {\n"
                    "  textBoxType = {\n"
                    '    name = "ToolTip"\n'
                    '    font = "TooltipFont"\n'
                    "  }\n"
                    "  containerWindowType = {\n"
                    '    name = "national_focus_item"\n'
                    "    instantTextBoxType = {\n"
                    '      name = "name"\n'
                    '      font = "FocusNodeFont"\n'
                    "    }\n"
                    "  }\n"
                    "  containerWindowType = {\n"
                    '    name = "national_focus_detail_view"\n'
                    "    instantTextBoxType = {\n"
                    '      name = "name"\n'
                    '      font = "FocusHeaderFont"\n'
                    "    }\n"
                    "    instantTextBoxType = {\n"
                    '      name = "desc"\n'
                    '      font = "FocusBodyFont"\n'
                    "    }\n"
                    "  }\n"
                    "  containerWindowType = {\n"
                    '    name = "political_selectable_idea_entry_grid"\n'
                    "    instantTextBoxType = {\n"
                    '      name = "name"\n'
                    '      font = "IdeaListFont"\n'
                    "    }\n"
                    "  }\n"
                    "  containerWindowType = {\n"
                    '    name = "EventWindow"\n'
                    "    instantTextBoxType = {\n"
                    '      name = "Title"\n'
                    '      font = "EventTitleFont"\n'
                    "    }\n"
                    "    instantTextBoxType = {\n"
                    '      name = "Description"\n'
                    '      font = "EventBodyFont"\n'
                    "    }\n"
                    "  }\n"
                    "  containerWindowType = {\n"
                    '    name = "event_option_entry"\n'
                    "    instantTextBoxType = {\n"
                    '      name = "Name"\n'
                    '      font = "EventOptionFont"\n'
                    "    }\n"
                    "  }\n"
                    "  containerWindowType = {\n"
                    '    name = "decision_item"\n'
                    "    instantTextBoxType = {\n"
                    '      name = "name_text"\n'
                    '      font = "DecisionFont"\n'
                    "    }\n"
                    "  }\n"
                    "  instantTextBoxType = {\n"
                    '    name = "tech_info_title"\n'
                    '    font = "TechTitleFont"\n'
                    "  }\n"
                    "  instantTextBoxType = {\n"
                    '    name = "tech_info_description"\n'
                    '    font = "TechBodyFont"\n'
                    "  }\n"
                    "  containerWindowType = {\n"
                    '    name = "stat_equipment_entry"\n'
                    "    instantTextBoxType = {\n"
                    '      name = "equipment_name"\n'
                    '      font = "LandEquipmentFont"\n'
                    "    }\n"
                    "  }\n"
                    "  containerWindowType = {\n"
                    '    name = "stat_equipment_entry_large"\n'
                    "    instantTextBoxType = {\n"
                    '      name = "equipment_name"\n'
                    '      font = "AirEquipmentFont"\n'
                    "    }\n"
                    "  }\n"
                    "  iconType = {\n"
                    '    pdx_tooltip = "DIRECT_TOOLTIP_KEY"\n'
                    "  }\n"
                    "}\n"
                ),
                encoding="utf-8",
            )

            source_files = {
                "common/ideas/test.txt": (
                    "ideas = {\n"
                    "  country = { TEST_SPIRIT = { } }\n"
                    "  political_advisor = { TEST_ADVISOR = { } }\n"
                    "}\n"
                ),
                "common/national_focus/test.txt": (
                    "focus_tree = { focus = { id = TEST_FOCUS } }\n"
                ),
                "common/decisions/test.txt": (
                    "TEST_CATEGORY = { TEST_DECISION = { } }\n"
                ),
                "common/technologies/test.txt": (
                    "technologies = { test_technology = { } }\n"
                ),
                "common/units/equipment/test.txt": (
                    "equipments = {\n"
                    "  land_equipment_1 = { archetype = land_equipment }\n"
                    "  fighter_equipment_1 = { archetype = small_plane_airframe }\n"
                    "}\n"
                ),
                "events/test.txt": (
                    "country_event = {\n"
                    "  id = test.1\n"
                    "  title = test.1.t\n"
                    "  desc = { text = test.1.d }\n"
                    "  option = { name = test.1.a }\n"
                    "}\n"
                ),
            }
            for relative_path, text in source_files.items():
                path = mod.joinpath(*relative_path.split("/"))
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")

            keys = {
                "DIRECT_TOOLTIP_KEY",
                "TAG_fighter_equipment_1",
                "TAG_land_equipment_1",
                "TAG_land_equipment_1_short",
                "TEST_ADVISOR",
                "TEST_ADVISOR_desc",
                "TEST_CATEGORY",
                "TEST_DECISION",
                "TEST_DECISION_desc",
                "TEST_FOCUS",
                "TEST_FOCUS_desc",
                "TEST_SPIRIT",
                "TEST_SPIRIT_lar_desc",
                "TAG_test_technology",
                "TAG_test_technology_desc",
                "test.1.a",
                "test.1.d",
                "test.1.t",
            }
            context = build_font_context(mod, keys)

            self.assertEqual(
                frozenset({"TooltipFont"}),
                context.fonts_for_key("TEST_SPIRIT"),
            )
            self.assertEqual(
                frozenset({"TooltipFont"}),
                context.fonts_for_key("TEST_SPIRIT_lar_desc"),
            )
            self.assertEqual(
                frozenset({"IdeaListFont", "TooltipFont"}),
                context.fonts_for_key("TEST_ADVISOR"),
            )
            self.assertEqual(
                frozenset(
                    {
                        "FocusBodyFont",
                        "TooltipFont",
                    }
                ),
                context.fonts_for_key("TEST_FOCUS_desc"),
            )
            self.assertEqual(
                frozenset(
                    {
                        "FocusHeaderFont",
                        "FocusNodeFont",
                        "TooltipFont",
                    }
                ),
                context.fonts_for_key("TEST_FOCUS"),
            )
            self.assertEqual(
                frozenset({"EventTitleFont"}),
                context.fonts_for_key("test.1.t"),
            )
            self.assertEqual(
                frozenset({"EventBodyFont"}),
                context.fonts_for_key("test.1.d"),
            )
            self.assertEqual(
                frozenset({"EventOptionFont"}),
                context.fonts_for_key("test.1.a"),
            )
            self.assertEqual(
                frozenset({"DecisionFont", "TooltipFont"}),
                context.fonts_for_key("TEST_DECISION"),
            )
            self.assertEqual(
                frozenset({"TechTitleFont", "TooltipFont"}),
                context.fonts_for_key("TAG_test_technology"),
            )
            self.assertEqual(
                frozenset({"TechBodyFont", "TooltipFont"}),
                context.fonts_for_key("TAG_test_technology_desc"),
            )
            self.assertEqual(
                frozenset({"LandEquipmentFont", "TooltipFont"}),
                context.fonts_for_key("TAG_land_equipment_1_short"),
            )
            self.assertEqual(
                frozenset({"AirEquipmentFont", "TooltipFont"}),
                context.fonts_for_key("TAG_fighter_equipment_1"),
            )
            self.assertEqual(
                frozenset({"TooltipFont"}),
                context.fonts_for_key("DIRECT_TOOLTIP_KEY"),
            )
            self.assertEqual(6, context.script_files_checked)
            self.assertGreaterEqual(context.semantic_resolved_key_count, 15)

    def test_engine_conventions_and_scripted_localisation_are_mapped(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            mod = Path(temporary) / "mod"
            interface = mod / "interface"
            interface.mkdir(parents=True)
            (mod / "localisation").mkdir()
            (mod / "descriptor.mod").write_text(
                'name="Extended Context Test"\n',
                encoding="utf-8",
            )
            (interface / "dynamic.gui").write_text(
                (
                    "guiTypes = {\n"
                    "  containerWindowType = {\n"
                    '    name = "battleplantools_window"\n'
                    "    editBoxType = {\n"
                    '      name = "operation_name"\n'
                    '      font = "OperationFont"\n'
                    "    }\n"
                    "  }\n"
                    "  containerWindowType = {\n"
                    '    name = "victory_point_mapicon"\n'
                    "    instantTextBoxType = {\n"
                    '      name = "text"\n'
                    '      font = "VictoryPointFont"\n'
                    "    }\n"
                    "  }\n"
                    "  instantTextBoxType = {\n"
                    '    name = "party_name"\n'
                    '    font = "PartyFont"\n'
                    "  }\n"
                    "  instantTextBoxType = {\n"
                    '    name = "country_name"\n'
                    '    font = "CountryFont"\n'
                    "  }\n"
                    "  instantTextBoxType = {\n"
                    '    name = "state_name"\n'
                    '    font = "StateFont"\n'
                    "  }\n"
                    "  instantTextBoxType = {\n"
                    '    name = "cost_and_timer_text"\n'
                    '    font = "DecisionCostFont"\n'
                    "  }\n"
                    "  containerWindowType = {\n"
                    '    name = "leader_list"\n'
                    "    instantTextBoxType = {\n"
                    '      name = "name"\n'
                    '      font = "CharacterFont"\n'
                    "    }\n"
                    "  }\n"
                    "  instantTextBoxType = {\n"
                    '    font = "DynamicFont"\n'
                    '    text = "PARENT_KEY"\n'
                    "  }\n"
                    "}\n"
                ),
                encoding="utf-8",
            )

            source_files = {
                "common/names/test.txt": (
                    "names = { o_TestCodename }\n"
                ),
                "common/countries/cosmetic.txt": (
                    "COSMETIC_TAG = { color = { 1 2 3 } }\n"
                ),
                "common/decisions/test.txt": (
                    "CATEGORY = {\n"
                    "  DECISION = { custom_cost_text = COST_KEY }\n"
                    "}\n"
                ),
                "common/scripted_localisation/test.txt": (
                    "defined_text = {\n"
                    "  name = GetDynamicText\n"
                    "  text = { localization_key = DYNAMIC_KEY }\n"
                    "}\n"
                ),
                "events/test.txt": (
                    "country_event = {\n"
                    "  id = test.1\n"
                    "  immediate = {\n"
                    "    set_province_name = { name = PROVINCE_KEY }\n"
                    "    set_state_name = { name = STATE_KEY }\n"
                    "    generate_character = { name = CHARACTER_KEY }\n"
                    "    set_party_name = { long_name = PARTY_LONG_KEY }\n"
                    "  }\n"
                    "}\n"
                ),
            }
            for relative_path, text in source_files.items():
                path = mod.joinpath(*relative_path.split("/"))
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")

            keys = {
                "CHARACTER_KEY",
                "COSMETIC_TAG_neutrality",
                "COST_KEY",
                "COST_KEY_blocked",
                "DYNAMIC_KEY",
                "PARENT_KEY",
                "PARTY_LONG_KEY",
                "PROVINCE_KEY",
                "STATE_KEY",
                "VICTORY_POINTS_123",
                "o_TestCodename",
            }
            context = build_font_context(
                mod,
                keys,
                localisation_values={
                    "PARENT_KEY": ("[Root.GetDynamicText]",),
                },
            )

            self.assertEqual(
                frozenset({"OperationFont"}),
                context.fonts_for_key("o_TestCodename"),
            )
            self.assertEqual(
                frozenset({"VictoryPointFont"}),
                context.fonts_for_key("VICTORY_POINTS_123"),
            )
            self.assertEqual(
                frozenset({"VictoryPointFont"}),
                context.fonts_for_key("PROVINCE_KEY"),
            )
            self.assertEqual(
                frozenset({"PartyFont"}),
                context.fonts_for_key("PARTY_LONG_KEY"),
            )
            self.assertEqual(
                frozenset({"DecisionCostFont"}),
                context.fonts_for_key("COST_KEY_blocked"),
            )
            self.assertEqual(
                frozenset({"CharacterFont"}),
                context.fonts_for_key("CHARACTER_KEY"),
            )
            self.assertEqual(
                frozenset({"DynamicFont"}),
                context.fonts_for_key("DYNAMIC_KEY"),
            )
            self.assertEqual(
                frozenset({"CountryFont", "tahoma_60"}),
                context.fonts_for_key("COSMETIC_TAG_neutrality"),
            )
            self.assertEqual(
                frozenset({"StateFont", "tahoma_60"}),
                context.fonts_for_key("STATE_KEY"),
            )

    def test_configured_game_install_is_preferred(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            game = Path(temporary) / "Hearts of Iron IV"
            (game / "interface").mkdir(parents=True)
            (game / "localisation").mkdir()
            (game / "hoi4.exe").write_bytes(b"test")

            self.assertEqual(
                game.resolve(),
                find_hoi4_install(str(game)),
            )


if __name__ == "__main__":
    unittest.main()
