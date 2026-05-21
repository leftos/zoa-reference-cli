"""Waypoint description / fix-role column regression tests.

ARINC 424 field 5.17 is 4 chars wide (cols 39-43) split into:
  pos 0 (col 39): Type
  pos 1 (col 40): Performance (fly-over)
  pos 2 (col 41): Phase of flight
  pos 3 (col 42): Fix role (A=IAF, B=IF, F=FAF, M=MAHP, etc.)

zoa-reference-cli's enhanced parse_procedure_leg was reading
waypoint_desc[0] (col 39) when it should read waypoint_desc[3] (col 42).
The legacy parse_approach_record correctly reads line[42].
"""

from __future__ import annotations

from tests.conftest import make_cifp_line
from zoa_ref.cifp import parse_procedure_leg


def test_iaf_marker_at_position_3_of_desc_code():
    """desc_code 'E  A' has Type='E' at pos 0, fix role 'A' (IAF) at pos 3."""
    line = make_cifp_line(
        fac_sub_code="F",
        procedure_id="H28LZ ",
        fix_id="WESLA",
        path_term="IF",
        desc_code="E  A",
    )
    leg = parse_procedure_leg(line, subsection="F")
    assert leg is not None
    assert leg.fix_type == "IAF", (
        f"Expected IAF (from pos 3 of desc_code='E  A'), got {leg.fix_type!r}. "
        "If empty, the parser is reading pos 0 ('E') which is the Type field."
    )


def test_if_marker():
    """desc_code 'E  B' marks the intermediate fix (col 42 = 'B')."""
    line = make_cifp_line(
        fac_sub_code="F",
        procedure_id="H28LZ ",
        fix_id="DUYET",
        path_term="TF",
        desc_code="E  B",
    )
    leg = parse_procedure_leg(line, subsection="F")
    assert leg is not None
    assert leg.fix_type == "IF"


def test_faf_marker():
    """desc_code 'E  F' marks the final approach fix (col 42 = 'F')."""
    line = make_cifp_line(
        fac_sub_code="F",
        procedure_id="H28LZ ",
        fix_id="ARCHI",
        path_term="CF",
        desc_code="E  F",
    )
    leg = parse_procedure_leg(line, subsection="F")
    assert leg is not None
    assert leg.fix_type == "FAF"


def test_mahp_marker():
    """desc_code 'E  M' marks the missed approach holding point."""
    line = make_cifp_line(
        fac_sub_code="F",
        procedure_id="H28LZ ",
        fix_id="OLYMM",
        path_term="HM",
        desc_code="E  M",
    )
    leg = parse_procedure_leg(line, subsection="F")
    assert leg is not None
    assert leg.fix_type == "MAHP"


def test_pos_0_type_code_not_misread_as_fix_role():
    """Type 'E' at pos 0 must not be read as fix role.

    'E' is not in WAYPOINT_DESC_CODES, so a buggy parser would just emit
    "" — but Type can be 'A' (Phantom Fix) or other letters which would
    accidentally match IAF. Use 'A' at pos 0 with empty at pos 3.
    """
    line = make_cifp_line(
        fac_sub_code="E",
        procedure_id="SCOLA1",
        fix_id="LOZIT",
        path_term="TF",
        desc_code="A   ",
    )
    leg = parse_procedure_leg(line, subsection="E")
    assert leg is not None
    assert leg.fix_type == "", (
        f"Expected '' (no fix role at pos 3), got {leg.fix_type!r}. "
        "If 'IAF', the parser is reading pos 0 ('A') instead of pos 3."
    )
