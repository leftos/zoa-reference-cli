"""Tests for the dev-only NCT route extractor, fed from saved page captures."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "nct_extract"


def _load_extractor() -> ModuleType:
    """Load ``tools/extract_nct_routes.py`` by path, since ``tools/`` is not a package."""
    spec = importlib.util.spec_from_file_location(
        "extract_nct_routes", REPO_ROOT / "tools" / "extract_nct_routes.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


extractor = _load_extractor()


def _pages(doc: str) -> list[dict[str, Any]]:
    paths = sorted(
        FIXTURES.glob(f"{doc}_p*.json"), key=lambda path: int(path.stem.split("_p")[1])
    )
    return [json.loads(path.read_text(encoding="utf-8")) for path in paths]


def _blank_page(number: int) -> dict[str, Any]:
    return {"number": number, "words": [], "h_edges": [], "v_edges": []}


def _word(text: str, x0: float, top: float) -> dict[str, Any]:
    return {
        "text": text,
        "x0": x0,
        "x1": x0 + 6.0 * len(text),
        "top": top,
        "bottom": top + 10.0,
    }


def _one_page(page: dict[str, Any]) -> Any:
    """Normalize a single SOP page, with only the real source-version pages beside it."""
    sop_versions = [p for p in _pages("sop") if p["number"] == 2]
    loa_versions = [p for p in _pages("loa") if p["number"] == 25]
    return extractor.normalize([*sop_versions, page], loa_versions)


@pytest.fixture(scope="module")
def result() -> Any:
    return extractor.normalize(_pages("sop"), _pages("loa"))


@pytest.fixture(scope="module")
def rows(result: Any) -> list[dict[str, Any]]:
    return result.draft["rows"]


def _select(rows: list[dict[str, Any]], **fields: Any) -> list[dict[str, Any]]:
    """Return the rows whose named fields equal the given values; ``from_`` means ``from``."""
    wanted = {key.rstrip("_"): value for key, value in fields.items()}
    return [
        row for row in rows if all(row[key] == value for key, value in wanted.items())
    ]


def _only(rows: list[dict[str, Any]], **fields: Any) -> dict[str, Any]:
    found = _select(rows, **fields)
    assert len(found) == 1, f"{fields} matched {len(found)} rows: {found}"
    return found[0]


def test_exit_row_with_flow_in_label(rows: list[dict[str, Any]]) -> None:
    row = _only(
        rows, page=22, from_="Morgan", to="Valley", flows=["SFOW"], aircraft=["P", "T"]
    )
    assert row["dest_or_route"] == ["V111"]
    assert row["altitude"] == "7,000"
    assert row["info"] == "Direct KARNN"
    assert row["source"] == "SOP §3-4 p22"
    assert row["direction"] == "exit"


def test_merged_info_fills_the_next_class_row(rows: list[dict[str, Any]]) -> None:
    row = _only(
        rows,
        page=22,
        from_="Morgan",
        to="Valley",
        flows=["SFOW"],
        aircraft=["J"],
        dest_or_route=["V111"],
    )
    assert row["altitude"] == "9,000"
    assert row["info"] == "Direct KARNN"


def test_design_example_row(rows: list[dict[str, Any]]) -> None:
    row = _only(rows, page=22, from_="Morgan", to="Cedar", flows=["SFOW"])
    assert row["dest_or_route"] == ["SFO"]
    assert row["aircraft"] == ["T", "J"]
    assert row["altitude"] == "14,000"
    assert row["info"] == "RV ALWYS/MOD"


def test_wrapped_altitude_is_one_cell(rows: list[dict[str, Any]]) -> None:
    row = _only(rows, page=22, from_="Morgan", to="Laguna", flows=["SFOW"])
    assert row["dest_or_route"] == ["SFO", "HAF"]
    assert row["aircraft"] == ["P", "T"]
    assert row["altitude"] == "12,000 or lower filed"
    assert row["info"] == "RV OSI"


def test_merged_sector_and_route_fill_down(rows: list[dict[str, Any]]) -> None:
    pxn = _select(
        rows,
        page=22,
        from_="Morgan",
        to="Toga",
        flows=["SFOE"],
        dest_or_route=["PXN STAR"],
    )
    assert [(row["aircraft"], row["altitude"]) for row in pxn] == [
        (["P", "T"], "Cross BORED @8,000"),
        (["J"], "Cross BORED @10,000"),
    ]
    assert all(row["qualifiers"] == ["HWD only"] for row in pxn)


def test_split_destinations(rows: list[dict[str, Any]]) -> None:
    row = _only(
        rows,
        page=22,
        from_="Morgan",
        to="Sunol",
        flows=["SFOW"],
        dest_or_route=["Stockton CX", "LVK", "Oakland CX", "Travis CX"],
    )
    assert row["aircraft"] == ["P", "T", "J"]
    assert row["altitude"] == "12,000 or lower filed"


def test_merged_alt_spans_destinations(rows: list[dict[str, Any]]) -> None:
    toga = _select(rows, page=22, from_="Morgan", to="Toga", flows=["SJCE"])
    assert [row["dest_or_route"] for row in toga] == [["RHV"], ["PAO"], ["SQL"]]
    assert all(row["aircraft"] == ["P"] and row["altitude"] == "6,000" for row in toga)


def test_floating_label(rows: list[dict[str, Any]]) -> None:
    row = _only(
        rows,
        page=22,
        from_="Morgan",
        to="Sunol",
        dest_or_route=["EMZOH"],
        flows=["SFOW", "OAKE"],
    )
    assert row["aircraft"] == ["J"]
    assert row["altitude"] == "Descend Via"


def test_two_altitudes_cell_is_doubted(rows: list[dict[str, Any]]) -> None:
    row = _only(
        rows, page=46, from_="Boulder", to="Seca", dest_or_route=["Landing MRY"]
    )
    assert row["altitude"] == "5,000 7,000"
    assert row["doubts"]


def test_grove_entry_two_labels(rows: list[dict[str, Any]]) -> None:
    for sector, flows in (("Toga", ["SFOW"]), ("Licke", ["SJCE"])):
        assert _select(rows, page=92, from_=sector, table_flows=["SFOW"], flows=flows)
        row = _only(
            rows,
            page=92,
            direction="entry",
            from_=sector,
            to="Grove",
            flows=flows,
            qualifiers=["PAO and SQL Departures Only"],
        )
        assert row["dest_or_route"] == ["Napa CX", "Oakland CX", "Travis CX"]
        assert row["altitude"] == "3,000"


def test_pacp_inside_table_bbox(result: Any, rows: list[dict[str, Any]]) -> None:
    grove = [
        line
        for line in result.draft["pacp"]
        if line["sector"] == "Grove" and line["page"] == 92
    ]
    first = grove[0]
    assert first["flows"] == ["SFOW"]
    assert first["letter"] == "a"
    assert first["text"].startswith("Protect the SAU-OAK arrivals")
    assert not [
        row for row in rows if "SAU-OAK" in row["info"] or "SAU-OAK" in row["altitude"]
    ]


def test_loa_arrival_merged_altitude_and_handoff(rows: list[dict[str, Any]]) -> None:
    row = _only(rows, page=12, doc="LOA", dest_or_route=["OAK"], route=["EMZOH STAR"])
    assert row["aircraft"] == ["J"]
    assert row["altitude"] == "Descend via or @ lower filed"
    assert row["to"] == "Morgan"
    assert row["restrictions"] == "NCT control RV right of course only"
    assert row["direction"] == "loa_arrival"
    assert "Area South" in row["from"]


def test_loa_empty_handoff_stays_empty(rows: list[dict[str, Any]]) -> None:
    row = _only(rows, page=12, doc="LOA", dest_or_route=["SFO"], route=["SERFR STAR"])
    assert row["aircraft"] == ["J"]
    assert row["altitude"] == "At filed altitude"
    assert row["to"] == ""
    assert row["flows"] == ["SFOW"]
    assert row["source"] == "LOA Table 1-1 p12"


def test_complexes(result: Any) -> None:
    assert result.draft["complexes"]["San Jose"] == ["SJC", "NUQ", "PAO", "RHV", "E16"]


def test_sector_combine_and_symbol(result: Any) -> None:
    sectors = {sector["name"]: sector for sector in result.draft["sectors"]["nct"]}
    assert sectors["Licke"]["symbol"] == "1L"
    assert sectors["Licke"]["combines_to"] == "Toga"
    assert sectors["Seca"]["symbol"] == "1S"
    assert sectors["Seca"]["loa_code"] == "Q2S"


def test_source_versions(result: Any) -> None:
    assert result.draft["source"]["sop"] == {"version": "1.13", "date": "04SEP2025"}
    assert result.draft["source"]["loa"] == {"version": "CHG08", "date": "07AUG2025"}


def test_empty_page_yields_no_rows_or_tables() -> None:
    outcome = _one_page(_blank_page(40))
    assert outcome.draft["rows"] == []
    assert outcome.coverage["SOP"].found == 0


def test_headerless_table_is_skipped_only_on_a_listed_page() -> None:
    listed = _one_page(_grid_page(16))
    assert listed.draft["rows"] == []
    assert listed.coverage["SOP"].found == 0
    assert listed.coverage["SOP"].unconsumed == []
    unlisted = _one_page(_grid_page(40))
    assert unlisted.draft["rows"] == []
    assert [item for item in unlisted.coverage["SOP"].unconsumed if "p40" in item]


def test_reserved_page_yields_no_rows() -> None:
    page = _blank_page(40)
    title = ["Foster", "SFOE", "Exit", "Routes"]
    page["words"] = [
        _word(text, 36.0 + 60.0 * index, 40.0) for index, text in enumerate(title)
    ]
    page["words"].append(_word("Reserved.", 36.0, 60.0))
    outcome = _one_page(page)
    assert outcome.draft["rows"] == []
    assert outcome.coverage["SOP"].unconsumed == []


@pytest.mark.parametrize("doc", ["SOP", "LOA"])
def test_missing_source_version_names_the_document(doc: str) -> None:
    sop = [_blank_page(2)] if doc == "SOP" else _pages("sop")
    loa = [_blank_page(25)] if doc == "LOA" else _pages("loa")
    with pytest.raises(extractor.ExtractError, match=doc):
        extractor.normalize(sop, loa)


SOP_EDGES = (50.0, 150.0, 300.0, 350.0, 450.0, 560.0)
SOP_HEADERS = ("SECTOR", "DEST/ROUTE", "ACFT", "ALT", "HDG/INFO")
LOA_ARRIVAL_HEADERS = (
    "Destination",
    "Route",
    "ACFT",
    "Altitude",
    "Handoff",
    "Requirements",
)
LOA_ARRIVAL_EDGES = (50.0, 150.0, 250.0, 300.0, 400.0, 470.0, 590.0)
LOA_ARRIVAL_TITLE = "Table 1-1. From Area South (Sectors 10 & 11) to NCT west of NLC."
TABLE_TOP = 100.0
HEADER_BOTTOM = 115.0
ROW_HEIGHT = 30.0


def _text_words(text: str, x0: float, top: float) -> list[dict[str, Any]]:
    """Lay a line of text out as words, left to right, from ``x0``."""
    words = []
    for token in text.split():
        words.append(_word(token, x0, top))
        x0 += 6.0 * len(token) + 3.0
    return words


def _table_page(
    title: str,
    headers: tuple[str, ...] = SOP_HEADERS,
    edges: tuple[float, ...] = SOP_EDGES,
    rows_of_cells: tuple[tuple[str, ...], ...] = (
        ("Valley", "V111", "P", "7,000", "Direct KARNN"),
    ),
    heading: str | None = "3-4 Morgan",
) -> dict[str, Any]:
    """Build a captured page holding one fully ruled table, with a ``\\n`` wrapping a cell."""
    page = _blank_page(40)
    if heading is not None:
        page["words"] += _text_words(heading, 36.0, 40.0)
    page["words"] += _text_words(title, 36.0, 85.0)
    for index, header in enumerate(headers):
        page["words"].append(_word(header, edges[index] + 3.0, TABLE_TOP + 2.0))
    bottom = HEADER_BOTTOM + ROW_HEIGHT * len(rows_of_cells)
    ys = [
        TABLE_TOP,
        *[HEADER_BOTTOM + ROW_HEIGHT * n for n in range(len(rows_of_cells) + 1)],
    ]
    page["h_edges"] = [{"y": y, "x0": edges[0], "x1": edges[-1]} for y in ys]
    page["v_edges"] = [{"x": x, "top": TABLE_TOP, "bottom": bottom} for x in edges]
    for number, cells in enumerate(rows_of_cells):
        for column, cell in enumerate(cells):
            for line, text in enumerate(cell.split("\n")):
                top = HEADER_BOTTOM + ROW_HEIGHT * number + 2.0 + 11.0 * line
                page["words"] += _text_words(text, edges[column] + 3.0, top)
    return page


def _sop_row(*cells: str) -> dict[str, Any]:
    """Return the one row of a synthetic SOP exit table with these five cells."""
    outcome = _one_page(_table_page("Morgan Exit Routes", rows_of_cells=(cells,)))
    assert outcome.coverage["SOP"].unconsumed == []
    return outcome.draft["rows"][0]


def _one_loa_page(page: dict[str, Any]) -> Any:
    sop_versions = [p for p in _pages("sop") if p["number"] == 2]
    loa_versions = [p for p in _pages("loa") if p["number"] == 25]
    return extractor.normalize(sop_versions, [*loa_versions, page])


def _loa_arrival_row(*cells: str) -> dict[str, Any]:
    page = _table_page(
        LOA_ARRIVAL_TITLE,
        LOA_ARRIVAL_HEADERS,
        LOA_ARRIVAL_EDGES,
        (cells,),
        heading=None,
    )
    outcome = _one_loa_page(page)
    assert outcome.coverage["LOA"].unconsumed == []
    return outcome.draft["rows"][0]


def _doubts_with(row: dict[str, Any], text: str) -> list[str]:
    return [doubt for doubt in row["doubts"] if text in doubt]


def _unsplit(row: dict[str, Any]) -> list[str]:
    return [doubt for doubt in row["doubts"] if doubt.startswith("unsplit: ")]


def test_table_flow_and_label_flow_both_kept(rows: list[dict[str, Any]]) -> None:
    valley = _only(
        rows, page=22, to="Valley", aircraft=["P", "T"], dest_or_route=["V111"]
    )
    assert (valley["table_flows"], valley["flows"]) == ([], ["SFOW"])
    licke = _only(rows, page=33, direction="exit", to="Licke", dest_or_route=["V107"])
    assert (licke["table_flows"], licke["flows"]) == (["SFOW"], [])
    smfs = _only(rows, page=130, to="Sunol", altitude="10,000", aircraft=["P", "T"])
    assert (smfs["table_flows"], smfs["flows"]) == (["SMFS"], ["SFOW"])
    assert smfs["info"] == "RV ALWYS CEDES"
    grove = _only(rows, id="sop-p96-t0-r5")
    assert grove["to"] == "Toga"
    assert (grove["table_flows"], grove["flows"]) == (["OAKE"], ["SFOW"])
    two = _select(rows, page=22, to="Licke", flows=["SJCE", "SFOE"])
    assert [row["aircraft"] for row in two] == [["T"], ["J"]]
    assert all(row["table_flows"] == [] for row in two)
    sfo = _only(rows, page=12, doc="LOA", route=["SERFR STAR"])
    assert (sfo["table_flows"], sfo["flows"]) == ([], ["SFOW"])


def test_out_of_list_flow_stays_and_is_doubted() -> None:
    page = _table_page("Grove SFO10 Exit Routes")
    row = _one_page(page).draft["rows"][0]
    assert row["table_flows"] == ["SFO10"]
    assert _doubts_with(row, "SFO10")
    label = _sop_row("Valley (SJCW)", "V111", "P", "7,000", "Direct KARNN")
    assert label["flows"] == ["SJCW"]
    assert _doubts_with(label, "SJCW")


def test_loa_requirements_flow_is_doubted(rows: list[dict[str, Any]]) -> None:
    row = _only(rows, id="loa-p17-t0-r0")
    assert "(SFOW only)" in row["restrictions"]
    assert _doubts_with(row, "'SFOW' in the requirements column")


def test_loa_departure_from_parsing(rows: list[dict[str, Any]]) -> None:
    cedar = _only(rows, page=14, doc="LOA", from_="Cedar")
    assert cedar["from_airports"] == []
    pair = [row["from"] for row in rows if row["id"].startswith("loa-p19-t1")]
    assert pair.count("Elkhorn") == pair.count("Paradise") == 2
    morgan = _only(rows, page=16, doc="LOA", from_="Morgan")
    assert morgan["qualifiers"] == ["Landing VIS, FAT, or FCH"]
    lvk = _only(rows, page=13, doc="LOA", from_airports=["LVK", "HWD", "SUU", "CCR"])
    assert lvk["from"] == ""
    assert lvk["qualifiers"] == ["Eastbound"]
    assert lvk["dest_or_route"] == ["CEDES MKNNA"]
    sfo = _only(rows, page=14, doc="LOA", from_airports=["SFO", "OAK", "HWD"])
    assert sfo["from"] == ""
    filed = _only(
        rows,
        page=22,
        doc="LOA",
        direction="loa_departure",
        from_="",
        to="Area East (Sector 44)",
        from_airports=[],
        qualifiers=["Filed over MVA, OAL or DUDES"],
    )
    assert _doubts_with(filed, "Filed over MVA")


def test_loa_departure_from_keeps_the_altitude_deciding_text(
    rows: list[dict[str, Any]],
) -> None:
    for sector in ("Boulder", "Sutro", "Richmond"):
        apc = _only(
            rows,
            page=20,
            from_=sector,
            qualifiers=["APC/CA35/O69"],
            route=[],
            dest_or_route=["VNYRD STAR"],
        )
        assert apc["altitude"] == "X VNYRD @ 100"
        assert apc["flows"] == ["SFOW"]
        hes = _only(
            rows,
            page=20,
            from_=sector,
            qualifiers=["HES/STS/DVO"],
            dest_or_route=["VNYRD STAR"],
        )
        assert hes["altitude"] == "↓ 100"


def test_row_ids_are_unique(rows: list[dict[str, Any]]) -> None:
    ids = [row["id"] for row in rows]
    assert len(ids) == len(set(ids))


def test_condition_not_split(rows: list[dict[str, Any]]) -> None:
    row = _only(rows, id="sop-p23-t0-r4")
    assert row["dest_or_route"] == ["East of or on T263"]
    assert _unsplit(row)
    fmg = _select(
        rows, page=22, doc="LOA", dest_or_route=["On or E of FMG163.FMG"]
    ) or _select(rows, page=22, doc="LOA", route=["On or E of FMG163.FMG"])
    assert fmg
    assert all(_unsplit(found) for found in fmg)


def test_requesting_altitude_not_split(rows: list[dict[str, Any]]) -> None:
    first = _only(rows, id="sop-p91-t0-r10")
    second = _only(rows, id="sop-p105-t1-r0")
    assert first["dest_or_route"] == ["Northbound requesting 6,000 or higher"]
    assert second["dest_or_route"] == ["Northbound, requesting 6,000 or higher"]
    assert _unsplit(first)
    assert _unsplit(second)


def test_shared_cx_distributes(rows: list[dict[str, Any]]) -> None:
    row = _only(rows, id="sop-p130-t0-r19")
    assert row["dest_or_route"] == ["Modesto CX", "Stockton CX"]
    assert not _unsplit(row)


def test_airports_split_in_destination_only(rows: list[dict[str, Any]]) -> None:
    row = _only(rows, page=18, doc="LOA", route=["PYE STAR", "PYE V27 HADLY OSI"])
    assert row["dest_or_route"] == ["SJC", "NUQ", "PAO", "RHV", "SQL", "E16"]
    spaced = _only(rows, page=12, doc="LOA", route=["BSR SHOEY OSI", "SNS V25 OSI"])
    assert spaced["dest_or_route"] == ["SFO"]
    assert spaced["flows"] == ["SFOW"]


def test_ampersand_splits(rows: list[dict[str, Any]]) -> None:
    row = _only(rows, id="sop-p96-t1-r1")
    reciprocal = _only(rows, id="sop-p61-t0-r0")
    assert row["dest_or_route"] == ["Oakland CX", "OAK V6"]
    assert row["dest_or_route"] == reciprocal["dest_or_route"]


def test_prose_stays_whole_and_doubted(rows: list[dict[str, Any]]) -> None:
    cinny = _only(rows, id="loa-p17-t1-r3")
    assert len(cinny["dest_or_route"]) == 1
    assert "CINNY All others heading 260" in cinny["dest_or_route"][0]
    assert _unsplit(cinny)
    hunter = _only(rows, id="loa-p14-t0-r5")
    assert len(hunter["dest_or_route"]) == 1
    assert (
        "aircraft between 7,000 and 9,000 must be routed via"
        in hunter["dest_or_route"][0]
    )
    assert _unsplit(hunter)


def test_route_phrase_splits_on_or() -> None:
    row = _sop_row("Sunol", "V111 or RV MOD", "T, J", "7,000", "Direct KARNN")
    assert row["dest_or_route"] == ["V111", "RV MOD"]
    assert not _unsplit(row)
    phrase = _sop_row("Sunol", "PXN V301 SUNOL", "T, J", "7,000", "Direct KARNN")
    assert phrase["dest_or_route"] == ["PXN V301 SUNOL"]
    assert not _unsplit(phrase)


def _grid_page(number: int) -> dict[str, Any]:
    page = _blank_page(number)
    page["words"] = [_word("Alpha", 60.0, 110.0), _word("Bravo", 260.0, 110.0)]
    page["h_edges"] = [{"y": y, "x0": 50.0, "x1": 450.0} for y in (100.0, 130.0)]
    page["v_edges"] = [
        {"x": x, "top": 100.0, "bottom": 130.0} for x in (50.0, 250.0, 450.0)
    ]
    return page


def test_one_column_box_is_not_a_grid() -> None:
    page = _grid_page(40)
    page["v_edges"] = [{"x": x, "top": 100.0, "bottom": 130.0} for x in (50.0, 450.0)]
    assert _one_page(page).coverage["SOP"].unconsumed == []


def test_border_gap_with_rows_below_is_unconsumed() -> None:
    page = _table_page(
        "Morgan Exit Routes",
        rows_of_cells=(
            ("Valley", "V111", "P", "7,000", "Direct KARNN"),
            ("Seca", "MRY", "T", "9,000", "Direct MRY"),
        ),
    )
    left = SOP_EDGES[0]
    page["v_edges"] = [
        edge if edge["x"] != left else {"x": left, "top": TABLE_TOP, "bottom": 145.0}
        for edge in page["v_edges"]
    ]
    page["v_edges"].append({"x": left, "top": 160.0, "bottom": 175.0})
    unconsumed = _one_page(page).coverage["SOP"].unconsumed
    assert [item for item in unconsumed if "p40" in item and "below" in item]


def test_unconsumed_table_exits_nonzero_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    page = _table_page("Not a table title")
    sop = [p for p in _pages("sop") if p["number"] in (2, 6, 7, 18)]
    loa = [p for p in _pages("loa") if p["number"] in (11, 25)]
    captures = {"sop.pdf": [*sop, page], "loa.pdf": loa}
    monkeypatch.setattr(extractor, "capture_pdf", lambda path: captures[path.name])
    out = tmp_path / "draft.json"
    code = extractor.main(["--sop", "sop.pdf", "--loa", "loa.pdf", "--out", str(out)])
    assert code != 0
    assert not out.exists()


def _sop_error(page: dict[str, Any]) -> str:
    unconsumed = _one_page(page).coverage["SOP"].unconsumed
    assert len(unconsumed) == 1, unconsumed
    return unconsumed[0]


def test_no_rule_under_header_names_the_page() -> None:
    page = _table_page("Morgan Exit Routes")
    page["h_edges"] = []
    error = _sop_error(page)
    assert "p40" in error
    assert "no ruled line under the header" in error


def test_no_border_names_the_page() -> None:
    page = _table_page("Morgan Exit Routes")
    page["v_edges"] = []
    error = _sop_error(page)
    assert "p40" in error
    assert "no ruled border" in error


def test_no_column_rule_names_the_page() -> None:
    page = _table_page("Morgan Exit Routes")
    outer = (SOP_EDGES[0], SOP_EDGES[-1])
    page["v_edges"] = [edge for edge in page["v_edges"] if edge["x"] in outer]
    error = _sop_error(page)
    assert "p40" in error
    assert "no column rule" in error


def test_no_rows_names_the_page() -> None:
    page = _table_page("Morgan Exit Routes")
    page["v_edges"] = [
        {**edge, "bottom": HEADER_BOTTOM + 3.0} for edge in page["v_edges"]
    ]
    page["h_edges"] = [edge for edge in page["h_edges"] if edge["y"] <= HEADER_BOTTOM]
    error = _sop_error(page)
    assert "p40" in error
    assert "no rows" in error


def test_loa_title_without_area_names_the_page() -> None:
    page = _table_page(
        "Table 1-1. Something else entirely.",
        LOA_ARRIVAL_HEADERS,
        LOA_ARRIVAL_EDGES,
        (("SFO", "SERFR STAR", "J", "FL200", "", ""),),
        heading=None,
    )
    unconsumed = _one_loa_page(page).coverage["LOA"].unconsumed
    assert [
        item for item in unconsumed if "p40" in item and "names no ZOA area" in item
    ]


def test_sop_title_that_is_no_title_names_the_page() -> None:
    error = _sop_error(_table_page("Not a table title"))
    assert "p40" in error
    assert "isn't an exit or entry title" in error


def test_loa_table_without_title_names_the_page() -> None:
    page = _table_page(
        "Not a table title",
        LOA_ARRIVAL_HEADERS,
        LOA_ARRIVAL_EDGES,
        (("SFO", "SERFR STAR", "J", "FL200", "", ""),),
        heading=None,
    )
    unconsumed = _one_loa_page(page).coverage["LOA"].unconsumed
    assert [
        item for item in unconsumed if "p40" in item and "isn't a table title" in item
    ]


def test_table_before_any_heading_names_the_page() -> None:
    error = _sop_error(_table_page("Morgan Exit Routes", heading=None))
    assert "p40" in error
    assert "section heading" in error


def test_unknown_altitude_is_doubted() -> None:
    row = _sop_row("Valley", "V111", "P", "Banana", "Direct KARNN")
    assert _doubts_with(row, "altitude matches no known form")


def test_missing_sector_is_doubted() -> None:
    row = _sop_row("", "V111", "P", "7,000", "Direct KARNN")
    assert _doubts_with(row, "row lists no sector")


def test_missing_destination_is_doubted() -> None:
    row = _sop_row("Valley", "", "P", "7,000", "Direct KARNN")
    assert _doubts_with(row, "row lists no destination")


def test_missing_class_is_doubted() -> None:
    row = _sop_row("Valley", "V111", "", "7,000", "Direct KARNN")
    assert _doubts_with(row, "row lists no aircraft class")


def test_class_outside_ptj_is_doubted() -> None:
    row = _sop_row("Valley", "V111", "DH8D", "7,000", "Direct KARNN")
    assert row["aircraft"] == ["DH8D"]
    assert _doubts_with(row, "aircraft class 'DH8D'")


def test_flow_in_info_is_doubted() -> None:
    row = _sop_row("Valley", "V111", "P", "7,000", "OSI RV 110 (SFOW)")
    assert _doubts_with(row, "'SFOW' in the info column")


def test_flow_in_route_is_doubted() -> None:
    row = _sop_row("Valley", "V111 (SFOW)", "P", "7,000", "Direct KARNN")
    assert _doubts_with(row, "'SFOW' in the route column")


def test_two_altitudes_are_doubted() -> None:
    row = _sop_row("Valley", "V111", "P", "5,000\n7,000", "Direct KARNN")
    assert row["altitude"] == "5,000 7,000"
    assert _doubts_with(row, "two altitudes")


def test_crossing_word_is_doubted() -> None:
    page = _table_page("Morgan Exit Routes")
    page["words"].append(_word("STRADDLE", SOP_EDGES[1] - 20.0, 125.0))
    row = _one_page(page).draft["rows"][0]
    assert _doubts_with(row, "'STRADDLE' crosses a column line")


def test_rejoined_word_is_doubted() -> None:
    row = _loa_arrival_row("OAK", "EMZOH STAR", "J", "FL200", "MORGA\nN", "")
    assert row["to"] == "Morgan"
    assert _doubts_with(row, "rejoined a word broken across lines: MORGAN")


def test_unknown_handoff_is_doubted() -> None:
    row = _loa_arrival_row("OAK", "EMZOH STAR", "J", "FL200", "BANANA", "")
    assert row["to"] == "Banana"
    assert _doubts_with(row, "handoff 'Banana'")


def test_loa_departure_row(rows: list[dict[str, Any]]) -> None:
    row = _only(rows, page=13, doc="LOA", from_="Seca")
    assert row["direction"] == "loa_departure"
    assert row["dest_or_route"] == ["BSR V27"]
    assert row["route"] == []
    assert row["aircraft"] == ["J", "T"]
    assert row["altitude"] == "↑ FL190 or lower filed altitude"
    assert row["to"] == "Area South (Sectors 10 & 11)"
    assert row["restrictions"] == "Aircraft @070 must be routed BSR V27 MQO"
    assert row["source"] == "LOA Table 1-2 p13"


def test_word_in_no_cell_is_doubted() -> None:
    page = _table_page("Morgan Exit Routes")
    page["words"].append(_word("STRAY", SOP_EDGES[-1] - 10.0, 125.0))
    row = _one_page(page).draft["rows"][0]
    assert _doubts_with(row, "'STRAY' landed in no cell")


def test_pacp_heading_flow_mismatch_is_doubted(result: Any) -> None:
    cedar = [line for line in result.draft["pacp"] if line["page"] == 55]
    assert cedar
    for line in cedar:
        assert line["sector"] == "Cedar"
        assert line["flows"] == ["SFOW"]
        assert [d for d in line["doubts"] if "SFOW" in d and "4-13 Cedar - SFOE" in d]
    grove = [line for line in result.draft["pacp"] if line["page"] == 92]
    assert all(line["doubts"] == [] for line in grove)


def test_wrapped_hyphen_joins(rows: list[dict[str, Any]]) -> None:
    cell = extractor.Cell(0.0, 1.0, ("VFR aircraft south-", "bound along"))
    assert cell.text == "VFR aircraft south-bound along"
    assert extractor.Cell(0.0, 1.0, ("A-", "Bravo")).text == "A- Bravo"
    first = _only(rows, id="sop-p119-t1-r4")["dest_or_route"]
    second = _only(rows, id="sop-p96-t0-r14")["dest_or_route"]
    assert first == ["VFR tours and VFR aircraft south-bound along Bayshore Freeway"]
    assert first == second


def test_render_draft_shape(result: Any, rows: list[dict[str, Any]]) -> None:
    text = extractor.render_draft(result.draft)
    assert list(json.loads(text)) == [
        "source",
        "flows",
        "sectors",
        "complexes",
        "aliases",
        "pacp",
        "rows",
    ]
    row_lines = [line for line in text.splitlines() if line.startswith('    {"id"')]
    assert len(row_lines) == len(rows)
    assert json.loads(row_lines[0].rstrip(",")) == rows[0]
    assert list(rows[0]) == [
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
        "doubts",
    ]


def test_shading_rect_is_not_a_rule() -> None:
    def rect(width: float, height: float, shade: float | None) -> dict[str, Any]:
        return {
            "object_type": "rect",
            "width": width,
            "height": height,
            "non_stroking_color": shade,
            "stroking_color": 0,
        }

    assert not extractor._is_dark_rule(rect(100.0, 15.0, 0.0))
    assert not extractor._is_dark_rule(rect(100.0, 0.5, 0.8))
    assert not extractor._is_dark_rule(rect(0.5, 0.5, 0.0))
    assert not extractor._is_dark_rule(rect(100.0, 0.5, None))
    assert extractor._is_dark_rule(rect(100.0, 0.5, 0.0))
    line = {
        "object_type": "line",
        "width": 100.0,
        "height": 0.0,
        "stroking_color": (0.0, 0.0, 0.0),
        "non_stroking_color": 1.0,
    }
    assert extractor._is_dark_rule(line)


def test_flow_mid_destination_cell_is_doubted(rows: list[dict[str, Any]]) -> None:
    both = _only(rows, id="loa-p22-t0-r2")
    assert both["dest_or_route"] == ["OAK", "HWD"]
    assert both["flows"] == ["SFOW"]
    assert _doubts_with(both, "text follows flow (SFOW)")
    below = _only(rows, id="loa-p22-t0-r3")
    assert below["dest_or_route"] == ["OAK"]
    assert below["flows"] == ["SFOE"]
    assert not _doubts_with(below, "text follows flow")


def _or_scope(row: dict[str, Any]) -> list[str]:
    return [doubt for doubt in row["doubts"] if doubt.startswith("or scope: ")]


def test_or_scope_doubt(rows: list[dict[str, Any]]) -> None:
    shared = _only(rows, id="loa-p12-t0-r3")
    assert shared["route"] == ["BSR", "SHOEY V27 HADLY SAU"]
    assert _or_scope(shared) == [
        "or scope: 'BSR or SHOEY V27 HADLY SAU' may share a route tail"
    ]
    for row_id in ("loa-p13-t1-r12", "loa-p16-t2-r2"):
        tail = _only(rows, id=row_id)
        assert tail["dest_or_route"] == ["BSR LIBBO TOKIO", "SERFR"]
        assert _or_scope(tail) == [
            "or scope: 'BSR LIBBO TOKIO or SERFR' may share a route tail"
        ]
    two = _sop_row("Sunol", "V111 or RV MOD", "T, J", "7,000", "Direct KARNN")
    assert two["dest_or_route"] == ["V111", "RV MOD"]
    assert not _or_scope(two)
    pair = _only(rows, page=22, doc="SOP", to="Laguna", flows=["SFOW"])
    assert pair["dest_or_route"] == ["SFO", "HAF"]
    assert not _or_scope(pair)
    neither = _only(rows, page=12, doc="LOA", route=["BSR SHOEY OSI", "SNS V25 OSI"])
    assert not _or_scope(neither)
    listed = ["Stockton CX", "LVK", "Oakland CX", "Travis CX"]
    list_row = _only(rows, page=22, doc="SOP", flows=["SFOW"], dest_or_route=listed)
    assert not _or_scope(list_row)


def test_or_scope_doubt_reaches_exit_and_entry() -> None:
    cell = "BSR LIBBO TOKIO or SERFR"
    for title in ("Morgan Exit Routes", "Morgan Entry Routes"):
        page = _table_page(
            title, rows_of_cells=(("Valley", cell, "T", "7,000", "Direct KARNN"),)
        )
        row = _one_page(page).draft["rows"][0]
        assert _or_scope(row) == [f"or scope: {cell!r} may share a route tail"]


def test_sop_destination_flow_reaches_flows(rows: list[dict[str, Any]]) -> None:
    west = _only(rows, id="sop-p65-t0-r2")
    assert west["from"] == "Morgan"
    assert west["to"] == "Laguna"
    assert west["dest_or_route"] == ["SFO", "HAF"]
    assert west["flows"] == ["SFOW"]
    assert west["table_flows"] == []
    assert west["aircraft"] == ["P", "T"]
    assert west["altitude"] == "12,000 or lower filed"
    assert west["info"] == "RV OSI"
    assert _doubts_with(west, "'SFOW' in the route column")
    east = _only(rows, id="sop-p65-t0-r3")
    assert east["dest_or_route"] == ["SFO"]
    assert east["flows"] == ["SFOE"]
    assert east["info"] == "Direct SHOEY HADLY"
    assert _doubts_with(east, "'SFOE' in the route column")


def test_sop_label_and_destination_flows_join_without_duplicates() -> None:
    row = _sop_row("Valley (SFOW/OAKE)", "V111 (OAKE)", "P", "7,000", "Direct KARNN")
    assert row["flows"] == ["SFOW", "OAKE"]
    other = _sop_row("Valley (SFOW)", "V111 (SFOE)", "P", "7,000", "Direct KARNN")
    assert other["flows"] == ["SFOW", "SFOE"]
