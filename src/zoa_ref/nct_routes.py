"""Core judgements over the reviewed NCT route data.

Which rows apply under a flow and which rows are reciprocal are decided here, so every
caller gets the same answer.
"""

from __future__ import annotations

import functools
import itertools
import json
import re
from collections import defaultdict
from collections.abc import Iterable, Sequence
from collections.abc import Set as AbstractSet
from pathlib import Path
from typing import Any, NamedTuple

Row = dict[str, Any]
_Coverage = dict[tuple[Any, ...], dict[str, set[tuple[str, str]]]]

DATA_PATH = Path(__file__).parent / "data" / "nct_routes.json"

BAY_CHOICES: tuple[frozenset[str], ...] = (
    frozenset({"SFOW"}),
    frozenset({"SFOW", "OAKE"}),
    frozenset({"SFOW", "SJCE"}),
    frozenset({"SFOW", "OAKE", "SJCE"}),
    frozenset({"SFOE"}),
    frozenset({"SFOE", "SFO10"}),
    frozenset({"SFOE", "SFO19"}),
)
VALID_FLOW_SETS: tuple[frozenset[str], ...] = tuple(
    bay | {smf, rno}
    for bay, smf, rno in itertools.product(
        BAY_CHOICES, ("SMFS", "SMFN"), ("RNOS", "RNON")
    )
)

FIELDS = ("altitude", "info", "restrictions")


class Mismatch(NamedTuple):
    """An exit row and its reciprocal entry row disagreeing on one field."""

    exit_row: Row
    entry_row: Row
    field: str
    items: list[str]
    classes: list[str]
    same_qualifiers: bool


class RowConflicts(NamedTuple):
    """What a row disagrees on, and each (item, class) no reciprocal with the row's own qualifiers covers.

    A row with a blank class reports its uncovered items with an empty class.
    """

    mismatches: list[Mismatch]
    uncovered: list[tuple[str, str]]


_BLANK_CLASS = ""
_RUNWAY_FLOWS = frozenset({"SFO10", "SFO19"})
_TABLE_RULE_FLOWS = frozenset({"OAKE", "SJCE"})
_OPPOSITE_DIRECTION = {"exit": "entry", "entry": "exit"}
_RWY = re.compile(r"\brwy\b")
_DEPS = re.compile(r"\bdeps\b")
_SLASH = re.compile(r"\s*/\s*")
_CLASS_MARKS = str.maketrans("", "", "()*")
_IDENTIFIER_LENGTH = 3


@functools.lru_cache(maxsize=1)
def load_data() -> dict[str, Any]:
    """Read the packaged route data.

    Returns:
        The parsed contents of ``data/nct_routes.json``.

    Raises:
        FileNotFoundError: The packaged data file is missing.
    """
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))


def item_key(text: str) -> str:
    """Normalise a destination or route item so two printings of it compare equal.

    Args:
        text: The item as printed.

    Returns:
        The item casefolded, with ``Rwy`` spelled out, commas dropped, whitespace
        collapsed and a leading ``RV`` dropped. A trailing ``DP`` is dropped too unless
        what remains is a three-letter identifier, where ``SFO DP`` isn't ``SFO``.
    """
    spelled = _RWY.sub("runway", text.casefold()).replace(",", "")
    collapsed = " ".join(spelled.split()).removeprefix("rv ")
    bare = collapsed.removesuffix(" dp")
    return bare if len(bare) > _IDENTIFIER_LENGTH else collapsed


def value_key(text: str) -> str:
    """Normalise a printed cell so two printings of one value compare equal.

    Args:
        text: The cell as printed.

    Returns:
        The cell casefolded, with degree signs removed, one space on each side of a
        slash, whitespace collapsed and a final period dropped.
    """
    stripped = _SLASH.sub(" / ", text.casefold().replace("°", ""))
    return " ".join(stripped.split()).removesuffix(".")


def class_key(text: str) -> str:
    """Normalise an aircraft class so two printings of it compare equal.

    Args:
        text: The class as printed.

    Returns:
        The class casefolded, with parentheses, asterisks and a trailing ``only`` dropped.
    """
    bare = text.casefold().translate(_CLASS_MARKS).strip()
    return bare.removesuffix(" only")


def qualifier_key(text: str) -> str:
    """Normalise a qualifier so two printings of one limit compare equal.

    Args:
        text: The qualifier as printed.

    Returns:
        The qualifier casefolded, with ``&`` as ``and``, ``deps`` as ``departures``,
        whitespace collapsed and a trailing ``only`` dropped.
    """
    spelled = _DEPS.sub("departures", text.casefold().replace("&", "and"))
    return " ".join(spelled.split()).removesuffix(" only")


