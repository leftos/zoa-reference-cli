"""Tests for the NCT handoff lookup and the 'xfer' command, on the packaged data."""

from __future__ import annotations

import os
import re
import subprocess
import sys

import pytest
from click.testing import CliRunner, Result

from zoa_ref.nct_routes import (
    FlowError,
    Mismatch,
    XferAnswer,
    XferQuery,
    applicable_rows,
    item_key,
    load_data,
    lookup,
    parse_flows,
)

SFOW = frozenset({"SFOW", "SMFS", "RNOS"})
SJCE = SFOW | {"SJCE"}
SFOE = frozenset({"SFOE", "SMFS", "RNOS"})

NO_ROW = "No specific instructions: hand off en route at any altitude."
SPELLING_NOTE = "anywhere in the SOP or LOA: check the spelling."
SFOW_FLOWS_LINE = "Flows: SFOW SMFS RNOS"
CEDAR_LINE = "Cedar, 14,000, RV ALWYS/MOD, SOP §3-4 p22"


@pytest.fixture()
def run(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """Invoke the command line without a browser download or the group's terminal escapes."""
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))
    monkeypatch.setattr("zoa_ref.cli.set_console_title", lambda _title: None)
    monkeypatch.setattr("zoa_ref.cli.reset_terminal_state", lambda: None)
    from zoa_ref.cli import main

    def invoke(*args: str) -> Result:
        return CliRunner().invoke(main, ["xfer", *args])

    return invoke


def _answer(
    sector: str,
    target: str,
    aircraft: str = "",
    chosen: frozenset[str] = SFOW,
    entry: bool = False,
) -> XferAnswer:
    return lookup(XferQuery(sector, target, aircraft, entry), chosen)


def _ids(
    sector: str,
    target: str,
    aircraft: str = "",
    chosen: frozenset[str] = SFOW,
    entry: bool = False,
) -> list[str]:
    answer = _answer(sector, target, aircraft, chosen, entry)
    return [row["id"] for row in answer.rows]


def _real_row(row_id: str) -> dict:
    return next(row for row in load_data()["rows"] if row["id"] == row_id)


def _line_ending(stdout: str, ending: str) -> str:
    """Return the one stdout line that ends with a text."""
    found = [line for line in stdout.splitlines() if line.endswith(ending)]
    assert len(found) == 1, stdout
    return found[0]


def test_morgan_sfo_j_answers_the_cedar_row(run):
    assert _ids("morgan", "SFO", "J") == ["sop-p22-t0-r32"]
    result = run("morgan", "SFO", "J", "--flow", "SFOW")
    assert result.exit_code == 0
    assert result.stdout == f"{CEDAR_LINE}\n{SFOW_FLOWS_LINE}\n"


def test_morgan_sfo_without_a_class_opens_lines_with_classes(run):
    ids = _ids("morgan", "SFO")
    assert ids.index("sop-p22-t0-r5") < ids.index("sop-p22-t0-r32")
    lines = run("morgan", "SFO", "--flow", "SFOW").stdout.splitlines()
    assert "P T  Laguna, 12,000 or lower filed, RV OSI, SOP §3-4 p22" in lines
    assert f"T J  {CEDAR_LINE}" in lines


def test_sector_target_and_class_fold_case_and_drop_the_k():
    assert _ids("MORGAN", "ksfo", "j") == ["sop-p22-t0-r32"]


def test_woodside_sfo_answers_the_catch_all():
    assert _ids("woodside", "SFO") == ["sop-p71-t0-r5"]


def test_woodside_sql_answers_its_row_and_not_the_catch_all():
    ids = _ids("woodside", "SQL")
    assert "sop-p71-t0-r0" in ids
    assert "sop-p71-t0-r5" not in ids


