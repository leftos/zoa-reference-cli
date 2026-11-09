"""Tests for the NCT route core: which rows apply, how they narrow, and reciprocals."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from zoa_ref.nct_routes import (
    BAY_CHOICES,
    VALID_FLOW_SETS,
    applicable_rows,
    class_key,
    conflicts,
    find_reciprocals,
    has_class,
    item_key,
    load_data,
    qualifier_key,
    row_applies,
    rows_for,
    value_key,
)

SFOW = {"SFOW", "SMFS", "RNOS"}
SFOE_SFO10 = {"SFOE", "SFO10", "SMFS", "RNOS"}
SFOW_OAKE = {"SFOW", "OAKE", "SMFS", "RNOS"}
SFOW_SJCE = {"SFOW", "SJCE", "SMFS", "RNOS"}
SFOW_BOTH = {"SFOW", "OAKE", "SJCE", "SMFS", "RNOS"}


def _row(row_id: str, **overrides: Any) -> dict[str, Any]:
    """Build a synthetic SOP exit row carrying every key a real row has."""
    row: dict[str, Any] = {
        "id": row_id,
        "doc": "SOP",
        "page": 1,
        "section": "1-1",
        "table": "Synthetic",
        "direction": "exit",
        "from": "Grove",
        "to": "Toga",
        "from_airports": [],
        "table_flows": [],
        "flows": [],
        "dest_or_route": ["SJC"],
        "route": [],
        "qualifiers": [],
        "aircraft": ["P", "T", "J"],
        "altitude": "5,000",
        "info": "",
        "restrictions": "",
        "source": "SOP §1-1 p1",
    }
    row.update(overrides)
    return row


def _real_row(row_id: str) -> dict[str, Any]:
    return next(row for row in load_data()["rows"] if row["id"] == row_id)


def _ids(rows: list[dict[str, Any]], chosen: set[str]) -> set[str]:
    return {row["id"] for row in rows_for(rows, frozenset(chosen))}


def _assert_real_case(bay: set[str], present: list[str], absent: list[str]) -> None:
    ids = _ids(load_data()["rows"], bay | {"SMFS", "RNOS"})
    assert set(present) <= ids
    assert not set(absent) & ids


def test_sfow_answers_with_west_rows_only() -> None:
    _assert_real_case(
        {"SFOW"},
        ["sop-p91-t0-r2", "sop-p114-t0-r4"],
        ["sop-p91-t0-r5", "sop-p114-t0-r5", "sop-p96-t0-r5"],
    )


def test_sjce_rows_replace_their_sfow_rows() -> None:
    _assert_real_case(
        {"SFOW", "SJCE"},
        ["sop-p91-t0-r5", "sop-p114-t0-r5"],
        ["sop-p91-t0-r2", "sop-p114-t0-r4"],
    )


def test_oake_table_replaces_the_sfow_table() -> None:
    _assert_real_case(
        {"SFOW", "OAKE"},
        ["sop-p96-t0-r5"],
        ["sop-p91-t0-r2", "sop-p91-t0-r5", "sop-p96-t0-r6"],
    )


def test_oake_with_sjce_lets_the_sjce_row_replace_inside_the_oake_table() -> None:
    _assert_real_case(
        {"SFOW", "OAKE", "SJCE"},
        ["sop-p96-t0-r6"],
        ["sop-p96-t0-r5", "sop-p91-t0-r2"],
    )


def test_plain_sfoe_keeps_sfo10_and_sfoe_rows() -> None:
    _assert_real_case({"SFOE"}, ["sop-p98-t0-r0", "sop-p94-t0-r0"], ["sop-p91-t0-r2"])


def test_sfo10_keeps_an_sfoe_row_with_no_counterpart() -> None:
    _assert_real_case(
        {"SFOE", "SFO10"}, ["sop-p98-t0-r0", "sop-p94-t0-r0"], ["sop-p91-t0-r2"]
    )


def test_sfo19_drops_the_sfo10_table() -> None:
    _assert_real_case({"SFOE", "SFO19"}, ["sop-p94-t0-r0"], ["sop-p98-t0-r0"])


def test_row_with_no_flow_condition_applies_under_every_valid_set() -> None:
    row = _row("r")
    assert all(row_applies(row, chosen) for chosen in VALID_FLOW_SETS)


def test_sfo10_row_replaces_its_sfoe_counterpart_only() -> None:
    sfo10 = _row("sfo10", table_flows=["SFO10"], dest_or_route=["HWD"])
    replaced = _row("replaced", table_flows=["SFOE"], dest_or_route=["HWD"])
    kept = _row("kept", table_flows=["SFOE"], dest_or_route=["SJC"])
    assert _ids([sfo10, replaced, kept], SFOE_SFO10) == {"sfo10", "kept"}


def test_sfo10_table_leaves_other_sectors_and_directions_alone() -> None:
    sfo10 = _row("sfo10", table_flows=["SFO10"], dest_or_route=["HWD"])
    other_sector = _row(
        "other-sector",
        **{"from": "Sutro"},
        table_flows=["SFOE"],
        dest_or_route=["HWD"],
    )
    other_direction = _row(
        "other-direction",
        direction="entry",
        table_flows=["SFOE"],
        dest_or_route=["HWD"],
    )
    assert _ids([sfo10, other_sector, other_direction], SFOE_SFO10) == {
        "sfo10",
        "other-sector",
        "other-direction",
    }


def test_oake_exit_table_leaves_the_sectors_sfow_entry_table() -> None:
    oake_exit = _row("oake-exit", table_flows=["OAKE"], dest_or_route=["HWD"])
    sfow_exit = _row("sfow-exit", table_flows=["SFOW"], dest_or_route=["SJC"])
    sfow_entry = _row(
        "sfow-entry",
        **{"from": "Toga"},
        direction="entry",
        to="Grove",
        table_flows=["SFOW"],
    )
    assert _ids([oake_exit, sfow_exit, sfow_entry], SFOW_OAKE) == {
        "oake-exit",
        "sfow-entry",
    }


def test_rows_tagged_with_two_active_flows_both_stay() -> None:
    oake = _row("oake", flows=["OAKE"])
    sjce = _row("sjce", flows=["SJCE"])
    assert _ids([oake, sjce], SFOW_BOTH) == {"oake", "sjce"}


def test_partly_covered_row_stays() -> None:
    sjce = _row("sjce", flows=["SJCE"], dest_or_route=["SJC"])
    sfow = _row("sfow", flows=["SFOW"], dest_or_route=["SJC", "SQL"])
    assert _ids([sjce, sfow], SFOW_SJCE) == {"sjce", "sfow"}


def test_partly_covered_classes_stay() -> None:
    sjce = _row("sjce", flows=["SJCE"], aircraft=["P"])
    sfow = _row("sfow", flows=["SFOW"], aircraft=["P", "J"])
    assert _ids([sjce, sfow], SFOW_SJCE) == {"sjce", "sfow"}


def test_row_with_no_tags_is_not_replaced() -> None:
    sjce = _row("sjce", flows=["SJCE"])
    untagged = _row("untagged")
    assert _ids([sjce, untagged], SFOW_SJCE) == {"sjce", "untagged"}


def test_replacing_row_may_name_a_different_receiver() -> None:
    sjce = _row("sjce", flows=["SJCE"], to="Licke")
    sfow = _row("sfow", flows=["SFOW"], to="Toga")
    assert _ids([sjce, sfow], SFOW_SJCE) == {"sjce"}


def test_valid_flow_sets_are_the_28_allowed_combinations() -> None:
    assert len(VALID_FLOW_SETS) == 28
    assert len(set(VALID_FLOW_SETS)) == 28
    assert not any({"SFOW", "SFOE"} <= chosen for chosen in VALID_FLOW_SETS)
    east = [chosen for chosen in VALID_FLOW_SETS if "SFOE" in chosen]
    assert not any(chosen & {"OAKE", "SJCE"} for chosen in east)


def test_item_key_treats_rwy_as_runway() -> None:
    assert item_key("MCC Rwy 16") == item_key("MCC Runway 16")


def test_item_key_keeps_different_names_apart() -> None:
    assert item_key("Monterey Runway 10") != item_key("MRY Runway 10")


def test_item_key_folds_case_and_whitespace() -> None:
    assert item_key("  Landing   mry ") == item_key("LANDING MRY")


def test_item_key_drops_a_leading_rv() -> None:
    assert item_key("RV MOD") == item_key("MOD")


def test_item_key_drops_a_trailing_dp() -> None:
    assert item_key("BMRNG DP") == item_key("BMRNG")


def test_item_key_keeps_a_different_fix_after_rv_apart() -> None:
    assert item_key("MOD") != item_key("RV ALTAM")


def test_value_key_drops_the_degree_sign() -> None:
    assert value_key("OSI RV 140") == value_key("OSI RV 140°")


def test_value_key_drops_a_final_period() -> None:
    assert value_key("RV through Salty Gate.") == value_key("RV through Salty Gate")


def test_value_key_keeps_different_headings_apart() -> None:
    assert value_key("OSI RV 110°") != value_key("OSI RV 140°")


def test_class_key_drops_parentheses_and_only() -> None:
    assert class_key("(DH8D only)") == class_key("DH8D")


def test_class_key_keeps_different_classes_apart() -> None:
    assert class_key("DH8D") != class_key("J")


def test_class_key_strips_asterisks() -> None:
    assert has_class(_real_row("loa-p18-t0-r9-a"), "J")


def test_item_key_keeps_dp_when_the_rest_is_a_short_identifier() -> None:
    assert item_key("SFO DP") != item_key("SFO")
    assert item_key("GAP DP") != item_key("GAP")


def test_item_key_drops_commas() -> None:
    assert item_key("Northbound, requesting 6,000 or higher") == item_key(
        "Northbound requesting 6000 or higher"
    )


def test_value_key_normalises_spaces_around_a_slash() -> None:
    assert value_key("5,000/ 7,000") == value_key("5,000 / 7,000")
    assert value_key("HOBOA/ TARVR") == value_key("HOBOA/TARVR")


def test_value_key_keeps_different_altitudes_apart() -> None:
    assert value_key("5,000 / 7,000") != value_key("7,000")


def test_value_key_keeps_commas() -> None:
    assert value_key("7,000") != value_key("7000")


def test_qualifier_key_folds_case() -> None:
    assert qualifier_key("HWD Departures Only") == qualifier_key("HWD departures only")


def test_qualifier_key_treats_and_and_ampersand_alike() -> None:
    assert qualifier_key("PAO & SQL Departures Only") == qualifier_key(
        "PAO and SQL Departures Only"
    )


def test_qualifier_key_spells_out_deps() -> None:
    assert qualifier_key("OAK and SFO Deps Only") == qualifier_key(
        "OAK and SFO departures only"
    )


def test_qualifier_key_drops_a_trailing_only() -> None:
    assert qualifier_key("PAO Departures Only") == qualifier_key("PAO Departures")


def test_qualifier_key_keeps_different_limits_apart() -> None:
    assert qualifier_key("HWD only") != qualifier_key("OAK Only")


def test_reciprocal_matches_classes_by_class_key() -> None:
    row = _row("exit", aircraft=["(DH8D only)"])
    match = _row("m", direction="entry", aircraft=["DH8D"])
    assert find_reciprocals(row, [row, match], SFOW) == [match]


def test_blank_class_shares_a_class_with_every_row() -> None:
    blank = _row("blank", aircraft=[])
    entry = _row("entry", direction="entry", aircraft=["J"])
    exit_row = _row("exit", aircraft=["J"])
    blank_entry = _row("blank-entry", direction="entry", aircraft=[])
    assert find_reciprocals(blank, [blank, entry], SFOW) == [entry]
    assert find_reciprocals(exit_row, [exit_row, blank_entry], SFOW) == [blank_entry]


def test_loa_row_has_no_reciprocal() -> None:
    rows = load_data()["rows"]
    loa = next(row for row in rows if row["doc"] == "LOA")
    assert find_reciprocals(loa, rows, SFOW) == []


def test_qualified_row_prefers_the_same_qualifiers_over_a_general_row() -> None:
    row = _row("exit", qualifiers=["HWD Departures Only"])
    same = _row("same", direction="entry", qualifiers=["HWD departures only"])
    other = _row("other", direction="entry", qualifiers=["OAK only"])
    general = _row("general", direction="entry")
    found = find_reciprocals(row, [row, general, other, same], SFOW)
    assert [candidate["id"] for candidate in found] == ["same"]


def test_qualified_row_with_no_match_takes_no_general_row() -> None:
    row = _row("exit", qualifiers=["HWD Departures Only"])
    general = _row("general", direction="entry")
    assert find_reciprocals(row, [row, general], SFOW) == []


def test_unqualified_row_prefers_unqualified_candidates() -> None:
    row = _row("exit")
    qualified = _row("qualified", direction="entry", qualifiers=["HWD only"])
    general = _row("general", direction="entry")
    found = find_reciprocals(row, [row, qualified, general], SFOW)
    assert [candidate["id"] for candidate in found] == ["general"]


def test_unqualified_row_falls_back_to_qualified_candidates() -> None:
    row = _row("exit")
    first = _row("first", direction="entry", qualifiers=["HWD only"])
    second = _row("second", direction="entry", qualifiers=["OAK only"])
    found = find_reciprocals(row, [row, first, second], SFOW)
    assert [candidate["id"] for candidate in found] == ["first", "second"]


def test_reciprocals_narrow_under_the_chosen_flows() -> None:
    rows = load_data()["rows"]
    found = find_reciprocals(_real_row("sop-p131-t0-r2"), rows, SFOW)
    ids = {candidate["id"] for candidate in found}
    assert "sop-p126-t0-r4" in ids
    assert "sop-p128-t0-r6" not in ids


def test_rows_of_different_flows_are_never_reciprocal() -> None:
    rows = load_data()["rows"]
    morgan, valley = _real_row("sop-p22-t0-r0"), _real_row("sop-p84-t1-r10")
    for chosen in VALID_FLOW_SETS:
        assert valley["id"] not in {
            r["id"] for r in find_reciprocals(morgan, rows, chosen)
        }
        assert morgan["id"] not in {
            r["id"] for r in find_reciprocals(valley, rows, chosen)
        }


def test_reciprocal_needs_a_shared_class_and_item() -> None:
    row = _row("exit", aircraft=["J"], dest_or_route=["SJC"])
    other_class = _row("c", direction="entry", aircraft=["P"], dest_or_route=["SJC"])
    other_item = _row("i", direction="entry", aircraft=["J"], dest_or_route=["SQL"])
    match = _row("m", direction="entry", aircraft=["J"], dest_or_route=["sjc"])
    found = find_reciprocals(row, [row, other_class, other_item, match], SFOW)
    assert [candidate["id"] for candidate in found] == ["m"]


def test_reciprocal_rejects_a_different_from() -> None:
    row = _row("exit")
    other = _row("o", direction="entry", **{"from": "Sutro"})
    assert find_reciprocals(row, [row, other], SFOW) == []


def test_reciprocal_rejects_a_different_to() -> None:
    row = _row("exit")
    other = _row("o", direction="entry", to="Licke")
    assert find_reciprocals(row, [row, other], SFOW) == []


def test_general_row_cannot_replace_a_row_limited_to_some_departures() -> None:
    limited = ["sop-p96-t0-r9", "sop-p96-t0-r10"]
    _assert_real_case({"SFOW", "OAKE"}, [*limited, "sop-p33-t1-r2"], [])
    _assert_real_case({"SFOW", "OAKE", "SJCE"}, limited, [])


def test_row_naming_the_parent_does_not_replace_on_real_data() -> None:
    _assert_real_case({"SFOW", "OAKE"}, ["sop-p82-t1-r10"], [])
    _assert_real_case({"SFOW", "OAKE", "SJCE"}, ["sop-p82-t1-r10"], [])


def test_row_naming_the_parent_gets_no_replacing_power() -> None:
    both = _row("both", flows=["SFOW", "SJCE"])
    sfow = _row("sfow", flows=["SFOW"])
    assert _ids([both, sfow], SFOW_SJCE) == {"both", "sfow"}


def test_row_limited_differently_is_not_replaced() -> None:
    sjce = _row("sjce", flows=["SJCE"], qualifiers=["HWD only"])
    sfow = _row("sfow", flows=["SFOW"])
    assert _ids([sjce, sfow], SFOW_SJCE) == {"sjce", "sfow"}


def test_row_with_the_same_limit_is_replaced() -> None:
    sjce = _row("sjce", flows=["SJCE"], qualifiers=["HWD only"])
    sfow = _row("sfow", flows=["SFOW"], qualifiers=["hwd"])
    assert _ids([sjce, sfow], SFOW_SJCE) == {"sjce"}


def test_smf_only_row_is_not_replaced() -> None:
    sjce = _row("sjce", flows=["SJCE"])
    smf = _row("smf", table_flows=["SMFS"])
    assert _ids([sjce, smf], SFOW_SJCE) == {"sjce", "smf"}


def test_from_airports_are_part_of_the_row_rule_origin() -> None:
    sjce = _row("sjce", flows=["SJCE"], from_airports=["LVK"])
    sfow = _row("sfow", flows=["SFOW"], from_airports=["HWD"])
    assert _ids([sjce, sfow], SFOW_SJCE) == {"sjce", "sfow"}


def test_applicable_rows_narrows_the_whole_file() -> None:
    chosen = {"SFOW", "OAKE", "SMFS", "RNOS"}
    ids = {row["id"] for row in applicable_rows(chosen)}
    assert "sop-p96-t0-r5" in ids
    assert "sop-p91-t0-r7" not in ids


def test_table_displaces_even_when_none_of_its_rows_apply() -> None:
    oake = _row("oake", table_flows=["OAKE"], flows=["SJCE"], dest_or_route=["HWD"])
    sfow = _row("sfow", table_flows=["SFOW"], dest_or_route=["SJC"])
    assert _ids([oake, sfow], SFOW_OAKE) == set()


def test_valid_flow_sets_never_hold_both_runway_flows() -> None:
    assert not any({"SFO10", "SFO19"} <= chosen for chosen in VALID_FLOW_SETS)


def test_valid_flow_sets_hold_one_smf_and_one_rno_flow() -> None:
    for chosen in VALID_FLOW_SETS:
        assert len(chosen & {"SMFS", "SMFN"}) == 1
        assert len(chosen & {"RNOS", "RNON"}) == 1


def test_bay_choices_agree_with_flow_parents() -> None:
    parents = load_data()["flow_parents"]
    named = {flow for bay in BAY_CHOICES for flow in bay}
    assert named == set(parents) | set(parents.values())
    for bay in BAY_CHOICES:
        assert all(parents[flow] in bay for flow in bay if flow in parents)


def test_conflicts_name_a_rows_mismatch() -> None:
    rows = load_data()["rows"]
    chosen = {"SFOE", "SMFS", "RNOS"}
    found = conflicts(_real_row("sop-p22-t0-r24"), rows, chosen).mismatches
    named = [(item.entry_row["id"], item.field, item.items) for item in found]
    assert named == [("sop-p89-t1-r5", "altitude", ["LVK"])]


def test_conflicts_name_uncovered_items_and_classes() -> None:
    rows = load_data()["rows"]
    chosen = {"SFOE", "SMFS", "RNOS"}
    uncovered = conflicts(_real_row("sop-p55-t0-r2"), rows, chosen).uncovered
    assert ("T263", "P") in uncovered


def test_conflicts_are_empty_for_a_row_that_does_not_answer() -> None:
    rows = load_data()["rows"]
    chosen = {"SFOW", "SMFS", "RNOS"}
    assert conflicts(_real_row("sop-p55-t0-r2"), rows, chosen) == ([], [])


def test_conflicts_are_empty_for_an_loa_row() -> None:
    rows = load_data()["rows"]
    loa = next(row for row in rows if row["doc"] == "LOA")
    assert conflicts(loa, rows, SFOW) == ([], [])


def test_missing_data_file_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("zoa_ref.nct_routes.DATA_PATH", tmp_path / "absent.json")
    load_data.cache_clear()
    try:
        with pytest.raises(FileNotFoundError):
            load_data()
    finally:
        monkeypatch.undo()
        load_data.cache_clear()