def has_class(row: Row, aircraft: str) -> bool:
    """Tell whether a row answers for a class.

    Args:
        row: The row to test. A blank class shares a class with every row.
        aircraft: The class as printed, or blank.

    Returns:
        True when either side is blank or the row prints the class.
    """
    if not row["aircraft"] or not aircraft:
        return True
    return class_key(aircraft) in {class_key(printed) for printed in row["aircraft"]}


def row_applies(row: Row, chosen: AbstractSet[str]) -> bool:
    """Tell whether both of a row's flow conditions hold.

    Args:
        row: The row to test.
        chosen: The chosen flows, holding the parent of any specific flow. Plain SFOE
            doesn't say which runway, so it also activates SFO10 and SFO19.

    Returns:
        True when ``table_flows`` and ``flows`` are each empty or name an active flow.
    """
    active = set(chosen)
    if "SFOE" in active and not active & _RUNWAY_FLOWS:
        active |= _RUNWAY_FLOWS
    return all(
        not conditions or not active.isdisjoint(conditions)
        for conditions in (row["table_flows"], row["flows"])
    )


def rows_for(all_rows: Sequence[Row], chosen: AbstractSet[str]) -> list[Row]:
    """Select the rows that answer under the chosen flows.

    Args:
        all_rows: Every row of the file. A row outside this list can't displace or
            replace another, so a lookup filters what this returns, never what it takes.
        chosen: The chosen flows, holding the parent of any specific flow.

    Returns:
        The rows passing ``row_applies``, narrowed by the table rule and then the row
        rule, in input order.
    """
    applying = [row for row in all_rows if row_applies(row, chosen)]
    return _apply_row_rule(_apply_table_rule(applying, all_rows, chosen), chosen)


def applicable_rows(chosen: AbstractSet[str]) -> list[Row]:
    """Narrow the whole packaged file under the chosen flows, for a lookup to filter.

    Args:
        chosen: The chosen flows, holding the parent of any specific flow.

    Returns:
        The rows that answer under those flows, in file order.
    """
    return rows_for(load_data()["rows"], chosen)


def find_reciprocals(
    row: Row, all_rows: Sequence[Row], chosen: AbstractSet[str]
) -> list[Row]:
    """Find a row's reciprocals among the rows that answer under the chosen flows.

    Args:
        row: The row to pair. An LOA row has no reciprocal inside the data, and a row
            that doesn't answer under the flows has none under them.
        all_rows: Every row of the file.
        chosen: The chosen flows, holding the parent of any specific flow.

    Returns:
        The opposite-direction SOP rows with the same sectors, a shared class and a
        shared item. A qualified row takes only those with its qualifiers; an unqualified
        row prefers unqualified ones and falls back to all.
    """
    narrowed = rows_for(all_rows, chosen)
    if all(other["id"] != row["id"] for other in narrowed):
        return []
    return _reciprocals_among(row, narrowed)


def conflicts(
    row: Row, all_rows: Sequence[Row], chosen: AbstractSet[str]
) -> RowConflicts:
    """Judge one row against its reciprocals under the chosen flows.

    Args:
        row: The row to judge. An LOA row, or a row that doesn't answer under the flows,
            has no conflicts under them.
        all_rows: Every row of the file.
        chosen: The chosen flows, holding the parent of any specific flow.

    Returns:
        Every mismatch of a pair the row belongs to, seen from either side, and the
        (item, class) pairs no reciprocal with the row's own qualifiers covers.
    """
    sectors = row["from"], row["to"]
    between = [
        other
        for other in rows_for(all_rows, chosen)
        if other["doc"] == "SOP" and (other["from"], other["to"]) == sectors
    ]
    return _judge(between).get(row["id"], RowConflicts([], []))


def conflicts_by_row(
    all_rows: Sequence[Row], chosen: AbstractSet[str]
) -> dict[str, RowConflicts]:
    """Judge every SOP row that answers under the chosen flows, narrowing once.

    Args:
        all_rows: Every row of the file.
        chosen: The chosen flows, holding the parent of any specific flow.

    Returns:
        Each such row's id mapped to what ``conflicts`` returns for it, in file order.
    """
    return _judge([row for row in rows_for(all_rows, chosen) if row["doc"] == "SOP"])


