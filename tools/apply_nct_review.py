#!/usr/bin/env python3
"""Turn the NCT extractor's draft into the reviewed data file.

Dev-only. Applies a committed list of corrections to one exact draft: the first
op binds the list to that draft's hash, so a re-extract from a new document
version fails loud and gets a new review (docs/plans/nct-data-rulings.md is its
starting point). Each later op also guards on the value it expects to find. The
output is written by the extractor's own writer, so the two formats can't drift.

    uv run python tools/apply_nct_review.py --draft .tmp/nct_routes.draft.json \
        --corrections tools/nct_corrections.json \
        --out src/zoa_ref/data/nct_routes.json
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import string
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

EXTRACTOR = Path(__file__).resolve().parent / "extract_nct_routes.py"
RULINGS_DOC = "docs/plans/nct-data-rulings.md"

SETTABLE_FLOWS = frozenset(
    {"SFOW", "SFOE", "SFO10", "SFO19", "SMFS", "SMFN", "RNOS", "RNON", "OAKE", "SJCE"}
)
FLOW_FIELDS = ("table_flows", "flows")
OUTPUT_KEYS = (
    "source",
    "flows",
    "flow_parents",
    "sectors",
    "complexes",
    "aliases",
    "rules",
    "pacp",
    "rows",
)
_ADDED_KEYS = {"flow_parents": {}, "rules": []}
_LABEL_KEYS = ("op", "id", "sector", "page", "letter", "field")

Data = dict[str, Any]


class ReviewError(Exception):
    """A correction doesn't fit the draft, or the result breaks a data rule."""


def _check_expect(what: str, actual: Any, expect: Any) -> None:
    if actual != expect:
        raise ReviewError(f"{what} is {actual!r}, expected {expect!r}")


def _find_row(data: Data, row_id: str) -> Data:
    for row in data["rows"]:
        if row["id"] == row_id:
            return row
    raise ReviewError(f"unknown row id {row_id!r}")


def _set_field(entry: Data, op: Data) -> None:
    field = op["field"]
    if field not in entry:
        raise ReviewError(f"no field {field!r}")
    if op["expect"] == op["value"]:
        raise ReviewError("a no-op: expect equals value")
    _check_expect(field, entry[field], op["expect"])
    entry[field] = op["value"]


def _op_set(data: Data, op: Data) -> None:
    _set_field(_find_row(data, op["id"]), op)


def _op_drop(data: Data, op: Data) -> None:
    row = _find_row(data, op["id"])
    _check_expect("dest_or_route", row["dest_or_route"], op["expect_dest"])
    data["rows"].remove(row)


def _part_aircraft(row: Data, part: Data) -> list[str]:
    unknown = [c for c in part["aircraft"] if c not in row["aircraft"]]
    if unknown:
        raise ReviewError(f"{part['to']}: class {unknown!r} not on the row")
    kept = [c for c in row["aircraft"] if c in part["aircraft"]]
    if not kept:
        raise ReviewError(f"{part['to']}: names no class")
    return kept


def _part_flows(row: Data, part: Data) -> list[str]:
    flows = part["flows"]
    if not flows or (row["flows"] and not set(flows) <= set(row["flows"])):
        raise ReviewError(f"{part['to']}: flows conflict with {row['flows']!r}")
    return list(flows)


def _split_part(row: Data, part: Data, suffix: str) -> Data:
    new = copy.deepcopy(row)
    new["id"] = f"{row['id']}-{suffix}"
    new["to"] = part["to"]
    if "aircraft" in part:
        new["aircraft"] = _part_aircraft(row, part)
    if "flows" in part:
        new["flows"] = _part_flows(row, part)
    if new["aircraft"] == row["aircraft"] and set(new["flows"]) == set(row["flows"]):
        raise ReviewError(f"{part['to']}: doesn't narrow by aircraft or flows")
    return new