def test_grove_sjc_under_sjce_drops_the_complex_row_and_names_a_longer_item(run):
    assert _ids("grove", "SJC", "J", SJCE) == ["sop-p91-t0-r4", "sop-p91-t0-r6"]
    result = run("grove", "SJC", "J", "--flow", "SJCE")
    assert result.stdout == (
        "Licke (SJCE), 2,000, RV to SJC 12R Localizer, HWD Departures Only, SOP §5-7 p91\n"
        "Licke (SJCE), VFR SJC Arrivals, At or above 2,500, RV Tesla Plant, SOP §5-7 p91\n"
        "Flows: SFOW SJCE SMFS RNOS\n"
    )


def test_grove_pao_under_sjce_keeps_the_complex_row():
    ids = _ids("grove", "PAO", "J", SJCE)
    assert "sop-p91-t0-r1" in ids
    assert "sop-p91-t0-r4" not in ids


def test_grove_complex_under_sjce_prints_both_rows():
    ids = _ids("grove", "San Jose CX", chosen=SJCE)
    assert "sop-p91-t0-r1" in ids
    assert "sop-p91-t0-r4" in ids


def test_grove_sjc_under_sfow_warns_of_the_entry_table(run):
    assert "sop-p91-t0-r1" in _ids("grove", "SJC", "J")
    entry_info = _real_row("sop-p33-t1-r2")["info"]
    expected = (
        "Toga, 6,000, RV at least 3 miles east of MABRY, HWD Departures Only, SOP §5-7 p91\n"
        "  Warning: the entry table disagrees on info:\n"
        "  Grove exit, SOP p91: RV at least 3 miles east of MABRY\n"
        f"  Toga entry, SOP p33: {entry_info}\n"
        "Toga, VFR SJC Arrivals, At or above 3,500, RV RHV, SOP §5-7 p91\n"
        f"{SFOW_FLOWS_LINE}\n"
    )
    assert run("grove", "SJC", "J", "--flow", "SFOW").stdout == expected


def test_warning_needs_the_asked_class():
    from zoa_ref.nct_routes import _warns_for_class

    def mismatch(classes: list[str]) -> Mismatch:
        return Mismatch({}, {}, "info", ["SFO"], classes, True)

    assert _warns_for_class(mismatch(["T"]), "T")
    assert _warns_for_class(mismatch(["(DH8D only)"]), "dh8d")
    assert _warns_for_class(mismatch(["T"]), "")
    assert _warns_for_class(mismatch([]), "J")
    assert not _warns_for_class(mismatch(["T"]), "J")


def test_complex_query_names_no_item(run):
    assert "sop-p27-t0-r1" in _ids("licke", "Napa", chosen=SFOE)
    result = run("licke", "Napa", "--flow", "SFOE")
    assert result.exit_code == 0
    assert "Napa CX" not in result.stdout


def test_piped_stdout_keeps_the_arrows(tmp_path):
    env = {
        **os.environ,
        "PYTHONIOENCODING": "cp1252",
        "PLAYWRIGHT_BROWSERS_PATH": str(tmp_path),
    }
    command = [
        sys.executable,
        "-c",
        "from zoa_ref.cli import main; main()",
        *("xfer", "zoa", "SFO", "--flow", "SFOW"),
    ]
    try:
        result = subprocess.run(
            command, env=env, capture_output=True, timeout=120, check=False
        )
    except subprocess.TimeoutExpired:
        pytest.fail("the command hung")
    assert result.returncode == 0, result.stderr
    assert "↓" in result.stdout.decode("utf-8")


def _catch_all_ids(
    sender: str, receiver: str, direction: str, chosen: frozenset[str]
) -> set[str]:
    return {
        row["id"]
        for row in applicable_rows(chosen)
        if row["direction"] == direction
        and (row["from"], row["to"]) == (sender, receiver)
        and any(
            item_key(item) == "all" or item_key(item).startswith("all others")
            for item in row["dest_or_route"]
        )
    }