def _judge(rows: list[Row]) -> dict[str, RowConflicts]:
    """Judge narrowed SOP rows, attaching each mismatch to both rows of its pair."""
    candidates = _candidates_by_id(rows)
    pairs: dict[str, dict[tuple[str, str, str], Mismatch]] = defaultdict(dict)
    for row in rows:
        for mismatch in _row_mismatches(row, candidates):
            exit_id, entry_id = mismatch.exit_row["id"], mismatch.entry_row["id"]
            key = (exit_id, entry_id, mismatch.field)
            pairs[exit_id].setdefault(key, mismatch)
            pairs[entry_id].setdefault(key, mismatch)
    return {
        row["id"]: RowConflicts(
            list(pairs[row["id"]].values()), _uncovered(row, candidates[row["id"]])
        )
        for row in rows
    }


def _reciprocals_among(row: Row, rows: Iterable[Row]) -> list[Row]:
    """Find a row's reciprocals among rows already narrowed under one flow set."""
    if row["doc"] != "SOP":
        return []
    candidates = [other for other in rows if _is_candidate(row, other)]
    same = [other for other in candidates if _same_qualifiers(row, other)]
    return same if row["qualifiers"] else same or candidates


def _same_qualifiers(row: Row, other: Row) -> bool:
    """Tell whether two rows carry the same limits."""
    return _qualifier_set(row) == _qualifier_set(other)


def _candidates_by_id(rows: list[Row]) -> dict[str, list[Row]]:
    """Find each row's reciprocals, searching only rows between the same two sectors."""
    by_sectors: dict[tuple[str, str], list[Row]] = defaultdict(list)
    for row in rows:
        by_sectors[row["from"], row["to"]].append(row)
    return {
        row["id"]: _reciprocals_among(row, by_sectors[row["from"], row["to"]])
        for row in rows
    }


def _row_mismatches(row: Row, candidates: dict[str, list[Row]]) -> list[Mismatch]:
    """Compare a row with each of its reciprocals."""
    found = []
    for other in candidates[row["id"]]:
        exit_row, entry_row = (
            (row, other) if row["direction"] == "exit" else (other, row)
        )
        items = _shared_items(exit_row, entry_row)
        classes = _shared_classes(exit_row, entry_row)
        same = _same_qualifiers(exit_row, entry_row)
        found.extend(
            Mismatch(exit_row, entry_row, field, items, classes, same)
            for field in _mismatched_fields(exit_row, entry_row, candidates)
        )
    return found


def _uncovered(row: Row, candidates: list[Row]) -> list[tuple[str, str]]:
    """Return each printed (item, class) of a row that no candidate covers."""
    same = [other for other in candidates if _same_qualifiers(row, other)]
    return [
        (item, aircraft)
        for item in row["dest_or_route"]
        for aircraft in row["aircraft"] or [_BLANK_CLASS]
        if not any(_covers(other, item, aircraft) for other in same)
    ]


def _covers(row: Row, item: str, aircraft: str) -> bool:
    """Tell whether a row answers for an item and a class."""
    key = item_key(item)
    return has_class(row, aircraft) and any(
        item_key(other) == key for other in row["dest_or_route"]
    )


def _shared_items(exit_row: Row, entry_row: Row) -> list[str]:
    """Return the exit row's items that the entry row also answers for."""
    entry_keys = {item_key(item) for item in entry_row["dest_or_route"]}
    return [item for item in exit_row["dest_or_route"] if item_key(item) in entry_keys]


def _shared_classes(exit_row: Row, entry_row: Row) -> list[str]:
    """Return the classes a pair shares, as the printing side has them."""
    shared = [
        aircraft for aircraft in exit_row["aircraft"] if has_class(entry_row, aircraft)
    ]
    return shared or list(entry_row["aircraft"])


def _settling_candidates(
    row: Row, candidates: list[Row], items: list[str], classes: list[str]
) -> list[Row]:
    """Keep a row's candidates with its limits sharing an (item, class) with the pair."""
    return [
        other
        for other in candidates
        if _same_qualifiers(row, other)
        and any(
            _covers(other, item, aircraft)
            for item in items
            for aircraft in classes or [_BLANK_CLASS]
        )
    ]


def _mismatched_fields(
    exit_row: Row, entry_row: Row, candidates: dict[str, list[Row]]
) -> Iterable[str]:
    """Yield the fields a pair disagrees on that neither side's other candidates settle."""
    items = _shared_items(exit_row, entry_row)
    classes = _shared_classes(exit_row, entry_row)
    exit_side = _settling_candidates(
        exit_row, candidates[exit_row["id"]], items, classes
    )
    entry_side = _settling_candidates(
        entry_row, candidates[entry_row["id"]], items, classes
    )
    for field in FIELDS:
        exit_value = value_key(exit_row[field])
        entry_value = value_key(entry_row[field])
        if exit_value == entry_value:
            continue
        if field != "altitude" and not (exit_value and entry_value):
            continue
        if _any_candidate_has(exit_side, field, exit_value):
            continue
        if _any_candidate_has(entry_side, field, entry_value):
            continue
        yield field


