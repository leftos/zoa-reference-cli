"""Draft the NCT handoff data from the NCT SOP and NCT-ZOA LOA PDFs (dev-only).

Two stages keep the parsing testable without a PDF or pdfplumber. ``capture`` reduces
PDF pages to plain JSON (words and ruled lines); ``normalize`` turns captured pages
into the draft. Run it with::

    uv run --group extract python tools/extract_nct_routes.py --sop <pdf> --loa <pdf> --out <json>

Add ``--capture-pages SOP:22,92 LOA:12 --capture-out <dir>`` to write page captures
instead of a draft.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path
from typing import Any, NamedTuple

Page = dict[str, Any]
Word = dict[str, Any]
Row = dict[str, Any]
ColumnSpec = tuple[tuple[str, tuple[str, ...]], ...]

MAX_RULE_THICKNESS = 1.5
MIN_RULE_LENGTH = 2.0
MAX_RULE_SHADE = 0.5

LINE_TOLERANCE = 3.0
HEADER_TOLERANCE = 12.0
EDGE_TOLERANCE = 2.5
BORDER_GAP = 2.5
CROSSING_MARGIN = 2.0
MIN_ROW_HEIGHT = 5.0
MIN_BAND_COVERAGE = 0.5
TITLE_REACH = 30.0
FOOTER_TOP = 740.0
INDENT_MARGIN = 5.0
HEADER_REACH = 12.0
MIN_GRID_COLUMNS = 2
MIN_TAIL_TOKENS = 3

VALID_FLOWS = ("SFOW", "SFOE", "OAKE", "SJCE", "SMFS", "SMFN", "RNOS", "RNON")
SECTOR_NAMES = frozenset(
    {
        "Boulder",
        "Cedar",
        "Elkhorn",
        "Foster",
        "Grove",
        "Laguna",
        "Licke",
        "Morgan",
        "Niles",
        "Nugget",
        "Paradise",
        "Richmond",
        "Seca",
        "Silver",
        "Sunol",
        "Sutro",
        "Toga",
        "Valley",
        "Woodside",
    }
)
ALIASES = {"Wine Country": "Napa CX"}
COMPLEX_NAMES = frozenset(
    {
        "Fresno",
        "Mather",
        "Modesto",
        "Monterey",
        "Napa",
        "Oakland",
        "Sacramento",
        "San Francisco",
        "San Jose",
        "Stockton",
        "Travis",
    }
)
SOP_NON_HANDOFF_PAGES = frozenset(
    {2, 6, 7, 8, 14, 15, 16, 17, 18, 41, 44, 80, 103, 124, 143, 144}
)
LOA_NON_HANDOFF_PAGES = frozenset({3, 4, 11, 25})
ROUTE_WORDS = frozenset({"RV", "Direct"})
CELL_DEST_ROUTE = "dest_route"
CELL_DESTINATION = "destination"
CELL_ROUTE = "route"

SOP_HANDOFF: ColumnSpec = (
    ("sector", ("SECTOR",)),
    ("dest", ("DEST/", "DEST/ROUTE")),
    ("aircraft", ("ACFT",)),
    ("altitude", ("ALT",)),
    ("info", ("HDG/", "HDG/INFO")),
)
_LOA_ROUTE = (
    ("route", ("Route",)),
    ("aircraft", ("ACFT", "ACF")),
    ("altitude", ("Altitude",)),
)
_LOA_REQUIREMENTS = ("restrictions", ("Requirements", "Requirement"))
LOA_ARRIVAL: ColumnSpec = (
    ("destination", ("Destination", "Destinatio")),
    *_LOA_ROUTE,
    ("handoff", ("Handoff",)),
    _LOA_REQUIREMENTS,
)
LOA_DEPARTURE: ColumnSpec = (("from", ("From",)), *_LOA_ROUTE, _LOA_REQUIREMENTS)
_GENERAL_BASE = (
    ("name", ("POSITION", "SECTOR")),
    ("radio", ("RADIO",)),
    ("frequency", ("FREQUENCY",)),
    ("symbol", ("SYMBOL",)),
)
GENERAL_WITH_COMBINE: ColumnSpec = (*_GENERAL_BASE, ("combines", ("COMBINES",)))
COMPLEX_TABLE: ColumnSpec = (("name", ("COMPLEX",)), ("airports", ("AIRPORTS",)))
FLOW_TABLE: ColumnSpec = (("name", ("FLOW/PLAN",)), ("definition", ("DEFINITION",)))

SOP_TITLE = re.compile(
    r"^(?P<sector>[A-Z][a-z]+)(?: (?P<flow>[A-Z0-9]+))? (?P<dir>Exit|Entry) Routes$"
)
LOA_TITLE = re.compile(r"^Table (?P<number>\d+-\d+)\b")
LOA_ARRIVAL_AREA = re.compile(r"From (?P<area>.+?) to NCT\b", re.IGNORECASE)
LOA_DEPARTURE_AREA = re.compile(r"From NCT to (?P<area>.+?\))", re.IGNORECASE)
SECTION_HEADING = re.compile(r"^(?P<major>\d)-(?P<minor>\d{1,2}) (?P<title>[A-Z].*)$")
TOC_TAIL = re.compile(r"(\.{2,}|\s\.)\s*\d*$")
AREA_HEADING = re.compile(r"^Section \d+\. (?P<area>.+?)(?: Procedures)?$")
PACP_HEADING = re.compile(
    r"^(?P<sector>[A-Z][a-z]+)(?: (?P<flow>[A-Z0-9]+))? Pre-Arranged Coordination "
    r"Procedures and Sector Responsibilities$"
)
PACP_LETTER = re.compile(r"^(?P<letter>[a-z]{1,2})\. (?P<text>.*)$")
FLOW_TOKEN = re.compile(r"(?:SFO|OAK|SJC|SMF|RNO)[A-Z0-9]+")
FLOW_WORD = re.compile(r"\b(?:SFO|OAK|SJC|SMF|RNO)[WESN]\b")
PAREN = re.compile(r"\(([^()]*)\)")
ITEM_SPLIT = re.compile(r"\s*(?:(?<!\d),|,(?!\d)|;|&)\s*(?:or\s+)?|\s+or\s+")
OR_SPLIT = re.compile(r"\s+or\s+")
AIRPORT_SHAPE = re.compile(r"^[A-Z][A-Z0-9]{2,3}$")
FIX_SHAPE = re.compile(r"^[A-Z][A-Z0-9]{2,4}$")
AIRWAY_SHAPE = re.compile(r"^[VJTQ]\d+$")
HEADING_SHAPE = re.compile(r"^\d{3}°$")
PROCEDURE_SHAPE = re.compile(r"^[A-Z][A-Z0-9]*(?:\.[A-Z][A-Z0-9]*)? (?:STAR|DP)$")
SECTION_FLOW = re.compile(
    r"^(?P<sector>\S+) - (?P<flow>(?:SFO|OAK|SJC|SMF|RNO)[A-Z0-9]+)$"
)
LABEL_TOKEN = re.compile(r"\([^()]*\)|[^\s/()]+")
DATE_WORD = re.compile(r"^\d{2}[A-Z]{3}\d{4}$")
SOP_VERSION = re.compile(r"^\d+\.\d+$")
LOA_VERSION = re.compile(r"^CHG\d+$")
NCT_LOA_CODE = re.compile(r"\b([A-Z]{3,}) \((Q[0-9A-Z]+)\)")
ZOA_LOA_CODE = re.compile(r"\b((?:Area|Pac) [A-Za-z]+) \((C\d+)\)\s+([\d.]+)")
TWO_ALTITUDES = re.compile(r"\b\d{1,2},\d{3}[\s/]+\d{1,2},?\d{3}\b")
AIRCRAFT_TOKEN = re.compile(r"\([^()]*\)|[^,\s]+")
WRAP_FRAGMENT = re.compile(r"^[A-Z]{1,2}$")
NO_LIMIT = float("inf")

_ALT = r"(?:\d{1,2},\d{3}|FL\s?\d{3}|\d{3})"
_FILED = r"(?:lower|higher) filed(?: altitude)?"
KNOWN_ALTITUDES = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        _ALT,
        rf"{_ALT} or {_FILED}",
        rf"(?:↓|↑|@)\s?{_ALT}(?: or {_FILED})?",
        rf"↓\s?{_ALT} or level at {_FILED}",
        rf"Level at {_ALT}",
        rf"(?:Cross|X) [A-Za-z0-9 ]+ @\s?{_ALT}(?: or {_FILED})?(?: \(if filed above {_ALT}\))?",
        rf"Cross [A-Za-z0-9 ]+ at or (?:above|below) {_ALT}",
        rf"(?:At or (?:above|below)|AOA) {_ALT}",
        r"Descend via",
        rf"Descend via except maintain {_ALT}",
        rf"Descend via or (?:(?:@\s?)?{_FILED}|↓\s?{_ALT})",
        r"At filed altitude",
        r"FDIO",
    )
)


class ExtractError(Exception):
    """A page or table can't be read; the message names where."""


