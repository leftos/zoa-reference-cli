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

FLOW_ORDER = (
    "SFOW",
    "SFOE",
    "SFO10",
    "SFO19",
    "OAKE",
    "SJCE",
    "SMFS",
    "SMFN",
    "RNOS",
    "RNON",
)
DEFAULT_FLOWS = frozenset({"SFOW", "SMFS", "RNOS"})


class FlowError(ValueError):
    """A flow name that doesn't exist, or flows that can't run together."""


class UnknownSectorError(ValueError):
    """A sector no row of the file names."""


class UnknownClassError(ValueError):
    """An aircraft class no row of the file carries."""


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


class XferQuery(NamedTuple):
    """What a controller asked: a sector, a destination or route, a class, a direction."""

    sector: str
    target: str
    aircraft: str
    entry: bool


class XferAnswer(NamedTuple):
    """The rows answering a query, each row's disagreements and the classes each row answers for.

    A row with a blank class shows no classes. ``matches_anywhere`` tells whether any
    row of the file names the target.
    """

    rows: list[Row]
    mismatches: dict[str, list[Mismatch]]
    matches_anywhere: bool
    shown_classes: dict[str, list[str]]


class _Target(NamedTuple):
    """What a lookup target can mean: its spellings, a complex it names, complexes it belongs to."""

    names: frozenset[str]
    queried_complex: str | None
    member_of: frozenset[str]
    complexes: dict[str, frozenset[str]]
    aliases: dict[str, str]


class _Lookup(NamedTuple):
    """What one lookup reads while judging its catch-all rows."""

    query: XferQuery
    target: _Target
    chosen: AbstractSet[str]
    applicable: list[Row]


_FLOW_GROUPS = (
    (frozenset({"SFOW", "SFOE"}), "SFOW"),
    (frozenset({"SMFS", "SMFN"}), "SMFS"),
    (frozenset({"RNOS", "RNON"}), "RNOS"),
)
_FLOWS_SPLIT = re.compile(r"[,\s]+")
_ZOA_SECTOR = "zoa"
_NOISE_WORDS = frozenset(
    {
        "all",
        "and",
        "arrivals",
        "at",
        "cx",
        "departures",
        "direct",
        "dp",
        "dps",
        "from",
        "landing",
        "of",
        "on",
        "only",
        "or",
        "others",
        "rv",
        "sid",
        "star",
        "the",
        "to",
        "via",
    }
)
_TOKEN_SPLIT = re.compile(r"[\s/,&().:;]+")
_POSSESSIVE = re.compile(r"['’]s$")
_EXCEPT_ON_FLOW = re.compile(r"\bon\s+(\S+)$")
_EXCEPT_PREFIX = "except"
_NOT_MATCH_TEXT_PREFIXES = (_EXCEPT_PREFIX, "excluding")
_CATCH_ALL_PREFIX = "all others"
_BARE_ALL = "all"
_LANDING_NCT = "landing nct"
_COMPLEX_SUFFIX = " cx"
_MATCH_DIRECT = 0
_MATCH_QUERIED_COMPLEX = 1
_MATCH_THROUGH_COMPLEX = 2
_MATCH_COMPLEX_NAME = 3
_MATCH_PHRASE = 4

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


def conflicts_in_file(row: Row, chosen: AbstractSet[str]) -> RowConflicts:
    """Judge one row against its reciprocals in the whole packaged file.

    Args:
        row: The row to judge.
        chosen: The chosen flows, holding the parent of any specific flow.

    Returns:
        What ``conflicts`` returns for the row over every row of the file.
    """
    return conflicts(row, load_data()["rows"], chosen)


def flow_names(text: str) -> list[str]:
    """Split typed flows into the names they hold, as typed.

    Args:
        text: Flow names separated by commas or whitespace.

    Returns:
        The names, which is none for a text of only separators.
    """
    return [name for name in _FLOWS_SPLIT.split(text.strip()) if name]


