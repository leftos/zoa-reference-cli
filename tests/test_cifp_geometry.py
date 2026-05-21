"""Geometry / navigation field decoding tests.

cifparse PrimaryIndices:
  rec_vhf      (50, 54)  recommended VHF navaid ident
  theta        (62, 66)  recommended navaid radial, tenths of degrees magnetic
  rho          (66, 70)  distance from recommended navaid, tenths of NM
  course       (70, 74)  outbound course / heading, tenths of degrees magnetic
  dist_time    (74, 78)  leg distance, tenths of NM (or holding time)
  vert_angle   (102, 106) vertical path angle, hundredths of degrees (signed)
"""

from __future__ import annotations

from tests.conftest import make_cifp_line
from zoa_ref.cifp import parse_procedure_leg


def test_outbound_course_tenths_of_degrees():
    """course '0900' = 090.0°."""
    line = make_cifp_line(
        fac_sub_code="E",
        procedure_id="SCOLA1",
        fix_id="MORGN",
        path_term="CF",
        course="0900",
    )
    leg = parse_procedure_leg(line, subsection="E")
    assert leg is not None
    assert leg.outbound_course == 90.0


def test_outbound_course_270_5_degrees():
    """course '2705' = 270.5°."""
    line = make_cifp_line(
        fac_sub_code="F",
        procedure_id="I28L  ",
        fix_id="DUYET",
        path_term="CF",
        course="2705",
    )
    leg = parse_procedure_leg(line, subsection="F")
    assert leg is not None
    assert leg.outbound_course == 270.5


def test_outbound_course_blank_yields_none():
    line = make_cifp_line(course="    ")
    leg = parse_procedure_leg(line, subsection="F")
    assert leg is not None
    assert leg.outbound_course is None


def test_leg_distance_nm_tenths():
    """dist_time '0048' = 4.8 NM."""
    line = make_cifp_line(
        fac_sub_code="E",
        procedure_id="SCOLA1",
        fix_id="MORGN",
        path_term="TF",
        dist_time="0048",
    )
    leg = parse_procedure_leg(line, subsection="E")
    assert leg is not None
    assert leg.leg_distance_nm == 4.8


def test_recommended_navaid_ident():
    line = make_cifp_line(
        fac_sub_code="F",
        procedure_id="I28L  ",
        fix_id="DUYET",
        path_term="CF",
        rec_vhf="OSI ",
    )
    leg = parse_procedure_leg(line, subsection="F")
    assert leg is not None
    assert leg.rec_navaid == "OSI"


def test_theta_rho_decoded_as_tenths():
    """theta '1234' = 123.4°, rho '0205' = 20.5 NM."""
    line = make_cifp_line(
        fac_sub_code="F",
        procedure_id="I28L  ",
        fix_id="DUYET",
        path_term="CF",
        theta="1234",
        rho="0205",
    )
    leg = parse_procedure_leg(line, subsection="F")
    assert leg is not None
    assert leg.theta == 123.4
    assert leg.rho == 20.5


def test_vertical_angle_negative_glide_path():
    """vert_angle '-285' = -2.85° glide path."""
    line = make_cifp_line(
        fac_sub_code="F",
        procedure_id="I28L  ",
        fix_id="RW28L",
        path_term="CF",
        vert_angle="-285",
    )
    leg = parse_procedure_leg(line, subsection="F")
    assert leg is not None
    assert leg.vertical_angle == -2.85


def test_blank_geometry_fields_are_none():
    line = make_cifp_line()
    leg = parse_procedure_leg(line, subsection="F")
    assert leg is not None
    assert leg.outbound_course is None
    assert leg.leg_distance_nm is None
    assert leg.rec_navaid == ""
    assert leg.theta is None
    assert leg.rho is None
    assert leg.vertical_angle is None