def join_lines(lines: Iterable[str]) -> str:
    """Join wrapped lines with a space, or none after a hyphen broken before a lowercase word."""
    text = ""
    for line in lines:
        if text.endswith("-") and line[:1].islower():
            text += line
        else:
            text = f"{text} {line}".strip()
    return text


class Line(NamedTuple):
    """One visual line of words."""

    top: float
    bottom: float
    x0: float
    words: tuple[Word, ...]

    @property
    def text(self) -> str:
        return " ".join(word["text"] for word in self.words)


class Header(NamedTuple):
    """A table's header row: each logical column's anchor word."""

    anchors: dict[str, Word]

    @property
    def top(self) -> float:
        return min(word["top"] for word in self.anchors.values())

    @property
    def bottom(self) -> float:
        return max(word["bottom"] for word in self.anchors.values())


class Cell(NamedTuple):
    """A logical cell: the area between ruled lines inside one column band."""

    top: float
    bottom: float
    lines: tuple[str, ...]

    @property
    def text(self) -> str:
        return join_lines(self.lines)


class Band(NamedTuple):
    """One column's x-extent."""

    name: str
    x0: float
    x1: float


class Grid(NamedTuple):
    """A table reduced to logical rows, with what looked wrong in each."""

    rows: list[dict[str, Cell]]
    doubts: list[list[str]]
    bands: list[Band]
    bottom: float


class Parsed(NamedTuple):
    """A destination or route cell, split up."""

    items: list[str]
    qualifiers: list[str]
    flows: list[str]
    doubts: list[str]


class Origin(NamedTuple):
    """A LOA departure's From Airport/Sector cell, split up."""

    sectors: list[str]
    airports: list[str]
    qualifiers: list[str]
    flows: list[str]
    doubts: list[str]


class Heading(NamedTuple):
    """A numbered section heading and where it sits."""

    page: int
    top: float
    code: str
    title: str


class Label(NamedTuple):
    """One sector named by a table's sector cell."""

    name: str
    flows: list[str]
    notes: list[str]


class TableContext(NamedTuple):
    """Where a table sits in its document, for the fields every row repeats."""

    doc: str
    page: int
    index: int
    section: str
    title: str
    source: str


@dataclass
class Coverage:
    """How much of one document's handoff tables was consumed."""

    found: int = 0
    consumed: int = 0
    rows: int = 0
    doubted: int = 0
    unconsumed: list[str] = field(default_factory=list)

    def summary(self, doc: str) -> str:
        return (
            f"{doc}: tables found {self.found}, consumed {self.consumed}, "
            f"rows {self.rows}, rows with doubts {self.doubted}"
        )


class Result(NamedTuple):
    """The draft and how much of the documents it covers."""

    draft: dict[str, Any]
    coverage: dict[str, Coverage]


def _is_dark_rule(obj: dict[str, Any]) -> bool:
    """Tell a drawn table rule from a cell's shading: rules are thin and dark, shading is neither."""
    thickness = min(float(obj["width"]), float(obj["height"]))
    length = max(float(obj["width"]), float(obj["height"]))
    if thickness > MAX_RULE_THICKNESS or length < MIN_RULE_LENGTH:
        return False
    color = (
        obj["stroking_color"]
        if obj["object_type"] == "line"
        else obj["non_stroking_color"]
    )
    if color is None:
        return False
    channels = color if isinstance(color, (tuple, list)) else (color,)
    return all(float(channel) <= MAX_RULE_SHADE for channel in channels)


def capture_page(page: Any, number: int) -> Page:
    """Reduce one pdfplumber page to plain JSON: its words and ruled lines.

    Args:
        page: The pdfplumber page.
        number: Its 1-based page number.

    Returns:
        The page number, the words with positions, and the deduplicated ruled lines.
    """
    words = [
        {
            "text": word["text"],
            "x0": round(float(word["x0"]), 1),
            "x1": round(float(word["x1"]), 1),
            "top": round(float(word["top"]), 1),
            "bottom": round(float(word["bottom"]), 1),
        }
        for word in page.extract_words()
    ]
    horizontal: set[tuple[float, float, float]] = set()
    vertical: set[tuple[float, float, float]] = set()
    for rule in [*page.lines, *page.rects]:
        if not _is_dark_rule(rule):
            continue
        x0, x1, top, bottom = (
            round(float(rule[key]), 1) for key in ("x0", "x1", "top", "bottom")
        )
        if x1 - x0 >= bottom - top:
            horizontal.add((round((top + bottom) / 2, 1), x0, x1))
        else:
            vertical.add((round((x0 + x1) / 2, 1), top, bottom))
    return {
        "number": number,
        "words": words,
        "h_edges": [{"y": y, "x0": x0, "x1": x1} for y, x0, x1 in sorted(horizontal)],
        "v_edges": [
            {"x": x, "top": top, "bottom": bottom}
            for x, top, bottom in sorted(vertical)
        ],
    }


def capture_pdf(path: Path, numbers: list[int] | None = None) -> list[Page]:
    """Capture pages of a PDF; pdfplumber is imported here so nothing else needs it.

    Args:
        path: The PDF to read.
        numbers: The 1-based pages to capture, or None for all of them.

    Returns:
        The captured pages in the order asked for.
    """
    import pdfplumber

    with pdfplumber.open(path) as pdf:
        wanted = numbers if numbers is not None else list(range(1, len(pdf.pages) + 1))
        return [capture_page(pdf.pages[number - 1], number) for number in wanted]


def _center_y(word: Word) -> float:
    return (word["top"] + word["bottom"]) / 2


def _center_x(word: Word) -> float:
    return (word["x0"] + word["x1"]) / 2


def text_lines(words: list[Word]) -> list[Line]:
    """Group words into visual lines, top to bottom and left to right."""
    groups: list[list[Word]] = []
    for word in sorted(words, key=_center_y):
        if groups and abs(_center_y(word) - _center_y(groups[-1][0])) <= LINE_TOLERANCE:
            groups[-1].append(word)
        else:
            groups.append([word])
    lines = []
    for group in groups:
        ordered = tuple(sorted(group, key=lambda word: word["x0"]))
        lines.append(
            Line(
                top=min(word["top"] for word in ordered),
                bottom=max(word["bottom"] for word in ordered),
                x0=ordered[0]["x0"],
                words=ordered,
            )
        )
    return lines


def _next_anchor(
    words: list[Word], first: Word, previous: Word, tokens: tuple[str, ...]
) -> Word | None:
    candidates = [
        word
        for word in words
        if word["text"] in tokens
        and word["x0"] >= previous["x1"]
        and abs(_center_y(word) - _center_y(first)) <= HEADER_TOLERANCE
    ]
    return min(candidates, key=lambda word: word["x0"], default=None)


def find_headers(page: Page, spec: ColumnSpec) -> list[Header]:
    """Find each header row on a page that has every column of ``spec``, in order."""
    headers = []
    first_name, first_tokens = spec[0]
    for first in page["words"]:
        if first["text"] not in first_tokens:
            continue
        anchors = {first_name: first}
        previous = first
        for name, tokens in spec[1:]:
            anchor = _next_anchor(page["words"], first, previous, tokens)
            if anchor is None:
                break
            anchors[name] = previous = anchor
        if len(anchors) == len(spec):
            headers.append(Header(anchors))
    return sorted(headers, key=lambda header: header.top)


def _body_top(page: Page, header: Header) -> float:
    """Return the ruled line closing the header row: the next one below every anchor word."""
    first = next(iter(header.anchors.values()))
    below = [
        edge["y"]
        for edge in page["h_edges"]
        if edge["y"] >= header.bottom - 0.5
        and edge["x0"] <= _center_x(first) <= edge["x1"]
    ]
    if not below:
        raise ExtractError(f"p{page['number']}: no ruled line under the header row")
    return min(below)