def test_entry_catch_all_agrees_with_exit(run):
    disagreements = []
    for chosen in (SFOW, SFOW | {"OAKE"}):
        for sender, receiver in (
            ("Woodside", "Sutro"),
            ("Richmond", "Sunol"),
            ("Richmond", "Cedar"),
        ):
            exit_rows = _catch_all_ids(sender, receiver, "exit", chosen)
            entry_rows = _catch_all_ids(sender, receiver, "entry", chosen)
            assert exit_rows
            assert entry_rows
            for target in (
                "RNO",
                "SQL",
                "SMF",
                "MRY",
                "SFO",
                "XYZ",
                "SCK",
                "AVE",
                "OAK",
            ):
                for aircraft in ("", "P", "J"):
                    by_exit = exit_rows & set(_ids(sender, target, aircraft, chosen))
                    by_entry = entry_rows & set(
                        _ids(receiver, target, aircraft, chosen, entry=True)
                    )
                    if bool(by_exit) != bool(by_entry):
                        disagreements.append(
                            (sorted(chosen), sender, receiver, target, aircraft)
                        )
    assert disagreements == []
    sunol = run("sunol", "RNO", "P", "--entry", "--flow", "SFOW").stdout
    assert sunol == f"{NO_ROW}\n{SFOW_FLOWS_LINE}\n"
    sutro = run("sutro", "SMF", "--entry", "--flow", "SFOW").stdout.splitlines()
    assert any(
        re.fullmatch(
            r"P T J +Woodside, 5,000, RV 280° at least 3 miles south of SFO, SOP §6-6 p114",
            line,
        )
        for line in sutro
    )


def test_loa_row_is_never_a_catch_all():
    assert "loa-p17-t1-r3" not in _ids("zoa", "RNO", chosen=SFOE, entry=True)


def test_all_row_answers(run):
    assert "sop-p54-t1-r0" in _ids("cedar", "XYZ", entry=True)
    ids = _ids("richmond", "XYZ")
    assert {"sop-p105-t0-r8", "sop-p105-t0-r9"} <= set(ids)
    lines = run("richmond", "XYZ", "--flow", "SFOW").stdout.splitlines()
    assert (
        "P T J  Sunol, 11,000 or lower filed, RV 120° / requested altitude 12,000 or lower, "
        "SOP §6-3 p105" in lines
    )
    assert "P T J  Cedar, All, 13,000-FL190, RV CEDES, SOP §6-3 p105" in lines


def test_catch_all_answers_for_uncovered_classes(run):
    woodside = run("woodside", "SCK", "--flow", "SFOW").stdout.splitlines()
    assert woodside[0].startswith("P T  Toga, 3,000, ")
    assert re.match(r"J +Sutro, 5,000, ", woodside[1])
    richmond = run("richmond", "AVE", "--flow", "SFOW").stdout.splitlines()
    assert any(re.match(r"J +Sunol, ", line) for line in richmond)
    assert not any(re.match(r"P T J +Sunol, ", line) for line in richmond)
    assert "sop-p71-t0-r5" in _ids("woodside", "SCK", "J")
    assert "sop-p71-t0-r5" not in _ids("woodside", "SCK", "P")


def test_multi_word_target(run):
    ids = _ids("woodside", "VFR Bay Tours")
    assert "sop-p71-t0-r4" in ids
    assert "sop-p71-t0-r5" not in ids
    result = run("woodside", "VFR Bay Tours", "--flow", "SFOW")
    assert SPELLING_NOTE not in result.stderr
    assert "sop-p91-t0-r3" in _ids("grove", "VFR SJC Arrivals")
    grove = run("grove", "VFR SJC Arrivals", "--flow", "SFOW").stdout
    assert "Toga, At or above 3,500, RV RHV, SOP §5-7 p91" in grove


def test_dotted_tokens():
    assert "loa-p12-t0-r15" in _ids("zoa", "BRIXX", chosen=SFOE)
    assert "loa-p22-t0-r8" in _ids("zoa", "FMG")
    assert "loa-p14-t0-r0" in _ids("cedar", "BFL")
    assert "loa-p14-t0-r5" in _ids("morgan", "BSR")


def test_airport_finds_a_complex_name_without_cx(run):
    assert "sop-p27-t0-r3" in _ids("licke", "MRY", chosen=SFOE)
    stdout = run("licke", "MRY", "--flow", "SFOE").stdout
    assert "Seca (SFOE), Monterey Runway 10, 7,000" in stdout


