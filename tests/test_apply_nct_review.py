"""Tests for the review applier, on small synthetic drafts."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_applier() -> ModuleType:
    """Load ``tools/apply_nct_review.py`` by path, since ``tools/`` is not a package."""
    spec = importlib.util.spec_from_file_location(
        "apply_nct_review", REPO_ROOT / "tools" / "apply_nct_review.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


applier = _load_applier()


def _row(row_id: str = "r1", **fields: Any) -> dict[str, Any]:
    row = {
        "id": row_id,
        "to": "Laguna (J) Seca (T/P)",
        "table_flows": [],
        "flows": [],
        "dest_or_route": ["SFO"],
        "aircraft": ["J", "T", "P"],
        "altitude": "5,000 7,000",
        "doubts": ["suspect"],
    }
    row.update(fields)
    return row


def _draft(*rows: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": {"sop": {"version": "1.13"}},
        "flows": {"SFOW": ["SFO landing Runways 01 or 28"]},
        "sectors": {
            "nct": [{"name": "Paradise", "area": "Area E", "symbol": "5P"}],
            "zoa": [],
        },
        "complexes": {},
        "aliases": {},
        "pacp": [
            {
                "sector": "Cedar",
                "flows": ["SFOW"],
                "section": "4-13",
                "page": 55,
                "letter": "a",
                "text": "Protect.",
                "doubts": ["heading"],
            }
        ],
        "rows": list(rows) or [_row()],
    }


def _set(field: str, expect: Any, value: Any, row_id: str = "r1") -> dict[str, Any]:
    return {
        "op": "set",
        "id": row_id,
        "field": field,
        "expect": expect,
        "value": value,
        "why": "test",
    }


def _split(*parts: dict[str, Any]) -> dict[str, Any]:
    return {
        "op": "split_to",
        "id": "r1",
        "expect": "Laguna (J) Seca (T/P)",
        "parts": list(parts),
        "why": "test",
    }


def _bind(draft: dict[str, Any]) -> dict[str, Any]:
    text = json.dumps(draft, ensure_ascii=False, sort_keys=True)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return {"op": "expect_draft", "sha256": digest, "why": "test"}


def _apply(draft: dict[str, Any], ops: list[dict[str, Any]]) -> dict[str, Any]:
    """Apply ops to the draft, bound to it by the first op the applier requires."""
    return applier.apply_review(draft, [_bind(draft), *ops])


def test_expect_draft_matches() -> None:
    draft = _draft()
    out = applier.apply_review(draft, [_bind(draft)])
    assert out["rows"][0]["id"] == "r1"


def test_changed_draft_fails_naming_the_review() -> None:
    bound = _bind(_draft())
    with pytest.raises(applier.ReviewError, match="new review.*nct-data-rulings"):
        applier.apply_review(_draft(_row(altitude="9,000")), [bound])


@pytest.mark.parametrize(
    "ops", [[], [_set("altitude", "5,000 7,000", "5,000 / 7,000")]]
)
def test_missing_expect_draft_fails(ops: list[dict[str, Any]]) -> None:
    with pytest.raises(applier.ReviewError, match="expect_draft"):
        applier.apply_review(_draft(), ops)


def test_set_noop_fails() -> None:
    with pytest.raises(applier.ReviewError, match="no-op"):
        _apply(_draft(), [_set("altitude", "5,000 7,000", "5,000 7,000")])


def test_set_on_a_missing_field_fails() -> None:
    with pytest.raises(applier.ReviewError, match="no field 'nope'"):
        _apply(_draft(), [_set("nope", "x", "y")])


def test_drop_with_wrong_dest_fails() -> None:
    op = {"op": "drop", "id": "r1", "expect_dest": ["OAK"], "why": "test"}
    with pytest.raises(applier.ReviewError, match="op 1 \\(drop r1\\)"):
        _apply(_draft(), [op])


def test_set_general() -> None:
    op = {
        "op": "set_general",
        "path": ["sectors", "nct", "Paradise", "area"],
        "expect": "Area E",
        "value": "Area E CA",
        "why": "test",
    }
    out = _apply(_draft(), [op])
    assert out["sectors"]["nct"][0]["area"] == "Area E CA"
    with pytest.raises(applier.ReviewError, match="sectors/nct/Paradise/area"):
        _apply(_draft(), [op, op])


def test_set_flows() -> None:
    value = {"SFOW": ["SFO landing Runways 28"]}
    expect = {"SFOW": ["SFO landing Runways 01 or 28"]}
    op = {"op": "set_flows", "expect": expect, "value": value, "why": "test"}
    assert _apply(_draft(), [op])["flows"] == value
    with pytest.raises(applier.ReviewError, match="flows block"):
        _apply(_draft(), [op, op])


def test_add_rule() -> None:
    op = {"op": "add_rule", "id": "x-1", "source": "SOP", "text": "T.", "why": "test"}
    out = _apply(_draft(), [op])
    assert out["rules"] == [{"id": "x-1", "source": "SOP", "text": "T."}]
    with pytest.raises(applier.ReviewError, match="rule 'x-1' already exists"):
        _apply(_draft(), [op, op])


def test_unknown_op_fails() -> None:
    with pytest.raises(applier.ReviewError, match="op 1 \\(frob\\): unknown op"):
        _apply(_draft(), [{"op": "frob"}])


def test_op_without_its_name_fails() -> None:
    with pytest.raises(applier.ReviewError, match="unknown op"):
        _apply(_draft(), [{"id": "r1"}])


def test_op_missing_a_key_fails() -> None:
    op = {"op": "set", "id": "r1", "field": "altitude", "expect": "5,000 7,000"}
    with pytest.raises(applier.ReviewError, match="missing key 'value'"):
        _apply(_draft(), [op])


def _pacp_op(letter: str) -> dict[str, Any]:
    return {
        "op": "set_pacp",
        "sector": "Cedar",
        "page": 55,
        "letter": letter,
        "field": "flows",
        "expect": ["SFOW"],
        "value": ["SFOE"],
        "why": "test",
    }


def test_set_pacp_matching_no_entry_fails() -> None:
    with pytest.raises(applier.ReviewError, match="matches 0 P-ACP"):
        _apply(_draft(), [_pacp_op("z")])


def test_set_pacp_matching_two_entries_fails() -> None:
    draft = _draft()
    draft["pacp"].append(copy.deepcopy(draft["pacp"][0]))
    with pytest.raises(applier.ReviewError, match="matches 2 P-ACP"):
        _apply(draft, [_pacp_op("a")])


def test_split_to_with_wrong_expect_fails() -> None:
    op = _split({"to": "Sutro", "flows": ["SFOW"]}, {"to": "Grove", "flows": ["SFOE"]})
    op["expect"] = "Something else"
    with pytest.raises(applier.ReviewError, match="split_to r1.*Something else"):
        _apply(_draft(), [op])


def test_split_to_losing_a_class_fails() -> None:
    op = _split(
        {"to": "Laguna", "aircraft": ["J"]}, {"to": "Seca", "aircraft": ["T", "P"]}
    )
    with pytest.raises(applier.ReviewError, match="lost.*DH8D"):
        _apply(_draft(_row(aircraft=["J", "DH8D", "T", "P"])), [op])


def test_split_to_unknown_class_fails() -> None:
    op = _split(
        {"to": "Laguna", "aircraft": ["J"]}, {"to": "Seca", "aircraft": ["T", "P"]}
    )
    with pytest.raises(applier.ReviewError, match="'P'.*not on the row"):
        _apply(_draft(_row(aircraft=["J", "T"])), [op])


@pytest.mark.parametrize(
    "first",
    [{"to": "Laguna"}, {"to": "Laguna", "aircraft": ["J", "T", "P"]}],
)
def test_split_to_part_must_narrow(first: dict[str, Any]) -> None:
    op = _split(first, {"to": "Seca", "aircraft": ["T", "P"]})
    with pytest.raises(applier.ReviewError, match="Laguna.*narrow"):
        _apply(_draft(), [op])


def test_split_to_needs_two_parts() -> None:
    op = _split({"to": "Laguna", "aircraft": ["J"]})
    with pytest.raises(applier.ReviewError, match="two parts"):
        _apply(_draft(), [op])


def test_split_to_over_26_parts_fails() -> None:
    op = _split(*[{"to": "Laguna", "flows": ["SFOW"]} for _ in range(27)])
    with pytest.raises(applier.ReviewError, match="26 parts"):
        _apply(_draft(), [op])


def test_main_guard_failure_exits_1_and_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    draft = _draft()
    draft_path = tmp_path / "draft.json"
    draft_path.write_text(json.dumps(draft), encoding="utf-8")
    corrections = tmp_path / "corrections.json"
    bad = _set("altitude", "wrong", "5,000 / 7,000")
    corrections.write_text(json.dumps([_bind(draft), bad]), encoding="utf-8")
    out = tmp_path / "out.json"
    code = applier.main(
        [
            "--draft",
            str(draft_path),
            "--corrections",
            str(corrections),
            "--out",
            str(out),
        ]
    )
    assert code == 1
    assert not out.exists()
    assert "op 1 (set r1 altitude)" in capsys.readouterr().err


def test_set_applies() -> None:
    out = _apply(_draft(), [_set("altitude", "5,000 7,000", "5,000 / 7,000")])
    assert out["rows"][0]["altitude"] == "5,000 / 7,000"


def test_set_with_wrong_expect_fails_naming_the_op() -> None:
    with pytest.raises(applier.ReviewError, match=r"op 2 \(set r1 altitude\)"):
        _apply(
            _draft(),
            [
                _set("altitude", "5,000 7,000", "5,000 / 7,000"),
                _set("altitude", "5,000 7,000", "5,000 / 7,000"),
            ],
        )


def test_unknown_id_fails() -> None:
    with pytest.raises(applier.ReviewError, match="nope"):
        _apply(_draft(), [_set("altitude", "x", "y", row_id="nope")])


def test_drop_removes_the_row() -> None:
    draft = _draft(_row("r1"), _row("r2", dest_or_route=[]))
    op = {"op": "drop", "id": "r2", "expect_dest": [], "why": "empty"}
    out = _apply(draft, [op])
    assert [row["id"] for row in out["rows"]] == ["r1"]


def test_split_to_by_class() -> None:
    op = _split(
        {"to": "Laguna", "aircraft": ["J"]}, {"to": "Seca", "aircraft": ["T", "P"]}
    )
    out = _apply(_draft(), [op])
    assert [(r["id"], r["to"], r["aircraft"]) for r in out["rows"]] == [
        ("r1-a", "Laguna", ["J"]),
        ("r1-b", "Seca", ["T", "P"]),
    ]


def test_split_to_by_flow() -> None:
    op = _split({"to": "Sutro", "flows": ["SFOW"]}, {"to": "Grove", "flows": ["SFOE"]})
    out = _apply(_draft(), [op])
    assert [(r["id"], r["to"], r["flows"]) for r in out["rows"]] == [
        ("r1-a", "Sutro", ["SFOW"]),
        ("r1-b", "Grove", ["SFOE"]),
    ]


def test_split_to_empty_intersection_fails() -> None:
    op = _split(
        {"to": "Laguna", "aircraft": ["J"]}, {"to": "Seca", "aircraft": ["T", "P"]}
    )
    with pytest.raises(applier.ReviewError, match="split_to r1"):
        _apply(_draft(_row(aircraft=["J"])), [op])


def test_split_to_conflicting_flow_fails() -> None:
    op = _split({"to": "Sutro", "flows": ["SFOW"]}, {"to": "Grove", "flows": ["SFOE"]})
    with pytest.raises(applier.ReviewError, match="split_to r1.*flows conflict"):
        _apply(_draft(_row(flows=["SFOW", "SMFS"])), [op])


def test_set_pacp() -> None:
    op = {
        "op": "set_pacp",
        "sector": "Cedar",
        "page": 55,
        "letter": "a",
        "field": "flows",
        "expect": ["SFOW"],
        "value": ["SFOE"],
        "why": "test",
    }
    out = _apply(_draft(), [op])
    assert out["pacp"][0]["flows"] == ["SFOE"]


def test_add_sector() -> None:
    sector = {"name": "Turlock", "area": "Area A", "symbol": "1Q"}
    op = {"op": "add_sector", "sector": sector, "why": "test"}
    out = _apply(_draft(), [op])
    assert out["sectors"]["nct"][-1] == sector
    with pytest.raises(applier.ReviewError, match="Turlock"):
        _apply(_draft(), [op, op])


def test_doubts_removed_from_output() -> None:
    out = _apply(_draft(), [])
    assert "doubts" not in out["rows"][0]
    assert "doubts" not in out["pacp"][0]


@pytest.mark.parametrize("field", ["flows", "table_flows"])
def test_out_of_list_flow_fails(field: str) -> None:
    with pytest.raises(applier.ReviewError, match="SJCW"):
        _apply(_draft(_row(**{field: ["SJCW"]})), [])


def test_pacp_out_of_list_flow_fails() -> None:
    draft = _draft()
    draft["pacp"][0]["flows"] = ["SJCW"]
    with pytest.raises(applier.ReviewError, match="SJCW"):
        _apply(draft, [])


@pytest.mark.parametrize("flow", ["SFO10", "SFO19"])
def test_sfoe_subset_flows_are_allowed(flow: str) -> None:
    out = _apply(_draft(_row(table_flows=[flow])), [])
    assert out["rows"][0]["table_flows"] == [flow]


def test_top_level_key_order() -> None:
    draft = _draft()
    before = copy.deepcopy(draft)
    out = _apply(draft, [])
    assert list(out) == [
        "source",
        "flows",
        "flow_parents",
        "sectors",
        "complexes",
        "aliases",
        "rules",
        "pacp",
        "rows",
    ]
    assert draft == before