def _rules_crossing(page: Page, y: float) -> list[float]:
    return [edge["x"] for edge in page["v_edges"] if edge["top"] <= y <= edge["bottom"]]


def _outer_borders(page: Page, header: Header, body_top: float) -> tuple[float, float]:
    """Return the table's left and right borders, read just below the header row."""
    crossing = _rules_crossing(page, body_top + LINE_TOLERANCE)
    anchors = list(header.anchors.values())
    lefts = [x for x in crossing if x < anchors[0]["x0"]]
    rights = [x for x in crossing if x > anchors[-1]["x1"]]
    if not lefts or not rights:
        raise ExtractError(
            f"p{page['number']}: no ruled border beside the first table row"
        )
    return max(lefts), min(rights)


def _body_bottom(page: Page, left: float, body_top: float, limit: float) -> float:
    """Follow the left border down from the header; where it stops, the table stops."""
    border = sorted(
        (edge["top"], edge["bottom"])
        for edge in page["v_edges"]
        if abs(edge["x"] - left) <= MAX_RULE_THICKNESS and edge["bottom"] > body_top
    )
    bottom = body_top
    for top, end in border:
        if top > bottom + BORDER_GAP:
            break
        bottom = max(bottom, end)
    return min(bottom, limit)


def _column_boundary(
    page: Page, span: tuple[float, float], gap: tuple[float, float]
) -> float:
    """Return the x of the longest vertical rule between two header words."""
    totals: dict[float, float] = {}
    for edge in page["v_edges"]:
        if not gap[0] - 1 <= edge["x"] <= gap[1] + 1:
            continue
        overlap = min(edge["bottom"], span[1]) - max(edge["top"], span[0])
        if overlap > 0:
            key = next(
                (x for x in totals if abs(x - edge["x"]) <= MAX_RULE_THICKNESS),
                edge["x"],
            )
            totals[key] = totals.get(key, 0.0) + overlap
    if not totals:
        raise ExtractError(
            f"p{page['number']}: no column rule between x={gap[0]} and x={gap[1]}"
        )
    return max(totals, key=lambda x: totals[x])


def _column_bands(
    page: Page, header: Header, borders: tuple[float, float], span: tuple[float, float]
) -> list[Band]:
    names = list(header.anchors)
    anchors = list(header.anchors.values())
    cuts = [
        _column_boundary(page, span, (before["x1"], after["x0"]))
        for before, after in pairwise(anchors)
    ]
    edges = [borders[0], *cuts, borders[1]]
    return [
        Band(name, edges[index], edges[index + 1]) for index, name in enumerate(names)
    ]


def _cluster_rules(
    page: Page, span: tuple[float, float]
) -> dict[float, list[dict[str, float]]]:
    """Group the horizontal rules strictly inside ``span`` by y, within a small tolerance."""
    rules = sorted(
        (
            edge
            for edge in page["h_edges"]
            if span[0] + EDGE_TOLERANCE < edge["y"] < span[1] - EDGE_TOLERANCE
        ),
        key=lambda edge: edge["y"],
    )
    clusters: dict[float, list[dict[str, float]]] = {}
    anchor = None
    for rule in rules:
        if anchor is None or rule["y"] - anchor > EDGE_TOLERANCE:
            anchor = rule["y"]
            clusters[anchor] = []
        clusters[anchor].append(rule)
    return clusters


def _covers_band(rules: list[dict[str, float]], band: Band) -> bool:
    covered = sum(
        max(0.0, min(rule["x1"], band.x1) - max(rule["x0"], band.x0)) for rule in rules
    )
    return covered >= MIN_BAND_COVERAGE * (band.x1 - band.x0)


def _band_cells(words: list[Word], band: Band, splits: list[float]) -> list[Cell]:
    in_band = [word for word in words if band.x0 <= _center_x(word) < band.x1]
    cells = []
    for top, bottom in pairwise(splits):
        inside = [word for word in in_band if top <= _center_y(word) < bottom]
        cells.append(Cell(top, bottom, tuple(line.text for line in text_lines(inside))))
    return cells


def _crosses_column(word: Word, cuts: list[float]) -> bool:
    low, high = word["x0"] + CROSSING_MARGIN, word["x1"] - CROSSING_MARGIN
    return any(low < cut < high for cut in cuts)


def _crosses_row(word: Word, splits: list[float]) -> bool:
    low, high = word["top"] + CROSSING_MARGIN, word["bottom"] - CROSSING_MARGIN
    return any(low < y < high for y in splits)


def _band_of(word: Word, bands: list[Band]) -> Band | None:
    center = _center_x(word)
    return next((band for band in bands if band.x0 <= center < band.x1), None)


def _word_doubts(
    words: list[Word], bands: list[Band], band_splits: dict[str, list[float]]
) -> list[tuple[float, str]]:
    """Report words that cross a ruled line, as (y, doubt)."""
    doubts = []
    cuts = [band.x1 for band in bands[:-1]]
    for word in words:
        if _crosses_column(word, cuts):
            doubts.append(
                (_center_y(word), f"word {word['text']!r} crosses a column line")
            )
        band = _band_of(word, bands)
        if band is not None and _crosses_row(word, band_splits[band.name]):
            doubts.append(
                (_center_y(word), f"word {word['text']!r} crosses a row line")
            )
    return doubts


def _overlaps_table(
    word: Word, borders: tuple[float, float], span: tuple[float, float]
) -> bool:
    across = (
        word["x1"] > borders[0] + CROSSING_MARGIN
        and word["x0"] < borders[1] - CROSSING_MARGIN
    )
    down = (
        word["bottom"] > span[0] + CROSSING_MARGIN
        and word["top"] < span[1] - CROSSING_MARGIN
    )
    return across and down


def _in_a_cell(
    word: Word, borders: tuple[float, float], ranges: list[tuple[float, float]]
) -> bool:
    if not borders[0] <= _center_x(word) <= borders[1]:
        return False
    return any(top <= _center_y(word) < end for top, end in ranges)


def _stray_word_doubts(
    page: Page,
    borders: tuple[float, float],
    span: tuple[float, float],
    ranges: list[tuple[float, float]],
) -> list[tuple[float, str]]:
    """Report words overlapping the table that no logical cell holds, as (y, doubt)."""
    return [
        (_center_y(word), f"word {word['text']!r} landed in no cell")
        for word in page["words"]
        if _overlaps_table(word, borders, span)
        and not _in_a_cell(word, borders, ranges)
    ]


def _attach_doubts(
    ranges: list[tuple[float, float]], located: list[tuple[float, str]]
) -> list[list[str]]:
    """Give each located doubt to the row holding its y, or else the nearest row."""
    doubts: list[list[str]] = [[] for _ in ranges]
    for y, doubt in located:
        nearest = min(
            range(len(ranges)),
            key=lambda i: (
                0.0 if ranges[i][0] <= y < ranges[i][1] else abs(ranges[i][0] - y)
            ),
        )
        doubts[nearest].append(doubt)
    return doubts


def _band_splits(
    page: Page, bands: list[Band], span: tuple[float, float]
) -> dict[str, list[float]]:
    clusters = _cluster_rules(page, span)
    return {
        band.name: [y for y, rules in clusters.items() if _covers_band(rules, band)]
        for band in bands
    }


def _words_inside(
    page: Page, borders: tuple[float, float], span: tuple[float, float]
) -> list[Word]:
    return [
        word
        for word in page["words"]
        if borders[0] <= _center_x(word) <= borders[1]
        and span[0] <= _center_y(word) <= span[1]
    ]


def _row_ranges(
    band_splits: dict[str, list[float]], span: tuple[float, float]
) -> list[tuple[float, float]]:
    """Return the finest partition of the table's height across all column bands."""
    cuts = sorted({*span, *(y for splits in band_splits.values() for y in splits)})
    return [(top, end) for top, end in pairwise(cuts) if end - top >= MIN_ROW_HEIGHT]


def _logical_row(
    cells: dict[str, list[Cell]], row: tuple[float, float]
) -> dict[str, Cell]:
    middle = (row[0] + row[1]) / 2
    return {
        name: next(cell for cell in column if cell.top <= middle < cell.bottom)
        for name, column in cells.items()
    }