def _check_no_class_lost(row: Data, parts: list[Data]) -> None:
    named = [c for part in parts for c in part.get("aircraft", [])]
    lost = [c for c in row["aircraft"] if c not in named]
    if named and lost:
        raise ReviewError(f"classes lost in the split: {lost!r}")


def _op_split_to(data: Data, op: Data) -> None:
    row = _find_row(data, op["id"])
    _check_expect("to", row["to"], op["expect"])
    if len(op["parts"]) < 2:
        raise ReviewError("a split needs at least two parts")
    if len(op["parts"]) > len(string.ascii_lowercase):
        raise ReviewError(f"a split takes at most 26 parts, not {len(op['parts'])}")
    parts = [
        _split_part(row, part, suffix)
        for part, suffix in zip(op["parts"], string.ascii_lowercase, strict=False)
    ]
    _check_no_class_lost(row, op["parts"])
    index = data["rows"].index(row)
    data["rows"][index : index + 1] = parts


def _op_set_pacp(data: Data, op: Data) -> None:
    found = [
        entry
        for entry in data["pacp"]
        if (entry["sector"], entry["page"], entry["letter"])
        == (op["sector"], op["page"], op["letter"])
    ]
    if len(found) != 1:
        raise ReviewError(f"matches {len(found)} P-ACP entries, not one")
    _set_field(found[0], op)


def _step(node: Any, key: str) -> Any:
    """Go one level down: a dict by key, a list of named entries by name."""
    if isinstance(node, dict) and key in node:
        return node[key]
    named = [e for e in node if e.get("name") == key] if isinstance(node, list) else []
    if len(named) != 1:
        raise ReviewError(f"path step {key!r} doesn't resolve to one entry")
    return named[0]


def _op_set_general(data: Data, op: Data) -> None:
    parent: Any = data
    for key in op["path"][:-1]:
        parent = _step(parent, key)
    leaf = op["path"][-1]
    if not isinstance(parent, dict) or leaf not in parent:
        raise ReviewError(f"path end {leaf!r} doesn't resolve")
    _check_expect(leaf, parent[leaf], op["expect"])
    parent[leaf] = op["value"]


def _op_add_sector(data: Data, op: Data) -> None:
    sector = op["sector"]
    sectors = data["sectors"]["nct"]
    if any(existing["name"] == sector["name"] for existing in sectors):
        raise ReviewError(f"sector {sector['name']!r} already exists")
    sectors.append(sector)


def _op_set_flows(data: Data, op: Data) -> None:
    _check_expect("flows block", data["flows"], op["expect"])
    data["flows"] = op["value"]


def _op_add_rule(data: Data, op: Data) -> None:
    if any(rule["id"] == op["id"] for rule in data["rules"]):
        raise ReviewError(f"rule {op['id']!r} already exists")
    data["rules"].append({key: op[key] for key in ("id", "source", "text")})


_OPS: dict[str, Callable[[Data, Data], None]] = {
    "set": _op_set,
    "drop": _op_drop,
    "split_to": _op_split_to,
    "set_pacp": _op_set_pacp,
    "set_general": _op_set_general,
    "add_sector": _op_add_sector,
    "set_flows": _op_set_flows,
    "add_rule": _op_add_rule,
}


def _op_label(index: int, op: Data) -> str:
    """Name an op by its list index and its identifying fields."""
    tokens = [str(op[k]) for k in _LABEL_KEYS if isinstance(op.get(k), (str, int))]
    if isinstance(op.get("path"), list):
        tokens.append("/".join(str(key) for key in op["path"]))
    return f"op {index} ({' '.join(tokens)})"


def _normalised(draft: Data) -> Data:
    """Copy the draft and give it the output's added keys, so ops can guard on them."""
    data = {**copy.deepcopy(_ADDED_KEYS), **copy.deepcopy(draft)}
    if set(data) != set(OUTPUT_KEYS):
        raise ReviewError(f"draft keys are {sorted(draft)}, unlike the output's")
    return data