def test_warning_when_matched_by_qualifier(run):
    stdout = run("grove", "HWD", "J", "--flow", "SFOW").stdout
    assert "  Warning: the entry table disagrees on info:\n" in stdout


def test_row_matched_by_qualifier_or_airport_names_its_destinations(run):
    morgan = run("morgan", "OAK", "J", "--flow", "SFOE").stdout.splitlines()
    assert "Sunol (SFOE), EMZOH, Descend Via, OAK Only, SOP §3-4 p22" in morgan
    assert (
        "Sunol (SFOE), PXN STAR, 10,000, Depart KARNN RV 320°, OAK Only, SOP §3-4 p22"
        in morgan
    )
    airport = run("zoa", "SFO", "--entry", "--flow", "SFOW").stdout.splitlines()
    assert any(
        "SFO to Area South (Sectors 10 & 11), SSTIK or WESLA or SEGUL or GAP DP,"
        in line
        for line in airport
    )
    grove = run("grove", "HWD", "J", "--flow", "SFOW").stdout.splitlines()
    assert (
        "Toga, San Jose CX, 6,000, RV at least 3 miles east of MABRY, "
        "HWD Departures Only, SOP §5-7 p91" in grove
    )


def test_empty_flow_warns(run):
    for empty in ("", ",", " , "):
        result = run("morgan", "SFO", "J", "--flow", empty)
        assert "Flow not set: assuming SFOW, SMFS, RNOS." in result.stderr
        assert result.stdout.splitlines()[-1] == SFOW_FLOWS_LINE


def test_excluding_is_not_match_text():
    assert "sop-p71-t0-r3" not in _ids("woodside", "Bay")
    assert "sop-p25-t0-r6" in _ids("licke", "VFR")
    assert "sop-p71-t0-r3" in _ids("woodside", "VFR")
    assert "sop-p114-t1-r2" in _ids("sutro", "VFR", entry=True)


def test_multi_word_target_folds_runway():
    spelled = _answer("elkhorn", "MCC Runway 16")
    short = _answer("elkhorn", "MCC Rwy 16")
    assert [row["id"] for row in spelled.rows] == [row["id"] for row in short.rows]
    assert any(row["source"] == "SOP §7-2 p126" for row in spelled.rows)
    assert "sop-p27-t0-r3" in _ids("licke", "Monterey Rwy 10", chosen=SFOE)


def test_complex_does_not_reach_its_own_airport_filed_rows():
    assert "loa-p13-t1-r6" not in _ids("silver", "San Jose CX")
    oakland = _answer("silver", "Oakland", "J", SFOE)
    assert all(row["from"] for row in oakland.rows)


def test_complex_query_finds_a_name_without_cx(run):
    spelled = _ids("licke", "Monterey CX", chosen=SFOE)
    assert spelled == _ids("licke", "Monterey", chosen=SFOE)
    assert "sop-p27-t0-r3" in spelled
    for target in ("Monterey", "Monterey CX"):
        stdout = run("licke", target, "--flow", "SFOE").stdout
        assert "Seca (SFOE), Monterey Runway 10, 7,000" in stdout
    assert "Napa CX" not in run("licke", "Napa", "--flow", "SFOE").stdout


def test_warning_dropped_for_an_item_the_disagreement_skips(run):
    assert "Warning:" not in run("grove", "SAC", "--flow", "OAKE").stdout
    assert "Warning:" in run("grove", "LIN", "--flow", "OAKE").stdout


def test_interactive_dispatch_reaches_xfer(capsys: pytest.CaptureFixture[str]):
    from zoa_ref.interactive import INTERACTIVE_COMMANDS

    handler, length, needs_context = INTERACTIVE_COMMANDS["xfer "]
    assert not needs_context
    handler("xfer morgan SFO J -f SFOW"[length:])
    assert capsys.readouterr().out == f"{CEDAR_LINE}\n{SFOW_FLOWS_LINE}\n"