def build_grid(page: Page, header: Header, limit: float) -> Grid:
    """Turn a located table into logical rows, by the ruled lines inside each column band.

    Each band is split only by horizontal rules crossing it. A logical row is the finest
    partition across the bands, so a cell spanning several rows fills all of them.

    Args:
        page: The captured page.
        header: The table's header row.
        limit: The y the table can't extend past, such as the next table's header.

    Returns:
        The logical rows and the doubts found while placing words.

    Raises:
        ExtractError: The ruled lines around the table can't be found.
    """
    body_top = _body_top(page, header)
    borders = _outer_borders(page, header, body_top)
    bottom = _body_bottom(page, borders[0], body_top, limit)
    span = (body_top, bottom)
    bands = _column_bands(page, header, borders, span)
    band_splits = _band_splits(page, bands, span)
    words = _words_inside(page, borders, span)
    ranges = _row_ranges(band_splits, span)
    if not ranges:
        raise ExtractError(
            f"p{page['number']}: the table has no rows between its ruled lines"
        )
    cells = {
        band.name: _band_cells(words, band, [body_top, *band_splits[band.name], bottom])
        for band in bands
    }
    rows = [_logical_row(cells, row) for row in ranges]
    located = [
        *_word_doubts(words, bands, band_splits),
        *_stray_word_doubts(page, borders, span, ranges),
    ]
    return Grid(rows, _attach_doubts(ranges, located), bands, bottom)


def _stop_below(page: Page, bottom: float, limit: float) -> float:
    """Return the y of the first title or heading under a table, within ``limit``."""
    for line in text_lines(page["words"]):
        if line.top > bottom and _is_title_or_heading(line.text):
            return min(line.top, limit)
    return limit


def _is_title_or_heading(text: str) -> bool:
    patterns = (SOP_TITLE, LOA_TITLE, SECTION_HEADING, PACP_HEADING)
    return any(pattern.match(text) for pattern in patterns)


def _handoff_grid(page: Page, header: Header, limit: float) -> Grid:
    """Build a handoff table's grid, refusing one whose left border stopped above more rows."""
    grid = build_grid(page, header, limit)
    clusters = _cluster_rules(
        page, (grid.bottom, _stop_below(page, grid.bottom, limit))
    )
    for y, rules in clusters.items():
        crossed = sum(1 for band in grid.bands if _covers_band(rules, band))
        if crossed >= MIN_GRID_COLUMNS:
            raise ExtractError(
                f"p{page['number']}: a ruled row at y={y} sits below where the table's "
                "left border stops, so its rows would be lost"
            )
    return grid


def _nearest_title(lines: list[Line], header: Header) -> str:
    above = [
        line
        for line in lines
        if line.bottom <= header.top + 1 and header.top - line.bottom <= TITLE_REACH
    ]
    return above[-1].text if above else ""


def _flow_tokens(text: str) -> list[str] | None:
    """Return the flows a parenthesised text names, or None when it isn't a flow list."""
    tokens = [
        token for token in re.split(r"\s*[/,]\s*|\s+and\s+", text.strip()) if token
    ]
    if tokens and all(FLOW_TOKEN.fullmatch(token) for token in tokens):
        return tokens
    return None


def _is_route_token(token: str) -> bool:
    shapes = (FIX_SHAPE, AIRWAY_SHAPE, HEADING_SHAPE)
    return token in ROUTE_WORDS or any(shape.match(token) for shape in shapes)


def _is_recognisable(item: str) -> bool:
    """Tell whether an item is an airport, fix, airway, complex, procedure or route phrase."""
    if item.endswith(" CX") and item[:-3] in COMPLEX_NAMES:
        return True
    if PROCEDURE_SHAPE.match(item) or item.title() in ALIASES:
        return True
    return all(_is_route_token(token) for token in item.split())


def _distribute_shared_cx(items: list[str]) -> list[str]:
    """Spread a shared ``CX``: ``Modesto``, ``Stockton CX`` means both are complexes."""
    if not any(item.endswith(" CX") for item in items):
        return items
    return [f"{item} CX" if item in COMPLEX_NAMES else item for item in items]


def _airport_list(item: str) -> list[str]:
    """Split a destination item on spaces when every token is airport-shaped."""
    tokens = item.split()
    if all(AIRPORT_SHAPE.match(token) for token in tokens):
        return tokens
    return [item]


def _candidate_items(whole: str, kind: str) -> list[str]:
    pattern = OR_SPLIT if kind == CELL_ROUTE else ITEM_SPLIT
    items = _distribute_shared_cx([item for item in pattern.split(whole) if item])
    if kind != CELL_DESTINATION:
        return items
    return [part for item in items for part in _airport_list(item)]


def _or_scope_doubts(whole: str, items: list[str]) -> list[str]:
    """Flag an ``or`` between one token and three or more, which may share a route tail."""
    if not OR_SPLIT.search(whole):
        return []
    lengths = [len(item.split()) for item in items]
    if 1 in lengths and max(lengths) >= MIN_TAIL_TOKENS:
        return [f"or scope: {whole!r} may share a route tail"]
    return []


def split_items(text: str, kind: str) -> tuple[list[str], list[str]]:
    """Split a cell into items only when every item is recognisable.

    Args:
        text: The cell text, without its parentheses.
        kind: ``CELL_DEST_ROUTE`` for the SOP's column, ``CELL_DESTINATION`` for a LOA
            Destination, where a space can mean a list, or ``CELL_ROUTE`` for a LOA Route,
            where a space is a sequence and only `` or `` separates.

    Returns:
        The items, and a doubt when the cell stayed whole or an ``or`` has unclear scope.
    """
    whole = " ".join(text.split())
    if not whole:
        return [], []
    items = _candidate_items(whole, kind)
    unknown = [item for item in items if not _is_recognisable(item)]
    if unknown:
        reason = f"{unknown[0]!r} isn't a recognisable destination or route"
        return [whole], [f"unsplit: {reason}"]
    return items, _or_scope_doubts(whole, items)


def _flow_mid_cell_doubts(text: str) -> list[str]:
    """Flag text after a flow in a destination, since the flow may or may not cover it."""
    return [
        f"text follows flow ({match[1]}) in {' '.join(text.split())!r}"
        for match in PAREN.finditer(text)
        if _flow_tokens(match[1]) and text[match.end() :].strip()
    ]


def parse_cell(text: str, kind: str) -> Parsed:
    """Split a destination or route cell into items, moving parenthesised text out."""
    qualifiers: list[str] = []
    flows: list[str] = []
    for inner in PAREN.findall(text):
        tokens = _flow_tokens(inner)
        if tokens is None:
            qualifiers.append(inner.strip())
        else:
            flows.extend(tokens)
    items, doubts = split_items(PAREN.sub(" ", text), kind)
    if kind == CELL_DESTINATION:
        doubts = [*_flow_mid_cell_doubts(text), *doubts]
    return Parsed(items, qualifiers, flows, doubts)


def _add_label_note(labels: list[Label], token: str) -> None:
    if not labels:
        labels.append(Label("", [], []))
    inner = token[1:-1].strip()
    flows = _flow_tokens(inner)
    if flows is None:
        labels[-1].notes.append(inner)
    else:
        labels[-1].flows.extend(flows)


def _starts_label(labels: list[Label], token: str) -> bool:
    return token in SECTOR_NAMES or not labels or labels[-1].name in SECTOR_NAMES


def parse_label(text: str) -> list[Label]:
    """Read the sectors a sector cell names, each with its own flows and notes."""
    labels: list[Label] = []
    for token in LABEL_TOKEN.findall(text):
        if token.startswith("("):
            _add_label_note(labels, token)
        elif _starts_label(labels, token):
            labels.append(Label(token, [], []))
        else:
            labels[-1] = labels[-1]._replace(name=f"{labels[-1].name} {token}")
    return labels or [Label("", [], [])]


def _leading_sectors(tokens: list[str]) -> tuple[list[str], list[str]]:
    """Take the known sector names a token list opens with, ``MORGAN/SECA`` counting as two."""
    sectors: list[str] = []
    for index, token in enumerate(tokens):
        names = [part.title() for part in token.split("/")]
        if not all(name in SECTOR_NAMES for name in names):
            return sectors, tokens[index:]
        sectors.extend(names)
    return sectors, []


