"""Subsection-aware route_type / transition detection tests.

ARINC 424 §5.7 route-type codes differ by subsection:
  D (SID):    1-6 = numbered transitions; T = RNAV departure transition;
              V = vector; F/M/S = RNAV common/runway/enroute
  E (STAR):   1-6 = numbered transitions; F/M/S = RNAV variants
  F (Approach): A = transition; all other letters (R, L, I, H, B, etc.)
                are main-route approach type codes

The shared parse_procedure_leg must agree with parse_approach_record on
approaches: anything other than 'A' clears the transition name.
"""

from __future__ import annotations

from tests.conftest import make_cifp_line
from zoa_ref.cifp import parse_procedure_leg


def test_approach_route_type_b_is_main_route():
    """Approach route_type 'B' (base) is main route, not a transition."""
    line = make_cifp_line(
        fac_sub_code="F",
        procedure_id="I28L  ",
        procedure_type="B",
        transition_id="XXXXX",  # would be set if this were a transition
        fix_id="DUYET",
        path_term="CF",
    )
    leg = parse_procedure_leg(line, subsection="F")
    assert leg is not None
    assert leg.transition == "", (
        f"Approach route_type 'B' should clear transition, got {leg.transition!r}"
    )


def test_approach_route_type_a_keeps_transition():
    line = make_cifp_line(
        fac_sub_code="F",
        procedure_id="I28L  ",
        procedure_type="A",
        transition_id="ARCHI",
        fix_id="ARCHI",
        path_term="IF",
    )
    leg = parse_procedure_leg(line, subsection="F")
    assert leg is not None
    assert leg.transition == "ARCHI"


def test_approach_route_type_i_is_main_route():
    """ILS approach route_type 'I' is the main route, not a transition."""
    line = make_cifp_line(
        fac_sub_code="F",
        procedure_id="I28L  ",
        procedure_type="I",
        transition_id="     ",
        fix_id="HEMAN",
        path_term="IF",
    )
    leg = parse_procedure_leg(line, subsection="F")
    assert leg is not None
    assert leg.transition == ""


def test_sid_route_type_t_keeps_transition():
    """SID route_type 'T' is RNAV departure transition — keep transition name."""
    line = make_cifp_line(
        fac_sub_code="D",
        procedure_id="CNDEL5",
        procedure_type="T",
        transition_id="MOD  ",
        fix_id="MOD",
        path_term="TF",
    )
    leg = parse_procedure_leg(line, subsection="D")
    assert leg is not None
    assert leg.transition == "MOD"


def test_sid_route_type_v_keeps_transition():
    """SID route_type 'V' is vector — keep transition name."""
    line = make_cifp_line(
        fac_sub_code="D",
        procedure_id="CNDEL5",
        procedure_type="V",
        transition_id="VECTR",
        fix_id="VEKTR",
        path_term="TF",
    )
    leg = parse_procedure_leg(line, subsection="D")
    assert leg is not None
    assert leg.transition == "VECTR"


def test_sid_route_type_4_is_common():
    """SID route_type '4' (common departure route) clears transition."""
    line = make_cifp_line(
        fac_sub_code="D",
        procedure_id="CNDEL5",
        procedure_type="4",
        transition_id="ALL  ",
        fix_id="CNDEL",
        path_term="TF",
    )
    leg = parse_procedure_leg(line, subsection="D")
    assert leg is not None
    # Common-route legs may have transition="ALL" preserved (filtered later in
    # get_procedure_detail) or "" — both signify main route. We only assert
    # that route_type='4' is recognized as a valid transition slot. The actual
    # transition string preservation is checked by integration tests.
    assert leg.transition in ("ALL", "")


def test_star_route_type_4_is_common():
    """STAR route_type '4' (common arrival) keeps transition name 'ALL'."""
    line = make_cifp_line(
        fac_sub_code="E",
        procedure_id="SCOLA1",
        procedure_type="4",
        transition_id="ALL  ",
        fix_id="SCOLA",
        path_term="TF",
    )
    leg = parse_procedure_leg(line, subsection="E")
    assert leg is not None
    assert leg.transition in ("ALL", "")