def parse_flows(text: str) -> frozenset[str]:
    """Read a typed list of flows into a complete flow set.

    Args:
        text: Flow names separated by commas or whitespace, in any case.

    Returns:
        The named flows with each one's parent, and the default flow of any group
        (Bay, Sacramento, Reno) the text doesn't name.

    Raises:
        FlowError: A name isn't a flow, or the flows can't run together.
    """
    parents = load_data()["flow_parents"]
    named: set[str] = set()
    for name in flow_names(text):
        if name.upper() not in FLOW_ORDER:
            known = ", ".join(FLOW_ORDER)
            raise FlowError(f"Unknown flow '{name}'. Known: {known}.")
        named.add(name.upper())
    named |= {parents[flow] for flow in named if flow in parents}
    for group, default in _FLOW_GROUPS:
        if named.isdisjoint(group):
            named.add(default)
    chosen = frozenset(named)
    if chosen not in VALID_FLOW_SETS:
        raise FlowError(
            "Those flows can't run together: OAKE and SJCE need SFOW, SFO10 and SFO19 need SFOE "
            "and are set one at a time, and SMF and RNO each take one flow."
        )
    return chosen


def row_flow_names(row: Row, chosen: AbstractSet[str]) -> list[str]:
    """Name the flows an answer has to print beside a row.

    Args:
        row: A row that answers under the flows.
        chosen: The chosen flows, holding the parent of any specific flow.

    Returns:
        The row's tags that are active specific flows. Plain SFOE doesn't say which
        runway, so SFOE, SFO10 and SFO19 count too under it.
    """
    named = chosen & load_data()["flow_parents"].keys()
    if "SFOE" in chosen and not chosen & _RUNWAY_FLOWS:
        named = named | _RUNWAY_FLOWS | {"SFOE"}
    return [flow for flow in _tags(row) if flow in named]


def lookup(query: XferQuery, chosen: AbstractSet[str]) -> XferAnswer:
    """Answer a handoff query from the rows that apply under the chosen flows.

    Args:
        query: The sector, target, class and direction asked for.
        chosen: The chosen flows, holding the parent of any specific flow.

    Returns:
        The rows that answer, in file order with catch-alls last, the disagreements worth warning of,
        whether the target matches any row of the file under any flow, and the classes
        each row answers for.

    Raises:
        UnknownSectorError: No row names the sector.
        UnknownClassError: No row carries the class.
    """
    _check_sector(query.sector)
    _check_class(query.aircraft)
    target = _resolve_target(query.target)
    context = _Lookup(query, target, chosen, applicable_rows(chosen))
    row_set = _query_rows(context.applicable, query)
    named = _named_rows(row_set, target, _reads_airports(query), chosen)
    filed = [] if _rows_for_class(named, query.aircraft) else _airport_filed(context)
    shown = _shown_classes(row_set, named, context)
    shown |= {row["id"]: list(row["aircraft"]) for row in filed}
    rows = sorted(
        (row for row in [*row_set, *filed] if row["id"] in shown), key=_is_catch_all
    )
    return XferAnswer(
        rows,
        _worth_warning(rows, target, query.aircraft, chosen),
        _matches_anywhere(target),
        shown,
    )


def matched_items(row: Row, query: XferQuery) -> list[str]:
    """Name the destinations a line has to print for it to say what it answers.

    Args:
        row: An answered row.
        query: What was asked.

    Returns:
        A longer destination holding the target as a word, or a complex's name without
        ``CX``. Every destination of a row matched only by a qualifier or an airport.
        A bare ``All`` row's item. Nothing for an exact match, a match through a
        complex, a phrase, a route, an ``All others`` row or a target naming a complex
        through a destination.
    """
    target = _resolve_target(query.target)
    if _is_catch_all(row):
        return [item for item in row["dest_or_route"] if item_key(item) == _BARE_ALL]
    matched = _matched_destinations(row, target)
    if matched:
        return _longer_items(matched, target)
    if any(_item_kind(item, target) is not None for item in row["route"]):
        return []
    return list(row["dest_or_route"])


def _matched_destinations(row: Row, target: _Target) -> list[str]:
    """Return the destination items of a row that match a target."""
    return [
        item for item in row["dest_or_route"] if _item_kind(item, target) is not None
    ]