def _leading_airports(tokens: list[str]) -> tuple[list[str], list[str]]:
    """Take the airport-shaped tokens a token list opens with."""
    airports: list[str] = []
    for index, token in enumerate(tokens):
        if not AIRPORT_SHAPE.match(token) or token.title() in SECTOR_NAMES:
            return airports, tokens[index:]
        airports.append(token)
    return airports, []


def parse_origin(text: str) -> Origin:
    """Read a LOA departure's From Airport/Sector cell into sectors or airports.

    The text after the names stays as a qualifier: on the page it can decide the altitude.
    """
    flows = [
        flow for inner in PAREN.findall(text) for flow in _flow_tokens(inner) or []
    ]
    bare = " ".join(
        PAREN.sub(lambda m: " " if _flow_tokens(m[1]) else m[0], text).split()
    )
    tokens = bare.split()
    sectors, rest = _leading_sectors(tokens)
    if sectors:
        return Origin(sectors, [], _tail_qualifier(rest), flows, [])
    airports, rest = _leading_airports(tokens)
    if airports:
        return Origin([""], airports, _tail_qualifier(rest), flows, [])
    if not bare:
        return Origin([""], [], [], flows, ["row lists no origin"])
    doubt = f"origin {bare!r} names no known sector or airport"
    return Origin([""], [], [bare], flows, [doubt])


def _tail_qualifier(tokens: list[str]) -> list[str]:
    return [" ".join(tokens)] if tokens else []


def parse_aircraft(text: str) -> tuple[list[str], list[str]]:
    """Split an aircraft class cell; return the classes and any doubts."""
    classes = AIRCRAFT_TOKEN.findall(text)
    if not classes:
        return [], ["row lists no aircraft class"]
    return classes, [
        f"aircraft class {token!r} isn't P, T or J"
        for token in classes
        if token not in ("P", "T", "J")
    ]


def altitude_doubts(text: str) -> list[str]:
    """Report what looks wrong with an altitude cell."""
    if not text:
        return ["row lists no altitude"]
    if TWO_ALTITUDES.search(text):
        return [f"two altitudes in one cell: {text!r}"]
    if any(pattern.fullmatch(text) for pattern in KNOWN_ALTITUDES):
        return []
    return [f"altitude matches no known form: {text!r}"]


def rejoin_broken_word(cell: Cell) -> tuple[str, list[str]]:
    """Read a narrow cell, gluing back a word it broke across lines (``MORGA`` / ``N``)."""
    text = ""
    doubts = []
    for line in cell.lines:
        if text and WRAP_FRAGMENT.match(line):
            doubts.append(
                f"rejoined a word broken across lines: {text.split()[-1]}{line}"
            )
            text += line
        else:
            text = join_lines((text, line))
    return text, doubts


def handoff_sector(text: str) -> tuple[str, list[str]]:
    """Title-case a Handoff To cell outside its parentheses; flag anything but one sector."""
    name = " ".join(
        token if token.startswith("(") else token.title()
        for token in LABEL_TOKEN.findall(text)
    )
    if name and name not in SECTOR_NAMES:
        return name, [f"handoff {name!r} isn't one known sector"]
    return name, []


def paren_doubts(text: str) -> list[str]:
    """Flag parentheses that don't pair up, since their text stays in the item."""
    return (
        [f"unbalanced parenthesis in {text!r}"]
        if text.count("(") != text.count(")")
        else []
    )


def flow_doubts(flows: list[str]) -> list[str]:
    return [
        f"flow {flow!r} isn't one of the eight valid flows"
        for flow in flows
        if flow not in VALID_FLOWS
    ]


def _column_flow_doubts(column: str, cell_text: str) -> list[str]:
    return [
        f"flow {flow!r} in the {column} column" for flow in FLOW_WORD.findall(cell_text)
    ]


def _make_row(context: TableContext, direction: str, index: int, **fields: Any) -> Row:
    row: Row = {
        "id": f"{context.doc.lower()}-p{context.page}-t{context.index}-r{index}",
        "doc": context.doc,
        "page": context.page,
        "section": context.section,
        "table": context.title,
        "direction": direction,
        "from": fields["from_"],
        "to": fields["to"],
        "from_airports": fields.get("from_airports", []),
        "table_flows": fields.get("table_flows", []),
        "flows": fields["flows"],
        "dest_or_route": fields["dest_or_route"],
        "route": fields.get("route", []),
        "qualifiers": fields["qualifiers"],
        "aircraft": fields["aircraft"],
        "altitude": fields["altitude"],
        "info": fields.get("info", ""),
        "restrictions": fields.get("restrictions", ""),
        "source": context.source,
        "doubts": fields["doubts"],
    }
    return row


def _sector_doubts(label: Label) -> list[str]:
    if not label.name:
        return ["row lists no sector"]
    return (
        []
        if label.name in SECTOR_NAMES
        else [f"sector label {label.name!r} isn't a known sector"]
    )


def _sop_label_row(
    context: TableContext,
    title: re.Match[str],
    label: Label,
    cells: dict[str, Cell],
    base_doubts: list[str],
    *,
    index: int,
) -> Row:
    dest = parse_cell(cells["dest"].text, CELL_DEST_ROUTE)
    aircraft, aircraft_doubts = parse_aircraft(cells["aircraft"].text)
    altitude = cells["altitude"].text
    info = cells["info"].text
    table_flows = [title["flow"]] if title["flow"] else []
    flows = list(dict.fromkeys([*label.flows, *dest.flows]))
    doubts = [
        *base_doubts,
        *flow_doubts([*table_flows, *flows]),
        *_sector_doubts(label),
        *[f"sector label note: {note!r}" for note in label.notes],
        *([] if dest.items else ["row lists no destination or route"]),
        *dest.doubts,
        *paren_doubts(cells["dest"].text),
        *aircraft_doubts,
        *altitude_doubts(altitude),
        *_column_flow_doubts("route", cells["dest"].text),
        *_column_flow_doubts("info", info),
    ]
    table_sector = title["sector"]
    is_exit = title["dir"] == "Exit"
    return _make_row(
        context,
        title["dir"].lower(),
        index,
        from_=table_sector if is_exit else label.name,
        to=label.name if is_exit else table_sector,
        table_flows=table_flows,
        flows=flows,
        dest_or_route=dest.items,
        qualifiers=[*label.notes, *dest.qualifiers],
        aircraft=aircraft,
        altitude=altitude,
        info=info,
        doubts=doubts,
    )


def sop_rows(context: TableContext, title: re.Match[str], grid: Grid) -> list[Row]:
    """Build the rows of one SOP exit or entry table, one per sector named in each label."""
    rows: list[Row] = []
    for cells, doubts in zip(grid.rows, grid.doubts):
        for label in parse_label(cells["sector"].text):
            rows.append(
                _sop_label_row(context, title, label, cells, doubts, index=len(rows))
            )
    return rows


def _loa_row_common(
    cells: dict[str, Cell], base_doubts: list[str]
) -> tuple[dict[str, Any], list[str]]:
    aircraft, aircraft_doubts = parse_aircraft(cells["aircraft"].text)
    altitude = cells["altitude"].text
    restrictions = cells["restrictions"].text
    doubts = [
        *base_doubts,
        *aircraft_doubts,
        *altitude_doubts(altitude),
        *_column_flow_doubts("requirements", restrictions),
    ]
    return {
        "aircraft": aircraft,
        "altitude": altitude,
        "restrictions": restrictions,
    }, doubts


def _loa_arrival_row(
    context: TableContext,
    area: str,
    cells: dict[str, Cell],
    base_doubts: list[str],
    index: int,
) -> Row:
    common, doubts = _loa_row_common(cells, base_doubts)
    dest_text, broken_dest = rejoin_broken_word(cells["destination"])
    handoff_text, broken_handoff = rejoin_broken_word(cells["handoff"])
    handoff, handoff_doubts = handoff_sector(handoff_text)
    dest = parse_cell(dest_text, CELL_DESTINATION)
    route = parse_cell(cells["route"].text, CELL_ROUTE)
    doubts += [
        *dest.doubts,
        *route.doubts,
        *broken_dest,
        *broken_handoff,
        *handoff_doubts,
        *flow_doubts(dest.flows),
        *_column_flow_doubts("route", cells["route"].text),
        *([] if dest.items else ["row lists no destination"]),
        *([] if route.items else ["row lists no route"]),
    ]
    return _make_row(
        context,
        "loa_arrival",
        index,
        from_=area,
        to=handoff,
        flows=dest.flows,
        dest_or_route=dest.items,
        route=route.items,
        qualifiers=[*dest.qualifiers, *route.qualifiers],
        doubts=doubts,
        **common,
    )


