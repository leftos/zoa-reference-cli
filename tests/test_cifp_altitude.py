"""Altitude column / scaling regression tests for parse_procedure_leg.

cifparse PrimaryIndices: alt_desc=(82,83), atc=(83,84), alt_1=(84,89),
alt_2=(89,94). Altitude values in 2.0+ are stored as actual feet (no ×10).

zoa-reference-cli historically read line[83:88]/line[88:93] and then
multiplied by 10 to compensate. The shift dropped the leading digit and
the ×10 inflated the result, so a FAF at 1,700 ft could render as FL170.
"""

from __future__ import annotations

from tests.conftest import make_cifp_line
from zoa_ref.cifp import parse_procedure_leg


def test_at_altitude_1700_parses_as_1700_feet():
    """A '01700' in alt_1 with '@' description means at 1,700 ft."""
    line = make_cifp_line(
        fac_sub_code="F",
        procedure_id="I28L  ",
        fix_id="WESLA",
        path_term="CF",
        alt_desc="@",
        alt_1="01700",
    )
    leg = parse_procedure_leg(line, subsection="F")
    assert leg is not None
    assert leg.altitude is not None
    assert leg.altitude.altitude1 == 1700, (
        f"Expected 1700 ft, got {leg.altitude.altitude1}. "
        "If 17000, the ×10 compensator is still in _parse_altitude. "
        "If something else, alt_1 columns are off."
    )


def test_at_or_above_4000_parses_as_4000_feet():
    """A '+' description with '04000' means at or above 4,000 ft."""
    line = make_cifp_line(
        fac_sub_code="F",
        procedure_id="I28L  ",
        fix_id="ARCHI",
        path_term="CF",
        alt_desc="+",
        alt_1="04000",
    )
    leg = parse_procedure_leg(line, subsection="F")
    assert leg is not None
    assert leg.altitude is not None
    assert leg.altitude.description == "+"
    assert leg.altitude.altitude1 == 4000


def test_between_4000_and_6000():
    """'B' (between) with alt_1='04000' alt_2='06000' means 4,000-6,000 ft."""
    line = make_cifp_line(
        fac_sub_code="E",
        procedure_id="SCOLA1",
        fix_id="SCOLA",
        path_term="TF",
        alt_desc="B",
        alt_1="04000",
        alt_2="06000",
    )
    leg = parse_procedure_leg(line, subsection="E")
    assert leg is not None
    assert leg.altitude is not None
    assert leg.altitude.altitude1 == 4000
    assert leg.altitude.altitude2 == 6000


def test_flight_level_280():
    """'FL280' in alt_1 means FL280 = 28,000 ft."""
    line = make_cifp_line(
        fac_sub_code="E",
        procedure_id="SCOLA1",
        fix_id="MORGN",
        path_term="TF",
        alt_desc="@",
        alt_1="FL280",
    )
    leg = parse_procedure_leg(line, subsection="E")
    assert leg is not None
    assert leg.altitude is not None
    assert leg.altitude.altitude1 == 28000


def test_atc_column_83_not_confused_with_altitude():
    """Column 83 is the ATC indicator, not the start of alt_1.

    If the parser still reads line[83:88], a non-space value in the atc
    column will leak into the altitude string and produce garbage.
    """
    line = make_cifp_line(
        fac_sub_code="F",
        procedure_id="I28L  ",
        fix_id="WESLA",
        path_term="CF",
        alt_desc="@",
        atc="9",
        alt_1="01700",
    )
    leg = parse_procedure_leg(line, subsection="F")
    assert leg is not None
    assert leg.altitude is not None
    assert leg.altitude.altitude1 == 1700
