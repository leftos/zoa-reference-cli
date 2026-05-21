"""Fly-over flag regression tests.

Position 2 of the 4-char desc_code field (char 40) indicates the waypoint's
performance / fly-over classification:
  ' ' = fly-by (turn anticipated at fix)
  'Y' = fly-over (must cross the fix before turning)

YAAT exposes IsFlyOver on each leg; zoa-ref-cli historically had no flag.
For TRACON training, the distinction matters on STARs where the heading
change at the fix is the cue.
"""

from __future__ import annotations

from tests.conftest import make_cifp_line
from zoa_ref.cifp import parse_procedure_leg


def test_fly_over_y_flag():
    """desc_code 'EY F' marks a fly-over fix."""
    line = make_cifp_line(
        fac_sub_code="E",
        procedure_id="SCOLA1",
        fix_id="MORGN",
        path_term="TF",
        desc_code="EY F",
    )
    leg = parse_procedure_leg(line, subsection="E")
    assert leg is not None
    assert leg.is_fly_over is True
    assert leg.fix_type == "FAF"


def test_fly_by_default():
    """desc_code 'E  F' (space at pos 2) is a fly-by fix."""
    line = make_cifp_line(
        fac_sub_code="E",
        procedure_id="SCOLA1",
        fix_id="MORGN",
        path_term="TF",
        desc_code="E  F",
    )
    leg = parse_procedure_leg(line, subsection="E")
    assert leg is not None
    assert leg.is_fly_over is False


def test_fly_over_default_when_desc_code_short():
    """If desc_code is empty / under 2 chars, is_fly_over defaults False."""
    line = make_cifp_line(
        fac_sub_code="D",
        procedure_id="CNDEL5",
        fix_id="CNDEL",
        path_term="TF",
        desc_code="    ",
    )
    leg = parse_procedure_leg(line, subsection="D")
    assert leg is not None
    assert leg.is_fly_over is False