def _loa_departure_rows(
    context: TableContext,
    area: str,
    cells: dict[str, Cell],
    base_doubts: list[str],
    index: int,
) -> list[Row]:
    """Build one departure row per sector the From Airport/Sector cell names."""
    common, doubts = _loa_row_common(cells, base_doubts)
    origin_text, broken_origin = rejoin_broken_word(cells["from"])
    origin = parse_origin(origin_text)
    route = parse_cell(cells["route"].text, CELL_ROUTE)
    doubts += [
        *origin.doubts,
        *route.doubts,
        *broken_origin,
        *flow_doubts(origin.flows),
        *_column_flow_doubts("route", cells["route"].text),
        *([] if route.items else ["row lists no route"]),
    ]
    return [
        _make_row(
            context,
            "loa_departure",
            index + offset,
            from_=sector,
            to=area,
            from_airports=origin.airports,
            flows=origin.flows,
            dest_or_route=route.items,
            qualifiers=[*origin.qualifiers, *route.qualifiers],
            doubts=doubts,
            **common,
        )
        for offset, sector in enumerate(origin.sectors)
    ]


def loa_rows(context: TableContext, spec: ColumnSpec, grid: Grid) -> list[Row]:
    """Build the rows of one LOA Attachment 3 table.

    Raises:
        ExtractError: The title doesn't name the ZOA area.
    """
    is_arrival = spec is LOA_ARRIVAL
    match = (LOA_ARRIVAL_AREA if is_arrival else LOA_DEPARTURE_AREA).search(
        context.title
    )
    if match is None:
        raise ExtractError(
            f"LOA p{context.page}: title {context.title!r} names no ZOA area"
        )
    rows: list[Row] = []
    for cells, doubts in zip(grid.rows, grid.doubts):
        if is_arrival:
            rows.append(
                _loa_arrival_row(context, match["area"], cells, doubts, len(rows))
            )
        else:
            rows.extend(
                _loa_departure_rows(context, match["area"], cells, doubts, len(rows))
            )
    return rows


def _is_toc_line(text: str) -> bool:
    return bool(TOC_TAIL.search(text))


def section_headings(pages: list[Page]) -> list[Heading]:
    """List the ``N-M Title`` headings in document order, skipping the table of contents.

    A heading must follow the last one found, which rejects a body line that happens to
    start like one.
    """
    headings: list[Heading] = []
    last = (0, 0)
    for page in pages:
        for line in text_lines(page["words"]):
            match = SECTION_HEADING.match(line.text)
            if match is None or _is_toc_line(line.text):
                continue
            order = (int(match["major"]), int(match["minor"]))
            if order > last:
                last = order
                code = f"{order[0]}-{order[1]}"
                headings.append(Heading(page["number"], line.top, code, match["title"]))
    return headings


def heading_at(headings: list[Heading], page: int, top: float) -> Heading | None:
    """Return the heading in force at a position, or None before the first."""
    current = None
    for heading in headings:
        if (heading.page, heading.top) > (page, top):
            break
        current = heading
    return current


def _sop_table(
    page: Page,
    header: Header,
    lines: list[Line],
    *,
    index: int,
    headings: list[Heading],
    limit: float,
) -> list[Row]:
    title_text = _nearest_title(lines, header)
    title = SOP_TITLE.fullmatch(title_text)
    if title is None:
        raise ExtractError(
            f"SOP p{page['number']}: the text above the table, {title_text!r}, isn't an exit or entry title"
        )
    heading = heading_at(headings, page["number"], header.top)
    if heading is None:
        raise ExtractError(
            f"SOP p{page['number']}: the table {title_text!r} comes before any section heading"
        )
    section = heading.code
    context = TableContext(
        "SOP",
        page["number"],
        index,
        section,
        title_text,
        f"SOP §{section} p{page['number']}",
    )
    return sop_rows(context, title, _handoff_grid(page, header, limit))


def _loa_table(
    page: Page,
    header: Header,
    spec: ColumnSpec,
    lines: list[Line],
    *,
    index: int,
    limit: float,
) -> list[Row]:
    title_text = _nearest_title(lines, header)
    title = LOA_TITLE.match(title_text)
    if title is None:
        raise ExtractError(
            f"LOA p{page['number']}: the text above the table, {title_text!r}, isn't a table title"
        )
    number = title["number"]
    context = TableContext(
        "LOA",
        page["number"],
        index,
        number,
        title_text,
        f"LOA Table {number} p{page['number']}",
    )
    return loa_rows(context, spec, _handoff_grid(page, header, limit))


def _record(coverage: Coverage, table_rows: list[Row]) -> None:
    coverage.consumed += 1
    coverage.rows += len(table_rows)
    coverage.doubted += sum(1 for row in table_rows if row["doubts"])


def _titles_without_tables(
    page: Page, lines: list[Line], tops: list[float], title_pattern: re.Pattern[str]
) -> list[str]:
    """Name each table title with neither a table below it nor ``Reserved.``."""
    missing = []
    for index, line in enumerate(lines):
        if not title_pattern.match(line.text):
            continue
        reserved = index + 1 < len(lines) and lines[index + 1].text.startswith(
            "Reserved"
        )
        has_table = any(0 <= top - line.bottom <= TITLE_REACH for top in tops)
        if not reserved and not has_table:
            missing.append(
                f"p{page['number']}: title {line.text!r} has no table below it"
            )
    return missing


def _touches(horizontal: dict[str, float], vertical: dict[str, float]) -> bool:
    margin = MAX_RULE_THICKNESS
    across = horizontal["x0"] - margin <= vertical["x"] <= horizontal["x1"] + margin
    down = vertical["top"] - margin <= horizontal["y"] <= vertical["bottom"] + margin
    return across and down


def _partition(
    rules: list[dict[str, float]], test: Callable[[dict[str, float]], bool]
) -> tuple[list[dict[str, float]], list[dict[str, float]]]:
    hit = [rule for rule in rules if test(rule)]
    miss = [rule for rule in rules if not test(rule)]
    return hit, miss


def _take_joined(
    vertical: dict[str, float], pools: dict[str, list[dict[str, float]]]
) -> list[dict[str, float]]:
    """Remove and return the vertical rules joined to this one through a horizontal rule."""
    touching, pools["h"] = _partition(pools["h"], lambda rule: _touches(rule, vertical))
    joined, pools["v"] = _partition(
        pools["v"], lambda other: any(_touches(rule, other) for rule in touching)
    )
    return joined


def _connected_verticals(page: Page) -> list[list[dict[str, float]]]:
    """Group the vertical rules joined to each other through horizontal rules."""
    pools = {"h": list(page["h_edges"]), "v": list(page["v_edges"])}
    groups = []
    while pools["v"]:
        stack = [pools["v"].pop()]
        group = []
        while stack:
            vertical = stack.pop()
            group.append(vertical)
            stack.extend(_take_joined(vertical, pools))
        groups.append(group)
    return groups


def _grid_columns(group: list[dict[str, float]]) -> int:
    """Count the columns a group of vertical rules bounds."""
    xs = sorted(rule["x"] for rule in group)
    lines = 1 + sum(1 for a, b in pairwise(xs) if b - a > MAX_RULE_THICKNESS)
    return lines - 1


def _is_inside_table(
    group: list[dict[str, float]], spans: list[tuple[float, float]]
) -> bool:
    top = min(rule["top"] for rule in group)
    bottom = max(rule["bottom"] for rule in group)
    reach = HEADER_REACH
    return any(top <= end + reach and bottom >= start - reach for start, end in spans)


def _unrecognised_grids(
    page: Page, spans: list[tuple[float, float]], listed: frozenset[int], constant: str
) -> list[str]:
    """Name each ruled grid of two or more columns outside every handoff table.

    A page holding only known non-handoff grids is listed per document, so a new document
    version with shifted pages fails for a person to look at.
    """
    if page["number"] in listed:
        return []
    return [
        f"p{page['number']}: a ruled grid at y={min(rule['top'] for rule in group)} isn't "
        f"a handoff table; check that page, and add it to {constant} if it holds no routes"
        for group in _connected_verticals(page)
        if _grid_columns(group) >= MIN_GRID_COLUMNS
        and not _is_inside_table(group, spans)
    ]


