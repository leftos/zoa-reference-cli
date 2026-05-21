"""Missed-approach leg separation tests.

On an approach procedure, the MAP (Missed Approach Point — labeled MAHP in
the current WAYPOINT_DESC_CODES mapping) is the boundary between the
inbound approach and the missed-approach climb-out. Legs sequenced after
the MAP belong to the missed-approach segment, not the inbound approach.
"""

from __future__ import annotations

from zoa_ref.cifp import get_procedure_detail


def test_sfo_ils_28l_missed_approach_legs_split_out():
    """SFO ILS 28L: RW28L is the MAP, OLYMM CF/HM are missed approach."""
    detail = get_procedure_detail("SFO", "ILS 28L")
    assert detail is not None

    inbound_fixes = [leg.fix_identifier for leg in detail.common_legs]
    missed_fixes = [leg.fix_identifier for leg in detail.missed_approach_legs]

    assert "RW28L" in inbound_fixes, (
        "MAP fix RW28L should remain in common_legs as last inbound leg"
    )
    assert "RW28L" not in missed_fixes
    # OLYMM is the actual MAHP/holding fix — must be in missed approach
    assert "OLYMM" in missed_fixes
    # And the OLYMM leg must NOT also be in common_legs
    assert missed_fixes.count("OLYMM") >= 1
    assert "OLYMM" not in inbound_fixes


def test_sid_has_no_missed_approach():
    """SIDs have no MAP, so missed_approach_legs is empty."""
    detail = get_procedure_detail("OAK", "CNDEL5")
    if detail is None:
        # CIFP cache may not have CNDEL5 — try another
        detail = get_procedure_detail("SFO", "OFFSH3")
    assert detail is not None
    assert detail.procedure_type == "SID"
    assert detail.missed_approach_legs == []