def test_interactive_entry_flag(capsys: pytest.CaptureFixture[str]):
    from zoa_ref.interactive import _handle_xfer_interactive

    _handle_xfer_interactive("cedar SFO -e -f SFOW")
    lines = capsys.readouterr().out.splitlines()
    assert any(line.startswith("T J  Morgan, 14,000") for line in lines)


def test_warning_under_an_entry_row(run):
    stdout = run("toga", "SJC", "J", "--entry", "--flow", "SFOW").stdout
    assert "the exit table disagrees on info" in stdout


def test_warning_prints_blank(capsys: pytest.CaptureFixture[str]):
    from zoa_ref.display import _display_xfer_mismatch

    exit_row = {**_real_row("sop-p91-t0-r1"), "info": ""}
    entry_row = _real_row("sop-p33-t1-r2")
    mismatch = Mismatch(exit_row, entry_row, "info", ["San Jose CX"], ["J"], True)
    _display_xfer_mismatch(exit_row, mismatch)
    assert "  Grove exit, SOP p91: (blank)\n" in capsys.readouterr().out


def test_complex_row_kept_when_classes_not_covered():
    from zoa_ref.nct_routes import (
        _MATCH_DIRECT,
        _MATCH_THROUGH_COMPLEX,
        _narrow_to_airport,
        _resolve_target,
    )

    direct = {**_real_row("sop-p91-t0-r4"), "aircraft": ["J"]}
    complex_row = {**_real_row("sop-p91-t0-r1"), "aircraft": ["P", "J"]}
    kinds = {direct["id"]: _MATCH_DIRECT, complex_row["id"]: _MATCH_THROUGH_COMPLEX}
    target = _resolve_target("SJC")
    kept = _narrow_to_airport([direct, complex_row], kinds, target, SJCE)
    assert kept == [direct, complex_row]
    covering = {**direct, "aircraft": ["P", "J"]}
    assert _narrow_to_airport([covering, complex_row], kinds, target, SJCE) == [
        covering
    ]


def test_sector_lookup_shows_airport_filed_loa_rows(run):
    result = run("sutro", "SSTIK")
    assert result.stdout == (
        "J T  SFO to Area South (Sectors 10 & 11), ↑ FL190 or lower filed altitude, "
        "RNAV DP or direct last fix in approach airspace, LOA Table 1-2 p13\n"
        "J T  SFO to Pac South (Sector 14), ↑ FL190, "
        "RNAV DP or direct last fix in approach airspace ZOA control, LOA Table 1-6 p16\n"
        f"{SFOW_FLOWS_LINE}\n"
    )


def test_named_row_keeps_airport_filed_rows_out():
    ids = _ids("richmond", "AVE")
    assert not {"loa-p13-t1-r5", "loa-p13-t1-r6", "loa-p14-t0-r1"} & set(ids)


def test_own_airport_does_not_reach_a_sector_lookup():
    assert "loa-p13-t1-r6" not in _ids("silver", "SJC", "J")


def test_airport_filed_row_when_no_named_row_for_the_class(monkeypatch):
    sector_row = {
        **_real_row("sop-p71-t0-r0"),
        "id": "sector",
        "dest_or_route": ["ZZFIX"],
        "aircraft": ["J"],
    }
    filed_row = {
        **_real_row("loa-p13-t1-r0"),
        "id": "filed",
        "dest_or_route": ["ZZFIX"],
        "aircraft": ["P", "J"],
    }
    monkeypatch.setattr(
        "zoa_ref.nct_routes.applicable_rows", lambda _chosen: [sector_row, filed_row]
    )
    assert _ids("woodside", "ZZFIX", "P") == ["filed"]
    assert _ids("woodside", "ZZFIX", "J") == ["sector"]


def test_airport_alone_does_not_reach_a_sector_lookup():
    assert "loa-p13-t1-r0" not in _ids("silver", "SFO")


def test_entry_skips_airport_filed_rows():
    assert "loa-p13-t1-r0" not in _ids("sutro", "SSTIK", entry=True)