def _table_span(page: Page, header: Header, limit: float) -> tuple[float, float]:
    """Return a table's height, or just its header's when its borders can't be read."""
    try:
        body_top = _body_top(page, header)
        left, _ = _outer_borders(page, header, body_top)
    except ExtractError:
        return header.top, header.bottom
    return header.top, _body_bottom(page, left, body_top, limit)


def _table_spans(page: Page, headers: list[Header]) -> list[tuple[float, float]]:
    limits = [*[header.top for header in headers[1:]], NO_LIMIT]
    return [_table_span(page, header, limit) for header, limit in zip(headers, limits)]


def _page_problems(
    page: Page,
    lines: list[Line],
    headers: list[Header],
    checks: tuple[re.Pattern[str], frozenset[int], str],
) -> list[str]:
    title_pattern, listed, constant = checks
    tops = [header.top for header in headers]
    return [
        *_titles_without_tables(page, lines, tops, title_pattern),
        *_unrecognised_grids(page, _table_spans(page, headers), listed, constant),
    ]


def _consume_tables(
    page: Page,
    located: list[tuple[Header, ColumnSpec]],
    build: Callable[..., list[Row]],
    coverage: Coverage,
) -> list[Row]:
    """Build each located table, recording a failed one instead of stopping at it."""
    rows: list[Row] = []
    coverage.found += len(located)
    tops = [header.top for header, _ in located]
    for index, (header, spec) in enumerate(located):
        limit = tops[index + 1] if index + 1 < len(tops) else NO_LIMIT
        try:
            table = build(header, spec, index, limit)
        except ExtractError as error:
            coverage.unconsumed.append(f"p{page['number']} table {index}: {error}")
            continue
        _record(coverage, table)
        rows.extend(table)
    return rows


def _sop_page_rows(
    page: Page, headings: list[Heading], coverage: Coverage
) -> list[Row]:
    lines = text_lines(page["words"])
    located = [(header, SOP_HANDOFF) for header in find_headers(page, SOP_HANDOFF)]

    def build(header: Header, _: ColumnSpec, index: int, limit: float) -> list[Row]:
        return _sop_table(
            page, header, lines, index=index, headings=headings, limit=limit
        )

    rows = _consume_tables(page, located, build, coverage)
    checks = (SOP_TITLE, SOP_NON_HANDOFF_PAGES, "SOP_NON_HANDOFF_PAGES")
    headers = [header for header, _ in located]
    coverage.unconsumed.extend(_page_problems(page, lines, headers, checks))
    return rows


def _loa_page_rows(page: Page, coverage: Coverage) -> list[Row]:
    lines = text_lines(page["words"])
    located = sorted(
        (
            (header, spec)
            for spec in (LOA_ARRIVAL, LOA_DEPARTURE)
            for header in find_headers(page, spec)
        ),
        key=lambda pair: pair[0].top,
    )

    def build(header: Header, spec: ColumnSpec, index: int, limit: float) -> list[Row]:
        return _loa_table(page, header, spec, lines, index=index, limit=limit)

    rows = _consume_tables(page, located, build, coverage)
    checks = (LOA_TITLE, LOA_NON_HANDOFF_PAGES, "LOA_NON_HANDOFF_PAGES")
    headers = [header for header, _ in located]
    coverage.unconsumed.extend(_page_problems(page, lines, headers, checks))
    return rows


def read_source(
    doc: str, pages: list[Page], version_pattern: re.Pattern[str]
) -> dict[str, str]:
    """Read the last row of a document's List of Changes table.

    Raises:
        ExtractError: No such row can be read; the message names the document.
    """
    for page in pages:
        lines = text_lines(page["words"])
        if not any(line.text.endswith("List of Changes") for line in lines):
            continue
        pairs = [_version_pair(line, version_pattern) for line in lines]
        found = [pair for pair in pairs if pair is not None]
        if found:
            version, date = found[-1]
            return {"version": version, "date": date}
    raise ExtractError(
        f"{doc}: can't read the source version from its List of Changes table"
    )


def _version_pair(
    line: Line, version_pattern: re.Pattern[str]
) -> tuple[str, str] | None:
    versions = [
        word["text"] for word in line.words if version_pattern.match(word["text"])
    ]
    dates = [word["text"] for word in line.words if DATE_WORD.match(word["text"])]
    return (versions[0], dates[0]) if versions and dates else None


def _reference_grids(pages: list[Page], spec: ColumnSpec) -> list[tuple[Page, Grid]]:
    """Find every table with the given header across a document's pages."""
    grids = []
    for page in pages:
        for header in find_headers(page, spec):
            grids.append((page, build_grid(page, header, NO_LIMIT)))
    return grids


def extract_complexes(pages: list[Page]) -> dict[str, list[str]]:
    """Read the SOP §1-4 airport complex table."""
    complexes: dict[str, list[str]] = {}
    for _, grid in _reference_grids(pages, COMPLEX_TABLE):
        for cells in grid.rows:
            airports = [
                airport.strip() for airport in cells["airports"].text.split(",")
            ]
            complexes[cells["name"].text] = [airport for airport in airports if airport]
    return complexes


def extract_flows(pages: list[Page]) -> dict[str, list[str]]:
    """Read the SOP §1-6 flow table, name to definition lines."""
    flows: dict[str, list[str]] = {}
    for _, grid in _reference_grids(pages, FLOW_TABLE):
        for cells in grid.rows:
            flows[cells["name"].text] = list(cells["definition"].lines)
    return flows


def _area_at(pages: list[Page], number: int) -> str:
    """Return the ``Section N. <Area>`` name in force at a page."""
    area = ""
    for page in pages:
        if page["number"] > number:
            break
        for line in text_lines(page["words"]):
            match = AREA_HEADING.match(line.text)
            if match is not None and not _is_toc_line(line.text):
                area = match["area"]
    return area


def _sector_entry(cells: dict[str, Cell], area: str) -> dict[str, str]:
    combined, _, name = cells["name"].text.rpartition("/")
    combines = cells.get("combines")
    return {
        "name": name.strip(),
        "combined_position": combined.strip(),
        "area": area,
        "radio_callsign": cells["radio"].text,
        "frequency": cells["frequency"].text,
        "symbol": cells["symbol"].text,
        "combines_to": combines.text if combines is not None else "",
        "loa_code": "",
    }


def extract_sop_sectors(pages: list[Page]) -> list[dict[str, str]]:
    """Read the General Information tables, skipping the real-world sector attachment."""
    sectors = []
    for page in pages:
        headers = find_headers(page, GENERAL_WITH_COMBINE) or find_headers(
            page, _GENERAL_BASE
        )
        if not headers:
            continue
        area = _area_at(pages, page["number"])
        for header in headers:
            grid = build_grid(page, header, NO_LIMIT)
            sectors.extend(
                _sector_entry(cells, area) for cells in grid.rows if cells["name"].text
            )
    return sectors


def _is_loa_code_page(lines: list[str]) -> bool:
    return any("NCT SECTOR" in line and "ZOA SECTOR" in line for line in lines)


def _zoa_codes(line: str) -> list[dict[str, str]]:
    return [
        {"name": name, "code": code, "frequency": frequency}
        for name, code, frequency in ZOA_LOA_CODE.findall(line)
    ]


def extract_sectors(
    sop_pages: list[Page], loa_pages: list[Page]
) -> dict[str, list[dict[str, str]]]:
    """Combine the SOP sector tables with the LOA's handoff codes.

    A mismatch between the two documents, such as Seca's ``1S`` and ``Q2S``, stays as read.
    """
    nct = extract_sop_sectors(sop_pages)
    zoa: list[dict[str, str]] = []
    by_name = {sector["name"].upper(): sector for sector in nct}
    for page in loa_pages:
        lines = [line.text for line in text_lines(page["words"])]
        if not _is_loa_code_page(lines):
            continue
        for line in lines:
            for name, code in NCT_LOA_CODE.findall(line):
                _set_loa_code(nct, by_name, name, code)
            zoa.extend(_zoa_codes(line))
    return {"nct": nct, "zoa": zoa}


