"""Tests that the committed NCT route data carries the review's fixes and rulings."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

DATA = (
    Path(__file__).resolve().parents[1] / "src" / "zoa_ref" / "data" / "nct_routes.json"
)
TEN = {"SFOW", "SFOE", "SFO10", "SFO19", "SMFS", "SMFN", "RNOS", "RNON", "OAKE", "SJCE"}
ROW_KEYS = [
    "id",
    "doc",
    "page",
    "section",
    "table",
    "direction",
    "from",
    "to",
    "from_airports",
    "table_flows",
    "flows",
    "dest_or_route",
    "route",
    "qualifiers",
    "aircraft",
    "altitude",
    "info",
    "restrictions",
    "source",
]


@pytest.fixture(scope="module")
def data() -> dict[str, Any]:
    return json.loads(DATA.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def rows(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {row["id"]: row for row in data["rows"]}


def test_source_stamp(data: dict[str, Any]) -> None:
    assert data["source"] == {
        "sop": {"version": "1.13", "date": "04SEP2025"},
        "loa": {"version": "CHG08", "date": "07AUG2025"},
    }


def test_no_doubts_remain(data: dict[str, Any]) -> None:
    assert not [e for e in data["rows"] + data["pacp"] if "doubts" in e]


def test_row_ids_unique(data: dict[str, Any]) -> None:
    ids = [row["id"] for row in data["rows"]]
    assert len(ids) == len(set(ids))


def test_flows_are_the_ten(data: dict[str, Any]) -> None:
    assert set(data["flows"]) == TEN
    assert data["flows"]["SFO10"] == ["SFO landing Runway 10"]
    assert data["flows"]["SFO19"] == ["SFO landing Runway 19"]
    assert data["flows"]["OAKE"] == [
        "SFO landing Runways 01 or 28 and OAK landing Runways 10 and 12"
    ]
    assert data["flows"]["SJCE"] == [
        "SFO landing Runways 01 or 28 OAK landing Runways 28 and 30, SJC landing Runway 12"
    ]
    for row in data["rows"]:
        assert set(row["table_flows"] + row["flows"]) <= TEN, row["id"]
    for entry in data["pacp"]:
        assert set(entry["flows"]) <= TEN, entry["text"]


def test_design_example(data: dict[str, Any]) -> None:
    found = [
        row
        for row in data["rows"]
        if row["from"] == "Morgan"
        and row["to"] == "Cedar"
        and row["flows"] == ["SFOW"]
        and row["dest_or_route"] == ["SFO"]
    ]
    assert len(found) == 1
    row = found[0]
    assert row["aircraft"] == ["T", "J"]
    assert row["altitude"] == "14,000"
    assert row["info"] == "RV ALWYS/MOD"
    assert row["source"] == "SOP §3-4 p22"


def test_aligned_altitudes_paired(rows: dict[str, dict[str, Any]]) -> None:
    expected = {
        "sop-p25-t0-r0": ("MRY Runway 10", "5,000"),
        "sop-p25-t0-r1": ("Monterey CX", "7,000"),
        "sop-p27-t0-r2": ("Monterey CX", "5,000"),
        "sop-p27-t0-r3": ("Monterey Runway 10", "7,000"),
        "sop-p20-t1-r5": ("MRY Runway 10", "5,000"),
        "sop-p20-t1-r6": ("MRY Runway 10", "5,000"),
        "sop-p20-t1-r7": ("Monterey CX", "7,000"),
        "sop-p20-t1-r8": ("Monterey CX", "7,000"),
    }
    for row_id, (dest, altitude) in expected.items():
        assert rows[row_id]["dest_or_route"] == [dest], row_id
        assert rows[row_id]["altitude"] == altitude, row_id


def test_unaligned_altitudes_keep_both(rows: dict[str, dict[str, Any]]) -> None:
    assert rows["sop-p46-t0-r5"]["altitude"] == "5,000 / 7,000"
    assert rows["sop-p46-t0-r6"]["altitude"] == "5,000 / 7,000"
    assert rows["sop-p134-t0-r20"]["altitude"] == "4,000 / 6,000"


def test_no_unnormalised_two_altitudes(data: dict[str, Any]) -> None:
    two = re.compile(r"^\d,?\d{3}[/ ]+\d,?\d{3}$")
    exact = re.compile(r"^\d,\d{3} / \d,\d{3}$")
    bad = [
        (row["id"], row["altitude"])
        for row in data["rows"]
        if two.fullmatch(row["altitude"]) and not exact.fullmatch(row["altitude"])
    ]
    assert not bad


def test_sfo10_kept(data: dict[str, Any], rows: dict[str, dict[str, Any]]) -> None:
    for row_id in ("sop-p98-t0-r0", "sop-p98-t1-r0", "sop-p98-t1-r1"):
        assert rows[row_id]["table_flows"] == ["SFO10"]
        assert "SFO10" not in rows[row_id]["qualifiers"]
    boulder = [e for e in data["pacp"] if e["sector"] == "Boulder" and e["page"] == 53]
    assert [e["flows"] for e in boulder] == [["SFO10"]]
    assert data["flow_parents"] == {
        "SFO10": "SFOE",
        "SFO19": "SFOE",
        "OAKE": "SFOW",
        "SJCE": "SFOW",
    }


@pytest.mark.parametrize("page", [114, 119])
def test_info_tags_reach_flows(
    data: dict[str, Any], rows: dict[str, dict[str, Any]], page: int
) -> None:
    assert rows[f"sop-p{page}-t0-r4"]["flows"] == ["SFOW"]
    assert rows[f"sop-p{page}-t0-r5"]["flows"] == ["SJCE"]
    # An exact key list: the only flow fields a row has are these two.
    for row in data["rows"]:
        assert list(row) == ROW_KEYS, row["id"]


def test_sjcw_is_sfow(rows: dict[str, dict[str, Any]]) -> None:
    assert rows["loa-p16-t1-r6"]["flows"] == ["SFOW"]


def test_blank_cells_filled(rows: dict[str, dict[str, Any]]) -> None:
    assert rows["sop-p105-t0-r8"]["to"] == "Sunol"
    assert rows["sop-p131-t0-r14"]["aircraft"] == ["J"]


def test_empty_rows_dropped(
    data: dict[str, Any], rows: dict[str, dict[str, Any]]
) -> None:
    assert "sop-p33-t0-r13" not in rows
    assert not [
        r["id"] for r in data["rows"] if not r["dest_or_route"] and not r["altitude"]
    ]


def test_whole_routes_kept(rows: dict[str, dict[str, Any]]) -> None:
    assert rows["loa-p12-t0-r3"]["route"] == ["BSR or SHOEY V27 HADLY SAU"]
    for row_id in ("loa-p16-t1-r4-a", "loa-p16-t1-r4-b"):
        assert rows[row_id]["route"] == ["BSR or SHOEY V27 HADLY SAU"]
    for row_id in ("loa-p13-t1-r12", "loa-p16-t2-r2"):
        assert rows[row_id]["dest_or_route"] == ["BSR LIBBO TOKIO or SERFR"]


def test_kept_whole_cells(rows: dict[str, dict[str, Any]]) -> None:
    assert rows["sop-p54-t1-r1"]["dest_or_route"] == ["CEDES HARGO BLEAR FRAME"]
    assert rows["sop-p33-t0-r4"]["dest_or_route"] == ["SPTNS, SJC or SOLN DP’s"]
    assert (
        rows["sop-p46-t0-r0"]["info"]
        == "RNAV STAR or Abeam OSI RV 110° (SFOW) Abeam OSI RV 140° (SJCE)"
    )


@pytest.mark.parametrize(
    ("row_id", "other"),
    [
        ("loa-p18-t0-r9", "Grove"),
        ("loa-p18-t0-r16", "Boulder"),
        ("loa-p19-t0-r0", "Boulder"),
        ("loa-p19-t0-r1", "Grove"),
    ],
)
def test_sutro_splits(rows: dict[str, dict[str, Any]], row_id: str, other: str) -> None:
    west, east = rows[f"{row_id}-a"], rows[f"{row_id}-b"]
    assert (west["to"], west["flows"]) == ("Sutro", ["SFOW"])
    assert (east["to"], east["flows"]) == (other, ["SFOE"])
    assert row_id not in rows


def test_cedar_pacp_under_sfoe(data: dict[str, Any]) -> None:
    cedar = {
        entry["letter"]: entry["flows"]
        for entry in data["pacp"]
        if entry["sector"] == "Cedar" and entry["page"] == 55
    }
    assert cedar == {"a": ["SFOE"], "b": ["SFOE"]}


def test_ruling_4_symbol(data: dict[str, Any]) -> None:
    sectors = {sector["name"]: sector for sector in data["sectors"]["nct"]}
    assert sectors["Departure Combined (Sutro)"]["symbol"] == "4U"


def test_ccr_wine_country(rows: dict[str, dict[str, Any]]) -> None:
    assert rows["loa-p15-t0-r16"]["dest_or_route"] == ["CCR", "WINE COUNTRY"]


def test_oak_hwd_stays_sfow(rows: dict[str, dict[str, Any]]) -> None:
    assert rows["loa-p22-t0-r2"]["dest_or_route"] == ["OAK", "HWD"]
    assert rows["loa-p22-t0-r2"]["flows"] == ["SFOW"]


def test_handoff_split(data: dict[str, Any], rows: dict[str, dict[str, Any]]) -> None:
    for row in data["rows"]:
        assert "(J)" not in row["to"] and "(SFOW)" not in row["to"], row["id"]
    for row_id in ("loa-p16-t1-r0", "loa-p16-t1-r1", "loa-p16-t1-r2"):
        assert (rows[row_id]["to"], rows[row_id]["aircraft"]) == ("Laguna", ["J"])
    assert (rows["loa-p16-t1-r3"]["to"], rows["loa-p16-t1-r3"]["aircraft"]) == (
        "Seca",
        ["T", "P"],
    )
    jets, props = rows["loa-p16-t1-r4-a"], rows["loa-p16-t1-r4-b"]
    assert (jets["to"], jets["aircraft"]) == ("Laguna", ["J"])
    assert (props["to"], props["aircraft"]) == ("Seca", ["T", "P"])
    assert "loa-p16-t1-r4" not in rows


def test_sop_sectors_resolve(data: dict[str, Any]) -> None:
    names = {sector["name"] for sector in data["sectors"]["nct"]}
    unresolved = [
        (row["id"], name)
        for row in data["rows"]
        if row["doc"] == "SOP"
        for name in (row["from"], row["to"])
        if name and name not in names
    ]
    unresolved += [
        (row["id"], row["to"])
        for row in data["rows"]
        if row["direction"] == "loa_arrival" and row["to"] and row["to"] not in names
    ]
    assert not unresolved
    assert "Turlock" in names
    assert any(
        r["to"] == "Turlock" and r["direction"] == "loa_arrival" for r in data["rows"]
    )


def test_areas_and_turlock(data: dict[str, Any]) -> None:
    sectors = {sector["name"]: sector for sector in data["sectors"]["nct"]}
    assert sectors["Paradise"]["area"] == "Area E CA"
    assert sectors["Elkhorn"]["area"] == "Area E CA"
    assert sectors["Silver"]["area"] == "Area E NV"
    assert sectors["Nugget"]["area"] == "Area E NV"
    assert sectors["Turlock"]["symbol"] == "1Q"


def test_turlock_details(data: dict[str, Any]) -> None:
    sectors = {sector["name"]: sector for sector in data["sectors"]["nct"]}
    assert sectors["Turlock"]["frequency"] == "126.475"
    assert sectors["Turlock"]["combines_to"] == "Morgan"


def test_rules_present(data: dict[str, Any]) -> None:
    rules = {rule["id"]: rule for rule in data["rules"]}
    phrases = {
        "sop-1-13": '"FDIO" means an altitude that is appropriate for direction of '
        "flight and will retain the aircraft in the receiving sector's airspace.",
        "sop-1-15": "The receiving controller has control of the transferred aircraft "
        "for speed reduction, turns, a climb to the ceiling of, and/or a descent to "
        "the base altitude of the transferring controller’s airspace.",
        "loa-2": "Control statements in this agreement are in addition to the +/- 30 "
        "and descent/climb unless specifically stated as “only.”",
        "loa-2-n": "aircraft must be handed off to the first sector the aircraft "
        "enters in the receiving facility.",
        "loa-att3-1": "must verbally coordinate speed restrictions on the SFO OPD "
        "STARs except where noted in the tables below.",
        "loa-att3-2": "Control additions/restrictions listed in the tables below are "
        "upon contact unless otherwise noted.",
        "loa-att3-3": "NCT Area E must accomplish all intra-facility coordination when "
        "requesting or approving requests that affect both the NCT CA and NV sectors.",
    }
    for rule_id, phrase in phrases.items():
        assert phrase in rules[rule_id]["text"], rule_id
        assert rules[rule_id]["source"].strip(), rule_id
    for word in ("RV", "Direct", "FDIO"):
        assert word in rules["sop-1-13"]["text"]