def _longer_items(matched: list[str], target: _Target) -> list[str]:
    """Keep matched destinations that say more than the target or its complex."""
    if target.queried_complex is not None:
        return [
            item
            for item in matched
            if _holds_bare_name(item.casefold(), target.queried_complex)
        ]
    exact = {item_key(name) for name in target.names}
    return [
        item
        for item in matched
        if item_key(item) not in exact
        and _item_kind(item, target) in (_MATCH_DIRECT, _MATCH_COMPLEX_NAME)
    ]


def _holds_bare_name(text: str, key: str) -> bool:
    """Tell whether a casefolded text holds a complex's name other than as ``<name> CX``."""
    return _holds(text, key) and not _holds(text, f"{key}{_COMPLEX_SUFFIX}")


def _reads_airports(query: XferQuery) -> bool:
    """Tell whether a query matches rows on the airports they depart from."""
    return query.sector.casefold() == _ZOA_SECTOR and query.entry


def _matches_anywhere(target: _Target) -> bool:
    """Tell whether any row of the file, under any flow, names a target."""
    return any(_row_kind(row, target, True) is not None for row in load_data()["rows"])


def _check_sector(sector: str) -> None:
    """Refuse a sector that no row names, since a typo isn't a lack of instructions."""
    known = {_ZOA_SECTOR}
    for row in load_data()["rows"]:
        if row["doc"] == "SOP":
            known |= {row["from"], row["to"]}
        elif row["direction"] == "loa_arrival":
            known.add(row["to"])
        else:
            known.add(row["from"])
    known.discard("")
    if sector.casefold() not in {name.casefold() for name in known}:
        names = ", ".join(sorted(known, key=str.casefold))
        raise UnknownSectorError(f"Unknown sector '{sector}'. Known: {names}.")


def _check_class(aircraft: str) -> None:
    """Refuse a class that no row carries, since a typo isn't a lack of instructions."""
    if not aircraft:
        return
    known = {
        class_key(printed) for row in load_data()["rows"] for printed in row["aircraft"]
    }
    if class_key(aircraft) not in known:
        names = ", ".join(sorted(name.upper() for name in known))
        raise UnknownClassError(f"Unknown aircraft class '{aircraft}'. Known: {names}.")


def _resolve_target(text: str) -> _Target:
    """Work out what a typed target can mean in the file's complexes and aliases."""
    complexes = _folded_complexes()
    aliases = {
        alias.casefold(): resolved.casefold().removesuffix(_COMPLEX_SUFFIX)
        for alias, resolved in load_data()["aliases"].items()
    }
    folded = " ".join(text.casefold().split())
    names = {folded}
    if len(folded) == 4 and folded.startswith("k"):
        names.add(folded[1:])
    bare = folded.removesuffix(_COMPLEX_SUFFIX)
    queried = bare if bare in complexes else aliases.get(bare)
    member_of = frozenset(
        key for key, airports in complexes.items() if not airports.isdisjoint(names)
    )
    return _Target(frozenset(names), queried, member_of, complexes, aliases)


def _folded_complexes() -> dict[str, frozenset[str]]:
    """Return each complex's casefolded name and member airports."""
    return {
        key.casefold(): frozenset(airport.casefold() for airport in airports)
        for key, airports in load_data()["complexes"].items()
    }


def _query_rows(rows: Iterable[Row], query: XferQuery) -> list[Row]:
    """Keep the rows a query reads: one sector's rows in a direction, or one LOA side."""
    sector = query.sector.casefold()
    if sector == _ZOA_SECTOR:
        wanted = "loa_departure" if query.entry else "loa_arrival"
        return [row for row in rows if row["direction"] == wanted]
    return [row for row in rows if _sector_reads(row, sector, query.entry)]


def _sector_reads(row: Row, sector: str, entry: bool) -> bool:
    """Tell whether a row is a sector's own, in the direction asked."""
    field, directions = (
        ("to", ("entry", "loa_arrival"))
        if entry
        else ("from", ("exit", "loa_departure"))
    )
    return row["direction"] in directions and row[field].casefold() == sector