def _set_loa_code(
    nct: list[dict[str, str]], by_name: dict[str, dict[str, str]], name: str, code: str
) -> None:
    sector = by_name.get(name)
    if sector is None:
        sector = {
            "name": name.title(),
            "combined_position": "",
            "area": "",
            "radio_callsign": "",
            "frequency": "",
            "symbol": "",
            "combines_to": "",
            "loa_code": "",
        }
        nct.append(sector)
        by_name[name] = sector
    sector["loa_code"] = code


def _pacp_page(
    page: Page,
    headings: list[Heading],
    state: dict[str, Any],
    entries: list[dict[str, Any]],
) -> None:
    for line in text_lines(page["words"]):
        if line.top >= FOOTER_TOP:
            continue
        _pacp_line(page["number"], line, headings, state, entries)


def _pacp_heading_doubts(
    flows: list[str], sector: str, enclosing: Heading | None
) -> list[str]:
    """Flag an unlisted flow, or a flow its own sector's section title contradicts."""
    doubts = flow_doubts(flows)
    match = SECTION_FLOW.match(enclosing.title) if enclosing is not None else None
    if match is None or enclosing is None or match["sector"] != sector:
        return doubts
    if flows and match["flow"] not in flows:
        printed = f"{enclosing.code} {enclosing.title}"
        doubts.append(f"heading says {sector} {flows[0]} under section {printed!r}")
    return doubts


def _open_pacp_heading(
    state: dict[str, Any], heading: re.Match[str], enclosing: Heading | None
) -> None:
    flows = [heading["flow"]] if heading["flow"] else []
    doubts = _pacp_heading_doubts(flows, heading["sector"], enclosing)
    state.update(
        sector=heading["sector"], flows=flows, doubts=doubts, base=None, open=None
    )


def _close_pacp(state: dict[str, Any]) -> None:
    state.update(sector=None, flows=[], doubts=[], base=None, open=None)


def _is_pacp_continuation(state: dict[str, Any], line: Line) -> bool:
    if state["open"] is None:
        return False
    return line.x0 > state["base"] + INDENT_MARGIN


def _open_pacp_letter(
    state: dict[str, Any], letter: re.Match[str], line: Line, location: tuple[int, str]
) -> dict[str, Any]:
    if state["base"] is None:
        state["base"] = line.x0
    state["open"] = {
        "sector": state["sector"],
        "flows": state["flows"],
        "section": location[1],
        "page": location[0],
        "letter": letter["letter"],
        "text": letter["text"],
        "doubts": state["doubts"],
    }
    return state["open"]


def _pacp_line(
    number: int,
    line: Line,
    headings: list[Heading],
    state: dict[str, Any],
    entries: list[dict[str, Any]],
) -> None:
    enclosing = heading_at(headings, number, line.top)
    heading = PACP_HEADING.fullmatch(line.text)
    if heading is not None:
        _open_pacp_heading(state, heading, enclosing)
        return
    if state["sector"] is None:
        return
    letter = PACP_LETTER.match(line.text)
    if letter is not None and not _is_pacp_continuation(state, line):
        section = enclosing.code if enclosing is not None else ""
        entries.append(_open_pacp_letter(state, letter, line, (number, section)))
    elif _is_pacp_continuation(state, line):
        state["open"]["text"] = join_lines((state["open"]["text"], line.text))
    else:
        _close_pacp(state)


def extract_pacp(pages: list[Page], headings: list[Heading]) -> list[dict[str, Any]]:
    """Read the lettered lines under each sector's P-ACP heading, from words rather than tables.

    Lines are lettered at one indent and wrap or carry a ``NOTE-`` at a deeper one; anything
    else ends the list, and the list can carry over to the next page.
    """
    entries: list[dict[str, Any]] = []
    state: dict[str, Any] = {}
    _close_pacp(state)
    for page in pages:
        _pacp_page(page, headings, state, entries)
    return entries


def normalize(sop_pages: list[Page], loa_pages: list[Page]) -> Result:
    """Turn captured pages into the draft; a pure function of the captures.

    Args:
        sop_pages: The captured SOP pages, in document order.
        loa_pages: The captured LOA pages, in document order.

    Returns:
        The draft, and per document what was found and consumed.

    Raises:
        ExtractError: A source version or a reference table can't be read.
    """
    source = {
        "sop": read_source("SOP", sop_pages, SOP_VERSION),
        "loa": read_source("LOA", loa_pages, LOA_VERSION),
    }
    coverage = {"SOP": Coverage(), "LOA": Coverage()}
    headings = section_headings(sop_pages)
    rows: list[Row] = []
    for page in sop_pages:
        rows.extend(_sop_page_rows(page, headings, coverage["SOP"]))
    for page in loa_pages:
        rows.extend(_loa_page_rows(page, coverage["LOA"]))
    draft = {
        "source": source,
        "flows": extract_flows(sop_pages),
        "sectors": extract_sectors(sop_pages, loa_pages),
        "complexes": extract_complexes(sop_pages),
        "aliases": dict(ALIASES),
        "pacp": extract_pacp(sop_pages, headings),
        "rows": rows,
    }
    return Result(draft, coverage)


def render_draft(draft: dict[str, Any]) -> str:
    """Render the draft as JSON text with one row per line, so diffs stay readable."""
    parts = [
        f"  {json.dumps(key)}: "
        + json.dumps(value, ensure_ascii=False, indent=2).replace("\n", "\n  ")
        for key, value in draft.items()
        if key != "rows"
    ]
    rows = ",\n".join(
        f"    {json.dumps(row, ensure_ascii=False)}" for row in draft["rows"]
    )
    parts.append(f'  "rows": [\n{rows}\n  ]')
    return "{\n" + ",\n".join(parts) + "\n}\n"


def write_text(path: Path, text: str) -> None:
    """Write a file with LF line endings, creating its folder."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def _parse_capture_pages(specs: list[str]) -> dict[str, list[int]]:
    wanted: dict[str, list[int]] = {}
    for spec in specs:
        doc, _, numbers = spec.partition(":")
        if doc not in ("SOP", "LOA") or not numbers:
            raise ExtractError(
                f"--capture-pages takes SOP:22,92 or LOA:12, not {spec!r}"
            )
        wanted[doc] = [int(number) for number in numbers.split(",")]
    return wanted


def _write_captures(paths: dict[str, Path], specs: list[str], out_dir: Path) -> None:
    for doc, numbers in _parse_capture_pages(specs).items():
        for page in capture_pdf(paths[doc], numbers):
            target = out_dir / f"{doc.lower()}_p{page['number']}.json"
            write_text(target, json.dumps(page, ensure_ascii=False) + "\n")
            print(f"wrote {target}")


def _check_complete(result: Result) -> None:
    """Fail when a document's tables weren't all consumed, or a reference table is absent."""
    problems = [
        f"{doc} {item}"
        for doc, coverage in result.coverage.items()
        for item in coverage.unconsumed
    ]
    problems += [
        f"no {key} table was read"
        for key in ("flows", "complexes")
        if not result.draft[key]
    ]
    if not result.draft["sectors"]["nct"]:
        problems.append("no sector table was read")
    if problems:
        raise ExtractError("unconsumed:\n  " + "\n  ".join(problems))


def _arguments(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--sop", type=Path, required=True, help="The NCT SOP PDF")
    parser.add_argument("--loa", type=Path, required=True, help="The NCT-ZOA LOA PDF")
    parser.add_argument("--out", type=Path, help="Where to write the draft JSON")
    parser.add_argument(
        "--capture-pages",
        nargs="+",
        metavar="DOC:PAGES",
        help="Pages to capture, such as SOP:22,92 LOA:12",
    )
    parser.add_argument("--capture-out", type=Path, help="The folder for page captures")
    args = parser.parse_args(argv)
    if bool(args.capture_pages) != bool(args.capture_out):
        parser.error("--capture-pages and --capture-out go together")
    if not args.capture_pages and args.out is None:
        parser.error("--out is required unless capturing pages")
    return args


def main(argv: list[str] | None = None) -> int:
    """Run the extractor; return the process exit code."""
    args = _arguments(argv)
    try:
        if args.capture_pages:
            _write_captures(
                {"SOP": args.sop, "LOA": args.loa}, args.capture_pages, args.capture_out
            )
            return 0
        result = normalize(capture_pdf(args.sop), capture_pdf(args.loa))
        for doc, coverage in result.coverage.items():
            print(coverage.summary(doc))
        _check_complete(result)
    except ExtractError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    write_text(args.out, render_draft(result.draft))
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
