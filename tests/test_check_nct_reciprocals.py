"""Tests for the dev-only NCT reciprocal checker, over the committed route data."""

from __future__ import annotations

import importlib.util
import sys
from collections import defaultdict
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from zoa_ref.nct_routes import VALID_FLOW_SETS, conflicts, load_data

REPO_ROOT = Path(__file__).resolve().parents[1]
ERRATA = REPO_ROOT / "docs" / "nct-errata.md"
KNOWN = REPO_ROOT / "tools" / "nct_errata_known.md"


def _load_checker() -> ModuleType:
    """Load ``tools/check_nct_reciprocals.py`` by path, since ``tools/`` is not a package."""
    spec = importlib.util.spec_from_file_location(
        "check_nct_reciprocals", REPO_ROOT / "tools" / "check_nct_reciprocals.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


checker = _load_checker()


@pytest.fixture(scope="module")
def findings() -> dict[str, list[dict[str, Any]]]:
    return checker.find_findings(load_data())


def _mismatch(
    findings: dict[str, list[dict[str, Any]]], exit_id: str, entry_id: str, field: str
) -> dict[str, Any] | None:
    for finding in findings["mismatches"]:
        if (finding["exit_id"], finding["entry_id"], finding["field"]) == (
            exit_id,
            entry_id,
            field,
        ):
            return finding
    return None


def _two_receiver(
    findings: dict[str, list[dict[str, Any]]], exit_id: str, entry_id: str
) -> dict[str, Any] | None:
    for finding in findings["two_receivers"]:
        if (finding["exit_id"], finding["entry_id"]) == (exit_id, entry_id):
            return finding
    return None


def _row(row_id: str, direction: str, **overrides: Any) -> dict[str, Any]:
    """Build a synthetic Grove to Toga row carrying every key a real row has."""
    row: dict[str, Any] = {
        "id": row_id,
        "doc": "SOP",
        "page": 1,
        "section": "1-1",
        "table": "Synthetic",
        "direction": direction,
        "from": "Grove",
        "to": "Toga",
        "from_airports": [],
        "table_flows": [],
        "flows": [],
        "dest_or_route": ["SJC"],
        "route": [],
        "qualifiers": [],
        "aircraft": ["J"],
        "altitude": "5,000",
        "info": "",
        "restrictions": "",
        "source": "SOP §1-1 p1",
    }
    row.update(overrides)
    return row


def _render(findings: dict[str, Any]) -> str:
    return checker.render(findings, "", load_data()["source"])


def test_morgan_sunol_lvk_sfoe_altitude_mismatch(findings: dict[str, Any]) -> None:
    finding = _mismatch(findings, "sop-p22-t0-r24", "sop-p89-t1-r5", "altitude")
    assert finding is not None
    assert finding["exit_value"] == "10,000"
    assert finding["entry_value"] == "12,000 or lower filed"
    assert finding["flows"] == "SFOE, SFOE+SFO10, SFOE+SFO19"


def test_morgan_sunol_lvk_sfow_agrees(findings: dict[str, Any]) -> None:
    assert _mismatch(findings, "sop-p22-t0-r18", "sop-p86-t1-r14", "altitude") is None


def test_grove_toga_mabry_info_mismatch(findings: dict[str, Any]) -> None:
    finding = _mismatch(findings, "sop-p91-t0-r1", "sop-p33-t1-r2", "info")
    assert finding is not None
    assert finding["exit_value"] == "RV at least 3 miles east of MABRY"
    assert finding["entry_value"] == "RV at least 3 miles west of MABRY"


def test_grove_richmond_v6_info_mismatch(findings: dict[str, Any]) -> None:
    finding = _mismatch(findings, "sop-p91-t0-r7", "sop-p105-t1-r2", "info")
    assert finding is not None
    assert finding["items"] == ["V6"]
    assert finding["exit_value"] == "RV vicinity of Danville Tower"
    assert finding["entry_value"] == "RV to join V6 over COLLI"


def test_toga_sjc_departures_have_no_reciprocal_under_oake(
    findings: dict[str, Any],
) -> None:
    found = [
        item for item in findings["no_reciprocal"] if item["id"] == "sop-p33-t0-r5"
    ]
    assert any("SFOW+OAKE" in item["flows"].split(", ") for item in found)
    assert _mismatch(findings, "sop-p33-t0-r5", "sop-p96-t1-r6", "altitude") is None


@pytest.mark.parametrize("row_id", ["sop-p92-t0-r10", "sop-p96-t1-r4"])
def test_limited_toga_rows_have_no_reciprocal(
    findings: dict[str, Any], row_id: str
) -> None:
    assert row_id in {item["id"] for item in findings["no_reciprocal"]}


def test_candidate_with_another_qualifier_does_not_settle_a_mismatch() -> None:
    rows = [
        _row("e", "exit", altitude="5,000"),
        _row("n1", "entry", altitude="5,000", qualifiers=["HWD only"]),
        _row("n2", "entry", altitude="7,000", qualifiers=["OAK only"]),
    ]
    found = checker.find_findings({"rows": rows})["mismatches"]
    assert [item["entry_id"] for item in found] == ["n2"]


def test_candidate_with_another_qualifier_does_not_cover_an_item() -> None:
    rows = [
        _row("e", "exit"),
        _row("n", "entry", qualifiers=["HWD only"]),
    ]
    found = checker.find_findings({"rows": rows})["no_reciprocal"]
    assert {item["id"] for item in found} == {"e", "n"}


def test_restrictions_mismatch_is_reported() -> None:
    rows = [
        _row("e", "exit", restrictions="Climb to 5,000"),
        _row("n", "entry", restrictions="Climb to 7,000"),
    ]
    found = checker.find_findings({"rows": rows})["mismatches"]
    assert [item["field"] for item in found] == ["restrictions"]


def test_blank_altitude_against_a_printed_one_is_reported() -> None:
    rows = [_row("e", "exit", altitude=""), _row("n", "entry", altitude="5,000")]
    found = checker.find_findings({"rows": rows})["mismatches"]
    assert [item["field"] for item in found] == ["altitude"]
    assert "(blank) (p1)" in _render(
        {"mismatches": found, "no_reciprocal": [], "two_receivers": []}
    )


def test_cell_separator_is_escaped() -> None:
    rows = [_row("e", "exit", info="A|B"), _row("n", "entry", info="C")]
    assert "A\\|B (p1)" in _render(checker.find_findings({"rows": rows}))


def test_qualifiers_column_keeps_rows_apart() -> None:
    rows = [
        _row("x1", "exit", qualifiers=["HWD only"]),
        _row("x2", "exit", qualifiers=["OAK only"]),
    ]
    text = _render(checker.find_findings({"rows": rows}))
    assert "| Grove | Toga | exit | SJC | J | HWD only |" in text
    assert "| Grove | Toga | exit | SJC | J | OAK only |" in text


def test_no_reciprocal_section_explains_gaps() -> None:
    line = (
        "Only one side prints a row with these limits. Tables list only what overrides "
        "en route at any altitude, so a line can be deliberate; a reader checks it "
        "against the other sector's table."
    )
    assert f"## No reciprocal row\n\n{line}\n\n| From |" in ERRATA.read_text("utf-8")


def _mismatch_keys(row: dict[str, Any], chosen: frozenset[str]) -> set[tuple[str, ...]]:
    found = conflicts(row, load_data()["rows"], chosen).mismatches
    return {(m.exit_row["id"], m.entry_row["id"], m.field) for m in found}


def test_conflicts_names_every_tool_finding() -> None:
    rows = load_data()["rows"]
    by_id = {row["id"]: row for row in rows}
    absent = []
    for chosen in VALID_FLOW_SETS:
        mismatches: dict[Any, Any] = {}
        missing: dict[Any, Any] = defaultdict(set)
        two_receivers: dict[Any, Any] = {}
        checker._record(rows, chosen, mismatches, missing, two_receivers)
        for row_id in {row_id for key in mismatches for row_id in key[:2]}:
            named = {key for key in mismatches if row_id in key[:2]}
            absent += sorted(named - _mismatch_keys(by_id[row_id], chosen))
        for row_id in {key[0] for key in missing}:
            named_pairs = {key[1:] for key in missing if key[0] == row_id}
            found = conflicts(by_id[row_id], rows, chosen).uncovered
            absent += sorted(named_pairs - set(found))
    assert absent == []


def test_sop_p136_row_names_its_info_mismatch() -> None:
    row = next(r for r in load_data()["rows"] if r["id"] == "sop-p136-t0-r0")
    keys = _mismatch_keys(row, frozenset({"SFOW", "SMFS", "RNOS"}))
    assert ("sop-p136-t0-r0", "sop-p135-t1-r0", "info") in keys


def test_candidate_for_another_item_does_not_settle_a_mismatch() -> None:
    rows = [
        _row("e", "exit", altitude="10,000", dest_or_route=["LVK", "OAK"]),
        _row("lvk", "entry", altitude="12,000", dest_or_route=["LVK"]),
        _row("oak", "entry", altitude="10,000", dest_or_route=["OAK"]),
    ]
    found = checker.find_findings({"rows": rows})["mismatches"]
    assert [(item["exit_id"], item["entry_id"]) for item in found] == [("e", "lvk")]


@pytest.mark.parametrize("row_id", ["sop-p55-t0-r2", "sop-p23-t0-r5"])
def test_cedar_t263_rows_have_no_reciprocal(
    findings: dict[str, Any], row_id: str
) -> None:
    found = [item for item in findings["no_reciprocal"] if item["id"] == row_id]
    assert found
    assert {"T263", "PXN", "AVE"} <= {name for item in found for name in item["items"]}


def test_two_receivers_finds_exactly_the_three_real_pairs(
    findings: dict[str, Any],
) -> None:
    found = {(item["exit_id"], item["entry_id"]) for item in findings["two_receivers"]}
    assert found == {
        ("sop-p55-t0-r2", "sop-p23-t0-r5"),
        ("sop-p96-t0-r11", "sop-p111-t1-r1"),
        ("sop-p96-t0-r12", "sop-p111-t1-r1"),
    }


def test_two_receivers_grove_valley_against_richmond(
    findings: dict[str, Any],
) -> None:
    finding = _two_receiver(findings, "sop-p96-t0-r11", "sop-p111-t1-r1")
    assert finding is not None
    assert finding["from"] == "Grove"
    assert finding["exit_to"] == "Valley"
    assert finding["entry_to"] == "Richmond"
    assert set(finding["items"]) == {"SAC", "V334"}
    assert set(finding["classes"]) == {"P"}
    assert finding["exit_value"] == "5,000"
    assert finding["entry_value"] == "10,000"
    assert finding["exit_page"] == 96
    assert finding["entry_page"] == 111
    assert finding["flows"] == "SFOW+OAKE, SFOW+OAKE+SJCE"


def test_two_receivers_cedar_t263(findings: dict[str, Any]) -> None:
    finding = _two_receiver(findings, "sop-p55-t0-r2", "sop-p23-t0-r5")
    assert finding is not None
    assert finding["exit_to"] == "Valley"
    assert finding["entry_to"] == "Morgan"
    assert set(finding["items"]) == {"T263", "PXN", "AVE"}
    assert finding["flows"] == "SFOE, SFOE+SFO10, SFOE+SFO19"


def test_two_receivers_skips_a_covered_split() -> None:
    rows = [
        _row("e1", "exit", to="Toga", dest_or_route=["X"]),
        _row("n1", "entry", to="Toga", dest_or_route=["X"]),
        _row("e2", "exit", to="Licke", dest_or_route=["X"]),
        _row("n2", "entry", to="Licke", dest_or_route=["X"]),
    ]
    assert checker.find_findings({"rows": rows})["two_receivers"] == []


def test_two_receivers_skips_different_qualifiers() -> None:
    rows = [
        _row("e", "exit", to="Toga", qualifiers=["HWD only"], dest_or_route=["X"]),
        _row("n", "entry", to="Licke", qualifiers=["OAK only"], dest_or_route=["X"]),
    ]
    assert checker.find_findings({"rows": rows})["two_receivers"] == []


def test_two_receivers_skips_the_same_receiver() -> None:
    rows = [
        _row("e", "exit", to="Toga", aircraft=["J"], dest_or_route=["X"]),
        _row("n", "entry", to="Toga", aircraft=["J"], dest_or_route=["X"]),
    ]
    assert checker.find_findings({"rows": rows})["two_receivers"] == []


def test_two_receivers_skips_no_shared_class() -> None:
    rows = [
        _row("e", "exit", to="Toga", aircraft=["J"], dest_or_route=["X"]),
        _row("n", "entry", to="Licke", aircraft=["P"], dest_or_route=["X"]),
    ]
    assert checker.find_findings({"rows": rows})["two_receivers"] == []


def test_two_receivers_finds_a_synthetic_pair() -> None:
    rows = [
        _row("e", "exit", to="Toga", aircraft=["J"], dest_or_route=["X"]),
        _row("n", "entry", to="Licke", aircraft=["J"], dest_or_route=["X"]),
    ]
    found = checker.find_findings({"rows": rows})["two_receivers"]
    assert len(found) == 1
    assert found[0]["exit_to"] == "Toga"
    assert found[0]["entry_to"] == "Licke"
    assert found[0]["items"] == ["X"]


def test_two_receivers_aggregates_across_flow_sets() -> None:
    rows = [
        _row("e", "exit", to="Toga", aircraft=["J"], dest_or_route=["A", "B"]),
        _row("n", "entry", to="Licke", aircraft=["J"], dest_or_route=["A", "B"]),
        _row(
            "t",
            "entry",
            to="Toga",
            aircraft=["J"],
            dest_or_route=["A"],
            flows=["SFOW"],
        ),
    ]
    found = checker.find_findings({"rows": rows})["two_receivers"]
    assert len(found) == 1
    assert (found[0]["exit_id"], found[0]["entry_id"]) == ("e", "n")
    assert found[0]["items"] == ["B", "A"]
    assert found[0]["flows"] == (
        "SFOW, SFOW+OAKE, SFOW+SJCE, SFOW+OAKE+SJCE, SFOE, SFOE+SFO10, SFOE+SFO19"
    )


def test_licke_seca_monterey_sfoe_altitude_mismatch(findings: dict[str, Any]) -> None:
    finding = _mismatch(findings, "sop-p27-t0-r2", "sop-p20-t1-r7", "altitude")
    assert finding is not None
    assert finding["exit_value"] == "5,000"
    assert finding["entry_value"] == "7,000"


def test_licke_seca_monterey_sfow_agrees(findings: dict[str, Any]) -> None:
    assert _mismatch(findings, "sop-p25-t0-r1", "sop-p20-t1-r7", "altitude") is None


def test_landing_mry_altitude_mismatch(findings: dict[str, Any]) -> None:
    finding = _mismatch(findings, "sop-p46-t0-r5", "sop-p20-t1-r0", "altitude")
    assert finding is not None
    assert finding["exit_value"] == "5,000 / 7,000"
    assert finding["entry_value"] == "7,000"


def test_no_loa_row_in_findings(findings: dict[str, Any]) -> None:
    loa_ids = {row["id"] for row in load_data()["rows"] if row["doc"] == "LOA"}
    named = {item["id"] for item in findings["no_reciprocal"]}
    for finding in findings["mismatches"]:
        named |= {finding["exit_id"], finding["entry_id"]}
    assert loa_ids
    assert not loa_ids & named


def test_committed_errata_matches_render(findings: dict[str, Any]) -> None:
    known = KNOWN.read_text(encoding="utf-8")
    rendered = checker.render(findings, known, load_data()["source"])
    assert ERRATA.read_bytes().decode("utf-8") == rendered


def test_found_by_hand_is_the_known_file() -> None:
    text = ERRATA.read_bytes().decode("utf-8")
    assert text.split("## Found by hand\n\n", 1)[1] == KNOWN.read_bytes().decode()


def test_errata_prose_lines_stay_short() -> None:
    text = ERRATA.read_bytes().decode("utf-8")
    prose = [line for line in text.splitlines() if not line.startswith("|")]
    assert all(len(line) < 500 for line in prose)


def test_blank_info_against_printed_info_is_no_finding() -> None:
    rows = [_row("e", "exit", info="RV RHV"), _row("n", "entry", info="")]
    assert checker.find_findings({"rows": rows})["mismatches"] == []


def test_row_with_one_agreeing_candidate_is_no_finding() -> None:
    rows = [
        _row("e", "exit", altitude="5,000"),
        _row("n1", "entry", altitude="5,000"),
        _row("n2", "entry", altitude="7,000"),
    ]
    assert checker.find_findings({"rows": rows})["mismatches"] == []


def test_uncovered_class_is_reported_with_only_what_is_missing() -> None:
    rows = [
        _row("e", "exit", aircraft=["P", "J"], dest_or_route=["SJC", "SQL"]),
        _row("n", "entry", aircraft=["J"], dest_or_route=["SJC", "SQL"]),
    ]
    found = checker.find_findings({"rows": rows})["no_reciprocal"]
    assert [(item["id"], item["items"], item["classes"]) for item in found] == [
        ("e", ["SJC", "SQL"], ["P"])
    ]


def test_blank_class_row_with_no_reciprocal_lists_blank() -> None:
    rows = [_row("e", "exit", aircraft=[])]
    findings = checker.find_findings({"rows": rows})
    assert [item["id"] for item in findings["no_reciprocal"]] == ["e"]
    assert "| Grove | Toga | exit | SJC | (blank) |" in _render(findings)


def test_blank_class_row_is_covered_by_any_class() -> None:
    rows = [_row("e", "exit", aircraft=[]), _row("n", "entry", aircraft=["J"])]
    assert checker.find_findings({"rows": rows})["no_reciprocal"] == []


def test_identical_table_lines_collapse() -> None:
    rows = [
        _row("e", "exit", altitude="5,000"),
        _row("n1", "entry", altitude="7,000"),
        _row("n2", "entry", altitude="7,000"),
        _row("x1", "exit", dest_or_route=["SQL"], to="Licke"),
        _row("x2", "exit", dest_or_route=["SQL"], to="Licke"),
    ]
    findings = checker.find_findings({"rows": rows})
    assert len(findings["mismatches"]) == 2
    assert len(findings["no_reciprocal"]) == 2
    table = [line for line in _render(findings).splitlines() if line.startswith("| G")]
    assert len(table) == 2


def test_main_writes_the_rendered_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "errata.md"
    assert checker.main(["--out", str(out)]) == 0
    assert out.read_bytes().decode("utf-8") == ERRATA.read_bytes().decode("utf-8")
    assert len(capsys.readouterr().out.splitlines()) == 1