def _airport_filed(context: _Lookup) -> list[Row]:
    """Return the airport-filed LOA rows a lookup out of a sector falls to."""
    query = context.query
    if query.entry or query.sector.casefold() == _ZOA_SECTOR:
        return []
    return [
        row
        for row in context.applicable
        if _is_airport_filed(row)
        and has_class(row, query.aircraft)
        and _filed_row_names_target(row, context)
    ]


def _target_airports(target: _Target) -> frozenset[str]:
    """Return the airports a target stands for: its spellings, or its complex's members."""
    if target.queried_complex is None:
        return target.names
    return target.complexes[target.queried_complex]


def _filed_row_names_target(row: Row, context: _Lookup) -> bool:
    """Tell whether an airport-filed row names a target that isn't its own departure airport."""
    target = context.target
    own_airports = {airport.casefold() for airport in row["from_airports"]}
    return (
        _target_airports(target).isdisjoint(own_airports)
        and not _is_excluded(row, target, context.chosen)
        and _row_kind(row, target, False) is not None
    )


def _tokens(text: str) -> set[str]:
    """Split a text into its casefolded words, without possessives or noise words."""
    words = (_POSSESSIVE.sub("", word) for word in _TOKEN_SPLIT.split(text.casefold()))
    return {word for word in words if word and word not in _NOISE_WORDS}


def _holds(text: str, phrase: str) -> bool:
    """Tell whether a casefolded text holds a phrase on word boundaries."""
    return re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text) is not None


def _holds_complex(text: str, key: str, aliases: dict[str, str]) -> bool:
    """Tell whether a casefolded text names a complex, directly or by an alias."""
    return _holds(text, f"{key}{_COMPLEX_SUFFIX}") or any(
        resolved == key and _holds(text, alias) for alias, resolved in aliases.items()
    )


def _item_kind(item: str, target: _Target) -> int | None:
    """Return how an item matches a target, the strongest way first, or None."""
    tokens = _tokens(item)
    text = item.casefold()
    if _is_direct(text, tokens, target):
        return _MATCH_DIRECT
    if _matches_queried_complex(text, tokens, target):
        return _MATCH_QUERIED_COMPLEX
    return _member_kind(item, text, target)


def _is_direct(text: str, tokens: set[str], target: _Target) -> bool:
    """Tell whether a text holds the target itself: a word, or consecutive words."""
    if not target.names.isdisjoint(tokens):
        return True
    spelled = _RWY.sub("runway", text)
    return target.queried_complex is None and any(
        " " in name and _holds(spelled, _RWY.sub("runway", name))
        for name in target.names
    )


def _matches_queried_complex(text: str, tokens: set[str], target: _Target) -> bool:
    """Tell whether a text names the complex a target asks for, or lands inside it."""
    queried = target.queried_complex
    return queried is not None and (
        _holds_complex(text, queried, target.aliases)
        or _holds(text, queried)
        or not target.complexes[queried].isdisjoint(tokens)
        or _holds(text, _LANDING_NCT)
    )


def _member_kind(item: str, text: str, target: _Target) -> int | None:
    """Return how a text reaches a member airport through its complex, or None."""
    if any(_holds_complex(text, key, target.aliases) for key in target.member_of):
        return _MATCH_THROUGH_COMPLEX
    if any(_holds(text, key) for key in target.member_of):
        return _MATCH_COMPLEX_NAME
    if target.member_of and _LANDING_NCT in item_key(item):
        return _MATCH_PHRASE
    return None


def _is_airport_filed(row: Row) -> bool:
    """Tell whether an LOA departure names its airports instead of a sending sector."""
    return row["direction"] == "loa_departure" and not row["from"]


def _is_exclusion(qualifier: str) -> bool:
    """Tell whether a qualifier takes targets away from its row."""
    return qualifier.casefold().startswith(_EXCEPT_PREFIX)


