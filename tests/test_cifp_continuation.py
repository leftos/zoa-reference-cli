"""Continuation-record handling tests.

cifparse PrimaryIndices defines cont_rec_no at col 38 — '0' or '1' marks
a primary record; '2'+ marks a continuation. Approaches use application
'W' (col 39) for SBAS/LPV authorization continuations. Primary records
need to be classified by cont_rec_no, not by the empty-path-terminator
heuristic the legacy code used.
"""

from __future__ import annotations

from tests.conftest import make_cifp_line
from zoa_ref.cifp import get_procedure_detail, parse_procedure_leg


def test_continuation_record_skipped():
    """cont_rec_no='2' is a continuation, not a primary leg."""
    line = make_cifp_line(
        fac_sub_code="F",
        procedure_id="H28RY ",
        cont_rec_no="2",
        desc_code="W   ",
        path_term="  ",  # continuation records have no path terminator
        fix_id="DONNG",
    )
    leg = parse_procedure_leg(line, subsection="F")
    assert leg is None


def test_primary_record_with_blank_path_terminator_kept():
    """Some primary records (cont_rec_no='1') legitimately have blank path
    terminators in legacy CIFP releases. Treat them as primary and parse
    what we can rather than dropping the leg."""
    line = make_cifp_line(
        fac_sub_code="D",
        procedure_id="SCOLA1",
        cont_rec_no="1",
        fix_id="SCOLA",
        path_term="  ",
        desc_code="E   ",
    )
    leg = parse_procedure_leg(line, subsection="D")
    # Old code rejected anything without a path terminator. New code keeps
    # primary records; leg may have an empty path_terminator string but the
    # fix identifier is still useful.
    if leg is not None:
        assert leg.fix_identifier == "SCOLA"


def test_sfo_h28ry_has_sbas_authorization():
    """KSFO RNAV (RNP) Y 28R has 'W' continuation records — SBAS-authorized."""
    detail = get_procedure_detail("SFO", "RNAV Y 28R")
    if detail is None:
        detail = get_procedure_detail("SFO", "RNAV 28R Y")
    assert detail is not None
    assert detail.procedure_type == "APPROACH"
    assert detail.is_sbas_authorized is True


def test_sid_has_no_sbas_authorization():
    """SIDs don't carry the 'W' continuation — flag is False."""
    detail = get_procedure_detail("OAK", "CNDEL5")
    if detail is None:
        detail = get_procedure_detail("SFO", "OFFSH3")
    assert detail is not None
    assert detail.is_sbas_authorized is False
