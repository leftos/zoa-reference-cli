"""Path-terminator classification and HILPT / PT detection tests.

ARINC 424 path terminators relevant to approaches:
  IF/TF/CF/DF/RF — straight-line legs into the procedure
  AF             — arc to fix
  HA/HF/HM       — hold legs (at altitude / to fix / to manual termination)
  PI             — procedure turn
  CA/FA/VA       — climb to altitude legs (typical on missed-approach)
  VM/VI/CI       — vector / intercept legs

A leg with path_terminator in {HA, HF, HM} is a hold; a procedure with
any such hold is in-lieu of a procedure turn (HILPT). A leg with
path_terminator == "PI" is a classical procedure turn.
"""

from __future__ import annotations

from tests.conftest import make_cifp_line
from zoa_ref.cifp import get_procedure_detail, parse_procedure_leg


def test_hf_path_terminator_is_hold_in_lieu():
    line = make_cifp_line(
        fac_sub_code="F",
        procedure_id="H28LZ ",
        fix_id="OLYMM",
        path_term="HF",
    )
    leg = parse_procedure_leg(line, subsection="F")
    assert leg is not None
    assert leg.is_hold is True
    assert leg.is_procedure_turn is False


def test_hm_path_terminator_is_hold():
    line = make_cifp_line(
        fac_sub_code="F",
        procedure_id="I28L  ",
        fix_id="OLYMM",
        path_term="HM",
    )
    leg = parse_procedure_leg(line, subsection="F")
    assert leg is not None
    assert leg.is_hold is True


def test_pi_path_terminator_is_procedure_turn():
    line = make_cifp_line(
        fac_sub_code="F",
        procedure_id="V07   ",
        fix_id="LOM",
        path_term="PI",
    )
    leg = parse_procedure_leg(line, subsection="F")
    assert leg is not None
    assert leg.is_procedure_turn is True
    assert leg.is_hold is False


def test_tf_leg_is_neither_hold_nor_pt():
    line = make_cifp_line(fac_sub_code="E", path_term="TF")
    leg = parse_procedure_leg(line, subsection="E")
    assert leg is not None
    assert leg.is_hold is False
    assert leg.is_procedure_turn is False


def test_sfo_ils_28l_has_hold_at_olymm():
    """SFO ILS 28L: OLYMM HM at the end is the missed-approach hold.

    The detail object exposes has_hold so callers can flag the procedure
    as having a hold somewhere (HILPT or missed-approach hold).
    """
    detail = get_procedure_detail("SFO", "ILS 28L")
    assert detail is not None
    assert detail.has_hold is True


def test_sid_has_no_hold_or_pt():
    detail = get_procedure_detail("OAK", "CNDEL5")
    if detail is None:
        detail = get_procedure_detail("SFO", "OFFSH3")
    assert detail is not None
    assert detail.has_hold is False
    assert detail.has_procedure_turn is False