def _is_match_text(qualifier: str) -> bool:
    """Tell whether a target can match a row by a qualifier, which limits a row instead of naming."""
    return not qualifier.casefold().startswith(_NOT_MATCH_TEXT_PREFIXES)


def _row_items(row: Row, with_airports: bool) -> list[str]:
    """Return the texts of a row a target can match.

    An airport-filed row read without its airports answers on destination and route only.
    """
    items = [*row["dest_or_route"], *row["route"]]
    if with_airports or not _is_airport_filed(row):
        items += [q for q in row["qualifiers"] if _is_match_text(q)]
    if with_airports:
        items += row["from_airports"]
    return items


def _row_kind(row: Row, target: _Target, with_airports: bool) -> int | None:
    """Return how a row's text matches a target, the strongest of its items, or None."""
    kinds = [_item_kind(item, target) for item in _row_items(row, with_airports)]
    return min((kind for kind in kinds if kind is not None), default=None)


def _is_catch_all(row: Row) -> bool:
    """Tell whether an SOP row answers for whatever else its table doesn't name."""
    return row["doc"] == "SOP" and any(
        item_key(item) == _BARE_ALL or item_key(item).startswith(_CATCH_ALL_PREFIX)
        for item in row["dest_or_route"]
    )


def _is_excluded(row: Row, target: _Target, chosen: AbstractSet[str]) -> bool:
    """Tell whether one of a row's exclusion qualifiers removes it for a target."""
    return any(
        _excepts(qualifier, target, chosen)
        for qualifier in row["qualifiers"]
        if _is_exclusion(qualifier)
    )


def _excepts(qualifier: str, target: _Target, chosen: AbstractSet[str]) -> bool:
    """Tell whether an exclusion qualifier names a target while its flow, if any, is chosen."""
    folded = qualifier.casefold()
    on_flow = _EXCEPT_ON_FLOW.search(folded)
    if (
        on_flow
        and on_flow[1].upper() in FLOW_ORDER
        and on_flow[1].upper() not in chosen
    ):
        return False
    terms = set(target.names | target.member_of)
    if target.queried_complex is not None:
        terms.add(target.queried_complex)
    return not terms.isdisjoint(_tokens(qualifier)) or any(
        _holds(folded, term) for term in terms
    )


def _match_kinds(
    rows: Iterable[Row], target: _Target, with_airports: bool, chosen: AbstractSet[str]
) -> dict[str, int]:
    """Map each row that matches a target by itself to how it matches."""
    kinds = {}
    for row in rows:
        if _is_catch_all(row) or _is_excluded(row, target, chosen):
            continue
        kind = _row_kind(row, target, with_airports)
        if kind is not None:
            kinds[row["id"]] = kind
    return kinds


def _named_rows(
    rows: Iterable[Row], target: _Target, with_airports: bool, chosen: AbstractSet[str]
) -> list[Row]:
    """Return the rows naming a target, narrowed to the airport asked."""
    kinds = _match_kinds(rows, target, with_airports, chosen)
    matched = [row for row in rows if row["id"] in kinds]
    return _narrow_to_airport(matched, kinds, target, chosen)


def _rows_of_kind(rows: list[Row], kinds: dict[str, int], kind: int) -> list[Row]:
    """Keep the rows that matched one way."""
    return [row for row in rows if kinds[row["id"]] == kind]


def _narrow_to_airport(
    rows: list[Row],
    kinds: dict[str, int],
    target: _Target,
    chosen: AbstractSet[str],
) -> list[Row]:
    """Drop complex rows an active specific flow's row answers for the airport asked."""
    if target.queried_complex is not None or not target.member_of:
        return rows
    parents = load_data()["flow_parents"]
    active = chosen & parents.keys()
    direct = _rows_of_kind(rows, kinds, _MATCH_DIRECT)
    return [
        row
        for row in rows
        if kinds[row["id"]] != _MATCH_THROUGH_COMPLEX
        or not any(_answers_instead(other, row, active, parents) for other in direct)
    ]