def test_airport_filed_row_beside_a_catch_all():
    ids = _ids("woodside", "SSTIK")
    assert {"loa-p13-t1-r0", "sop-p71-t0-r5"} <= set(ids)


def test_zoa_sfo_lists_arrivals_naming_the_first_sector_rule(run):
    assert "loa-p12-t0-r0" in _ids("zoa", "SFO")
    ending = (
        "Area South (Sectors 10 & 11) to first sector entered, SERFR STAR, "
        "At filed altitude, LOA Table 1-1 p12"
    )
    line = _line_ending(run("zoa", "SFO", "--flow", "SFOW").stdout, ending)
    classes = line.removesuffix(ending)
    assert classes.strip() == "J"
    assert classes.endswith("  ")


def test_zoa_shoey_finds_a_token_inside_a_route():
    ids = _ids("zoa", "SHOEY")
    assert "loa-p12-t0-r2" in ids
    assert "loa-p16-t1-r3" in ids


def test_paradise_oak_answers_landing_nct_rows():
    ids = _ids("paradise", "OAK")
    assert {"sop-p130-t0-r12", "sop-p130-t0-r16", "sop-p130-t0-r17"} <= set(ids)


def test_paradise_sfo_drops_the_row_excepting_sfo():
    ids = _ids("paradise", "SFO")
    assert {"sop-p130-t0-r16", "sop-p130-t0-r17"} <= set(ids)
    assert "sop-p130-t0-r12" not in ids


def test_except_on_a_flow_needs_that_flow():
    ids = _ids("paradise", "OAK", chosen=SFOE)
    assert "sop-p130-t0-r12" in ids
    assert "sop-p130-t0-r17" not in ids


def test_licke_alias_resolves_to_its_complex():
    ids = _ids("licke", "Wine Country", chosen=SFOE)
    assert {"sop-p27-t0-r1", "sop-p27-t0-r5"} <= set(ids)


def test_licke_member_airport_matches_through_its_complex():
    assert "sop-p27-t0-r1" in _ids("licke", "APC", chosen=SFOE)


def test_cedar_sfo_entry_reads_the_entry_table(run):
    ids = _ids("cedar", "SFO", entry=True)
    assert {"sop-p54-t1-r2", "sop-p54-t1-r3"} <= set(ids)
    result = run("cedar", "SFO", "--entry", "--flow", "SFOW")
    assert any(
        line.startswith("T J  Morgan, 14,000") for line in result.stdout.splitlines()
    )


def test_grove_hwd_under_plain_sfoe_names_the_runway_flow(run):
    assert "sop-p98-t0-r0" in _ids("grove", "HWD", chosen=SFOE)
    lines = run("grove", "HWD", "--flow", "SFOE").stdout.splitlines()
    assert any(line.startswith("P T J  Richmond (SFO10), 4,000") for line in lines)


def test_silver_sfo_has_no_row_and_no_spelling_note(run):
    assert _ids("silver", "SFO") == []
    result = run("silver", "SFO", "--flow", "SFOW")
    assert result.exit_code == 0
    assert result.stdout == f"{NO_ROW}\n{SFOW_FLOWS_LINE}\n"
    assert SPELLING_NOTE not in result.stderr


def test_morgan_xyz_has_no_row_and_a_spelling_note(run):
    assert _ids("morgan", "XYZ") == []
    result = run("morgan", "XYZ", "--flow", "SFOW")
    assert result.exit_code == 0
    assert result.stdout == f"{NO_ROW}\n{SFOW_FLOWS_LINE}\n"
    assert f"No row matches XYZ {SPELLING_NOTE}" in result.stderr


def test_woodside_xyz_answers_the_catch_all_with_a_spelling_note(run):
    assert _ids("woodside", "XYZ") == ["sop-p71-t0-r5"]
    result = run("woodside", "XYZ", "--flow", "SFOW")
    assert result.exit_code == 0
    assert f"No row matches XYZ {SPELLING_NOTE}" in result.stderr