def _any_candidate_has(candidates: list[Row], field: str, value: str) -> bool:
    """Tell whether any candidate prints a value in a field."""
    return any(value_key(other[field]) == value for other in candidates)


def _apply_table_rule(
    rows: Sequence[Row], all_rows: Sequence[Row], chosen: AbstractSet[str]
) -> list[Row]:
    """Drop a sector's SFOW table for a direction that has an active OAKE or SJCE table."""
    displaced = {
        _sop_pair(row)
        for row in all_rows
        if row["doc"] == "SOP"
        and len(row["table_flows"]) == 1
        and row["table_flows"][0] in _TABLE_RULE_FLOWS & chosen
    }
    return [
        row
        for row in rows
        if not (
            row["doc"] == "SOP"
            and row["table_flows"] == ["SFOW"]
            and _sop_pair(row) in displaced
        )
    ]


def _apply_row_rule(rows: Sequence[Row], chosen: AbstractSet[str]) -> list[Row]:
    """Drop rows fully covered by surviving rows tagged with an active specific flow."""
    parents = load_data()["flow_parents"]
    active = chosen & parents.keys()
    coverage: _Coverage = defaultdict(lambda: defaultdict(set))
    for row in rows:
        tags = _tags(row)
        for flow in active.intersection(tags):
            if parents[flow] not in tags:
                coverage[_match_key(row)][flow] |= _item_classes(row)
    return [row for row in rows if not _is_replaced(row, active, coverage, parents)]


def _is_replaced(
    row: Row,
    active: AbstractSet[str],
    coverage: _Coverage,
    parents: dict[str, str],
) -> bool:
    """Tell whether every (item, class) of a tagged row is covered by rows it competes with."""
    tags = _tags(row)
    if not tags or active.intersection(tags):
        return False
    covered: set[tuple[str, str]] = set()
    for flow, pairs in coverage.get(_match_key(row), {}).items():
        if _competes(tags, flow, parents):
            covered |= pairs
    answers = _item_classes(row)
    return bool(answers) and answers <= covered


def _competes(tags: list[str], flow: str, parents: dict[str, str]) -> bool:
    """Tell whether tags name the parent of a specific flow, or a sibling of it."""
    parent = parents[flow]
    return any(tag == parent or parents.get(tag) == parent for tag in tags)


def _sop_pair(row: Row) -> tuple[str, str]:
    """Return the (sector, direction) whose table a row belongs to."""
    sector = row["from"] if row["direction"] == "exit" else row["to"]
    return sector, row["direction"]


def _tags(row: Row) -> list[str]:
    """Return a row's own flows, or its table's when the row names none."""
    return row["flows"] or row["table_flows"]


def _match_key(row: Row) -> tuple[Any, ...]:
    """Return what two rows must share to compete for the same handoff."""
    airports = tuple(sorted(row["from_airports"]))
    limits = frozenset(_qualifier_set(row))
    return row["doc"], row["direction"], row["from"], airports, limits


def _item_classes(row: Row) -> set[tuple[str, str]]:
    """Return every (item key, class) a row answers for."""
    return {
        (item_key(item), class_key(aircraft))
        for item in row["dest_or_route"]
        for aircraft in row["aircraft"]
    }


def _is_candidate(row: Row, other: Row) -> bool:
    """Tell whether another row could be a row's reciprocal, ignoring qualifiers."""
    return (
        other["doc"] == "SOP"
        and other["direction"] == _OPPOSITE_DIRECTION[row["direction"]]
        and other["from"] == row["from"]
        and other["to"] == row["to"]
        and _shares_class(row, other)
        and not _item_keys(other).isdisjoint(_item_keys(row))
    )


def _shares_class(row: Row, other: Row) -> bool:
    """Tell whether two rows have a class in common, a blank class matching any."""
    return not row["aircraft"] or any(
        has_class(other, aircraft) for aircraft in row["aircraft"]
    )


def _item_keys(row: Row) -> set[str]:
    """Return the keys of a row's items."""
    return {item_key(item) for item in row["dest_or_route"]}


def _qualifier_set(row: Row) -> set[str]:
    """Return a row's qualifiers, normalised by ``qualifier_key``."""
    return {qualifier_key(qualifier) for qualifier in row["qualifiers"]}