def _answers_instead(
    direct: Row, row: Row, active: AbstractSet[str], parents: dict[str, str]
) -> bool:
    """Tell whether a directly matched row replaces a complex row, as the row rule judges it."""
    return (
        _match_key(direct) == _match_key(row)
        and _class_keys(row) <= _class_keys(direct)
        and any(
            flow in active and _competes(_tags(row), flow, parents)
            for flow in _tags(direct)
        )
    )


def _class_keys(row: Row) -> set[str]:
    """Return a row's classes, normalised by ``class_key``."""
    return {class_key(printed) for printed in row["aircraft"]}


def _shown_classes(
    row_set: Iterable[Row], named: list[Row], context: _Lookup
) -> dict[str, list[str]]:
    """Map each answering row to the classes it answers for."""
    aircraft = context.query.aircraft
    shown = {
        row["id"]: list(row["aircraft"]) for row in named if has_class(row, aircraft)
    }
    for row in row_set:
        if _is_catch_all(row) and not _is_excluded(row, context.target, context.chosen):
            classes = _uncovered_classes(
                row, _judged_rows(row, named, context), aircraft
            )
            if classes:
                shown[row["id"]] = classes
    return shown


def _judged_rows(catch_all: Row, named: list[Row], context: _Lookup) -> list[Row]:
    """Return the rows naming the target that a catch-all row gives way to.

    An exit row gives way to its own table. An entry row gives way to its sender's exit
    rows, so both directions of one handoff give the same answer.
    """
    if not context.query.entry:
        return [row for row in named if row["table"] == catch_all["table"]]
    sender = [
        row
        for row in context.applicable
        if row["direction"] == "exit" and row["from"] == catch_all["from"]
    ]
    return _named_rows(sender, context.target, False, context.chosen)


def _uncovered_classes(row: Row, named: list[Row], aircraft: str) -> list[str]:
    """Return the classes a catch-all answers for: those no row naming the target covers.

    (item, class) is the unit, so a row naming the target for another class leaves this
    row answering. A blank-class catch-all answers only with no such row, as one blank class.
    """
    covering = _rows_for_class(named, aircraft)
    if any(not row_named["aircraft"] for row_named in covering):
        return []
    if not row["aircraft"]:
        return [] if covering else [_BLANK_CLASS]
    covered = set().union(*map(_class_keys, covering))
    return [
        printed
        for printed in row["aircraft"]
        if class_key(printed) not in covered and _is_asked_class(printed, aircraft)
    ]


def _rows_for_class(rows: list[Row], aircraft: str) -> list[Row]:
    """Keep the rows answering for a class."""
    return [row for row in rows if has_class(row, aircraft)]


def _is_asked_class(printed: str, aircraft: str) -> bool:
    """Tell whether a printed class is the one asked for, when one was."""
    return not aircraft or class_key(printed) == class_key(aircraft)


def _warns_for_class(mismatch: Mismatch, aircraft: str) -> bool:
    """Tell whether a disagreement concerns the class asked, or no class limits it."""
    return (
        not aircraft
        or not mismatch.classes
        or class_key(aircraft) in {class_key(printed) for printed in mismatch.classes}
    )


def _concerns_match(mismatch: Mismatch, row: Row, target: _Target) -> bool:
    """Tell whether a disagreement covers what a row was matched by.

    Only a row matched through a destination can miss: a qualifier, airport or catch-all
    match says nothing about which item a disagreement is over.
    """
    matched = _matched_destinations(row, target)
    if not matched:
        return True
    shared = {item_key(item) for item in mismatch.items}
    return any(item_key(item) in shared for item in matched)


def _worth_warning(
    rows: Iterable[Row], target: _Target, aircraft: str, chosen: AbstractSet[str]
) -> dict[str, list[Mismatch]]:
    """Map each answered SOP row to its disagreements over what was asked."""
    found = {}
    for row in rows:
        if row["doc"] != "SOP":
            continue
        kept = [
            mismatch
            for mismatch in conflicts_in_file(row, chosen).mismatches
            if _warns_for_class(mismatch, aircraft)
            and _concerns_match(mismatch, row, target)
        ]
        if kept:
            found[row["id"]] = kept
    return found


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