def test_flow_not_set_warns_and_assumes(run):
    result = run("morgan", "SFO", "J")
    assert "Flow not set: assuming SFOW, SMFS, RNOS." in result.stderr
    assert result.stdout.splitlines()[-1] == SFOW_FLOWS_LINE


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("SFOW", {"SFOW", "SMFS", "RNOS"}),
        ("oake", {"SFOW", "OAKE", "SMFS", "RNOS"}),
        ("SFO10", {"SFOE", "SFO10", "SMFS", "RNOS"}),
        ("SFOE,SMFN", {"SFOE", "SMFN", "RNOS"}),
        ("OAKE SJCE RNON", {"SFOW", "OAKE", "SJCE", "SMFS", "RNON"}),
    ],
)
def test_parse_flows(text: str, expected: set[str]):
    assert parse_flows(text) == expected


@pytest.mark.parametrize(
    "text", ["SFOE OAKE", "SFO10 SFO19", "SMFS SMFN", "RNOS RNON", "SFOW SFOE"]
)
def test_parse_flows_refuses(text: str):
    with pytest.raises(FlowError):
        parse_flows(text)


def test_parse_flows_refuses_an_unknown_name():
    with pytest.raises(FlowError, match="ZZZ"):
        parse_flows("ZZZ")


def test_unknown_sector_exits_1(run):
    result = run("nowhere", "SFO", "--flow", "SFOW")
    assert result.exit_code == 1
    assert "Unknown sector 'nowhere'. Known: " in result.stderr
    assert "Morgan" in result.stderr
    assert "zoa" in result.stderr


def test_unknown_class_exits_1(run):
    result = run("morgan", "SFO", "Z", "--flow", "SFOW")
    assert result.exit_code == 1
    assert "Unknown aircraft class 'Z'. Known: " in result.stderr


def test_bad_flow_exits_1(run):
    unknown = run("morgan", "SFO", "--flow", "ZZZ")
    assert unknown.exit_code == 1
    assert (
        "Unknown flow 'ZZZ'. Known: SFOW, SFOE, SFO10, SFO19, OAKE, SJCE, SMFS, SMFN, RNOS, RNON."
        in unknown.stderr
    )
    refused = run("morgan", "SFO", "--flow", "SFOE OAKE")
    assert refused.exit_code == 1
    assert (
        "Those flows can't run together: OAKE and SJCE need SFOW, SFO10 and SFO19 need SFOE "
        "and are set one at a time, and SMF and RNO each take one flow."
        in refused.stderr
    )


def test_zoa_entry_reaches_airport_departures(run):
    assert "loa-p13-t1-r0" in _ids("zoa", "SFO", entry=True)
    result = run("zoa", "SFO", "--entry", "--flow", "SFOW")
    lines = result.stdout.splitlines()
    assert any(
        line.startswith("J T  SFO to Area South (Sectors 10 & 11)") for line in lines
    )


def test_morgan_loa_departure():
    assert "loa-p13-t1-r9" in _ids("morgan", "AVE")


def test_five_registries_agree():
    from zoa_ref.autocomplete import INTERACTIVE_COMMANDS as COMPLETED_COMMANDS
    from zoa_ref.cli import main
    from zoa_ref.cli_utils import COMMAND_HELP, INTERACTIVE_HELP_COMMANDS
    from zoa_ref.interactive import INTERACTIVE_COMMANDS

    assert "xfer" in main.commands
    assert "xfer " in INTERACTIVE_COMMANDS
    assert "xfer" in COMMAND_HELP
    assert any("xfer <sector>" in line for line in INTERACTIVE_HELP_COMMANDS)
    assert "xfer" in COMPLETED_COMMANDS


def test_interactive_handler_answers(capsys: pytest.CaptureFixture[str]):
    from zoa_ref.interactive import _handle_xfer_interactive

    _handle_xfer_interactive("morgan SFO J -f SFOW")
    assert capsys.readouterr().out == f"{CEDAR_LINE}\n{SFOW_FLOWS_LINE}\n"
