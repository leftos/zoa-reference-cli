"""RF-arc geometry decoding tests.

ARINC 424 RF arcs encode:
  arc_radius     (56, 62)  thousandths of NM
  center_fix     (106, 111) 5-char fix ident
  center_fix_*   (112, 116) region / section / subsection (for cross-airport lookup)
"""

from __future__ import annotations

from tests.conftest import make_cifp_line
from zoa_ref.cifp import get_procedure_detail, parse_procedure_leg


def test_arc_radius_thousandths_of_nm():
    """arc_radius '002920' = 2.920 NM."""
    line = make_cifp_line(
        fac_sub_code="F",
        procedure_id="H28RY ",
        fix_id="JOSUF",
        path_term="RF",
        arc_radius="002920",
        center_fix="CFFJZ",
    )
    leg = parse_procedure_leg(line, subsection="F")
    assert leg is not None
    assert leg.path_terminator == "RF"
    assert leg.arc_radius_nm is not None
    assert abs(leg.arc_radius_nm - 2.920) < 1e-6
    assert leg.center_fix == "CFFJZ"


def test_blank_radius_yields_none():
    line = make_cifp_line(arc_radius="      ", center_fix="     ")
    leg = parse_procedure_leg(line, subsection="F")
    assert leg is not None
    assert leg.arc_radius_nm is None
    assert leg.center_fix == ""


def test_sfo_rnav_rnp_28r_y_resolves_arc_center_coords():
    """KSFO RNAV RNP Y 28R has RF transitions with center fixes CFFJZ/CFFJX.

    After parsing, the leg's center_fix_lat/lon should be resolved from
    the airport's subsection-C terminal waypoints.
    """
    detail = get_procedure_detail("SFO", "RNAV Y 28R")
    if detail is None:
        # Fall back to alternate name forms; AIRAC may shift the variant
        detail = get_procedure_detail("SFO", "RNAV 28R Y")
    assert detail is not None
    # Walk all legs (transitions + common) looking for RF
    rf_legs = []
    for legs in detail.transitions.values():
        rf_legs.extend(leg for leg in legs if leg.path_terminator == "RF")
    rf_legs.extend(leg for leg in detail.common_legs if leg.path_terminator == "RF")
    assert rf_legs, "Expected at least one RF leg on SFO RNAV RNP Y 28R"
    for leg in rf_legs:
        assert leg.arc_radius_nm is not None
        assert leg.center_fix
        # CFFJZ / CFFJX live in KSFO's terminal waypoint table; should resolve
        assert leg.center_fix_lat is not None
        assert leg.center_fix_lon is not None
        assert 37.0 < leg.center_fix_lat < 38.0
        assert -123.0 < leg.center_fix_lon < -121.0