def _apply_op(data: Data, index: int, op: Data) -> None:
    label = _op_label(index, op)
    handler = _OPS.get(op.get("op", ""))
    if handler is None:
        raise ReviewError(f"{label}: unknown op")
    try:
        handler(data, op)
    except ReviewError as error:
        raise ReviewError(f"{label}: {error}") from error
    except KeyError as error:
        raise ReviewError(f"{label}: missing key {error}") from error


def _flow_problems(entry: Data, name: str) -> list[str]:
    return [
        f"{name} {field}: {flow!r} isn't a settable flow"
        for field in FLOW_FIELDS
        for flow in entry.get(field, [])
        if flow not in SETTABLE_FLOWS
    ]


def _check_flows(data: Data) -> None:
    problems = [p for row in data["rows"] for p in _flow_problems(row, row["id"])]
    for entry in data["pacp"]:
        name = f"P-ACP {entry['sector']} p{entry['page']} {entry['letter']}"
        problems += _flow_problems(entry, name)
    if problems:
        raise ReviewError("\n  ".join(["flows outside the settable list:", *problems]))


def _without_doubts(entry: Data) -> Data:
    return {key: value for key, value in entry.items() if key != "doubts"}


def draft_hash(draft: Data) -> str:
    """Return the draft's SHA-256, independent of how its file is formatted."""
    text = json.dumps(draft, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _check_bound(draft: Data, corrections: list[Data]) -> None:
    """Fail unless the first op binds the corrections to exactly this draft."""
    if not corrections or corrections[0].get("op") != "expect_draft":
        raise ReviewError("op 0: the first op must be expect_draft")
    actual = draft_hash(draft)
    expect = corrections[0].get("sha256")
    if actual != expect:
        raise ReviewError(
            f"op 0 (expect_draft): the draft changed (sha256 {actual}, expected "
            f"{expect}), so it needs a new review; start from {RULINGS_DOC}"
        )


def apply_review(draft: Data, corrections: list[Data]) -> Data:
    """Apply the corrections to the draft and shape the reviewed data.

    Args:
        draft: The extractor's draft; it isn't changed.
        corrections: The ops to apply, in order; the first is ``expect_draft``.

    Returns:
        The reviewed data, with its keys in output order and no ``doubts``.

    Raises:
        ReviewError: The corrections aren't bound to this draft, an op's guard
            doesn't match, naming the op, or a flow field holds something outside
            the settable flows.
    """
    _check_bound(draft, corrections)
    data = _normalised(draft)
    for index, op in enumerate(corrections[1:], start=1):
        _apply_op(data, index, op)
    _check_flows(data)
    data["rows"] = [_without_doubts(row) for row in data["rows"]]
    data["pacp"] = [_without_doubts(entry) for entry in data["pacp"]]
    return {key: data[key] for key in OUTPUT_KEYS}


def _load_extractor() -> ModuleType:
    """Load the extractor by path, since ``tools/`` is not a package."""
    spec = importlib.util.spec_from_file_location("extract_nct_routes", EXTRACTOR)
    if spec is None or spec.loader is None:
        raise ReviewError(f"can't load {EXTRACTOR}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _arguments(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--draft", type=Path, required=True, help="The extractor draft")
    parser.add_argument(
        "--corrections", type=Path, required=True, help="The corrections JSON"
    )
    parser.add_argument("--out", type=Path, required=True, help="The reviewed file")
    return parser.parse_args(argv)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    """Run the applier; return the process exit code."""
    args = _arguments(argv)
    try:
        draft = _read_json(args.draft)
        corrections = _read_json(args.corrections)
        reviewed = apply_review(draft, corrections)
        extractor = _load_extractor()
    except (ReviewError, OSError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    extractor.write_text(args.out, extractor.render_draft(reviewed))
    print(
        f"applied {len(corrections)} ops: rows {len(draft['rows'])} in, "
        f"{len(reviewed['rows'])} out; P-ACP {len(reviewed['pacp'])}; wrote {args.out}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
