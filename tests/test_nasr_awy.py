"""Tests for NASR AWY.txt record parsing.

NASR duplicates airway designators between CONUS and Alaska/Hawaii (e.g. V334
exists in both California and Alaska). The records are distinguished by a
one-char airway type at column 10 (blank = CONUS, "A" = Alaska, "H" = Hawaii).
Parsers must keep these separate or the fixes/restrictions merge.

Fixture lines are verbatim records from the 2608 cycle AWY.txt.
"""

from zoa_ref.nasr import _parse_awy1_record, _parse_awy2_record

CONUS_AWY1 = "AWY1V334     1007/09/2026                   000.00000.00008.85188.93015.2505000             BND 17500         03000S BND         BND  NN  16EZOASUNOL*CA                         V334 *OAKEY*CA                                            BND V334 *OAKEY*CA                                                N     0000001"
ALASKA_AWY1 = "AWY1V334 A   1007/09/2026                   000.00000.00016.76198.23011.3707000             BND 175002000            BND         BND  NN     ZANWALUS*AK                         V334 A*CLAMS*AK                         02000             BND                                                           BND N     0000001"
CONUS_AWY2 = "AWY2V334     10SAN JOSE                      VOR/DME                           CA  37-22-28.964N 121-56-40.807W     SJC V334 *SJC*D                                                                                                                                                                                0000002"
ALASKA_AWY2 = "AWY2V334 A   10AUGEY                         REP-PT             FIX            AKPA59-28-10.96N  152-53-19.4W           V334 A*AUGEY*AK                                                                                                                                                                            0000002"


def test_awy2_conus_record():
    airway, fix = _parse_awy2_record(CONUS_AWY2)
    assert airway == "V334"
    assert fix.identifier == "SJC"
    assert fix.sequence == 10
    assert round(fix.latitude, 2) == 37.37
    assert round(fix.longitude, 2) == -121.94


def test_awy2_alaska_record_keyed_separately():
    airway, fix = _parse_awy2_record(ALASKA_AWY2)
    assert airway == "V334A"
    assert fix.identifier == "AUGEY"
    assert fix.sequence == 10


def test_awy1_conus_record():
    airway, restriction = _parse_awy1_record(CONUS_AWY1)
    assert airway == "V334"
    assert restriction.sequence == 10
    assert restriction.mea == 5000


def test_awy1_alaska_record_keyed_separately():
    airway, restriction = _parse_awy1_record(ALASKA_AWY1)
    assert airway == "V334A"
    assert restriction.sequence == 10
    assert restriction.mea == 7000
    assert restriction.moca == 2000
