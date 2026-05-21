"""SUSAD navaid coordinate-table tests.

Section D subsection ' ' = VHF (VOR/DME), subsection 'B' = NDB. Per
cifparse, both share the lat (32-41) / lon (41-51) and ident (13-17)
columns, so the same primary-record parse handles both.
"""

from __future__ import annotations

from zoa_ref.cifp import get_navaids, Navaid


def test_osi_vor_resolves():
    """OSI is the Woodside VOR/DME — should resolve at ~37.39°N / -122.28°W."""
    navaids = get_navaids()
    assert "OSI" in navaids, "Expected OSI Woodside VOR/DME in navaid table"
    osi = navaids["OSI"]
    assert isinstance(osi, Navaid)
    assert osi.ident == "OSI"
    assert osi.navaid_type == "VHF"
    assert 37.3 < osi.lat < 37.5
    assert -122.4 < osi.lon < -122.1


def test_sfo_vor_resolves():
    navaids = get_navaids()
    assert "SFO" in navaids
    sfo = navaids["SFO"]
    assert sfo.navaid_type == "VHF"
    # SFO VOR/DME on the airport ~37.62°N / -122.37°W
    assert 37.5 < sfo.lat < 37.7
    assert -122.5 < sfo.lon < -122.2


def test_navaid_table_distinguishes_vhf_from_ndb():
    navaids = get_navaids()
    types = {n.navaid_type for n in navaids.values()}
    assert "VHF" in types
    assert "NDB" in types, "Expected at least one NDB in the navaid table"


def test_navaid_table_non_empty():
    navaids = get_navaids()
    # FAA CIFP has thousands of navaids in CONUS
    assert len(navaids) > 100
