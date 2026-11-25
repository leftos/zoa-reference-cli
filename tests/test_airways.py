"""Tests for CIFP airway parsing and display.

CIFP marks the last fix of each continuous stretch of an airway with "E" in
the second character of the waypoint description code (column 41). V108 has
two such breaks inside it: CROIT (no leg to OAKEY) and LIN (no leg to EKR,
Meeker, CO). Fixture lines are verbatim V108 records from the 2611 cycle.
"""

from pathlib import Path

import click
import pytest

from zoa_ref import airways
from zoa_ref.airways import AirwayFix, AirwayInfo, AirwaySearchResult, FixAirwaysResult
from zoa_ref.display import display_airway, display_fix_airways
from zoa_ref.waypoints import WaypointInfo

V108_RECORDS = [
    "SUSAER       V108        0100ROZZAK2EA0E    OL                        11650186     04700     17500                         637062405",
    "SUSAER       V108        0120SGD  K2D 0V    OL                        114001121168 03000     17500                         637082405",
    "SUSAER       V108        0130CROITK2EA0EE   OL                                1141                                         637092611",
    "SUSAER       V108        0140OAKEYK2EA0E    OL                        070901690770 02300     17500                         637102611",
    "SUSAER       V108        0160LIN  K2D 0VE   OL                                0713                                         637122611",
    "SUSAER       V108        0170EKR  K2D 0V    OL                        119003680659 14000     17500                         637132611",
    "SUSAER       V108        0350HLC  K3D 0VE   OL                                0889                                         637312611",
]
V108_FIXES = ["ROZZA", "SGD", "CROIT", "OAKEY", "LIN", "EKR", "HLC"]


def _segment_names(airway: AirwayInfo) -> list[list[str]]:
    return [[fix.identifier for fix in segment] for segment in airway.segments]


@pytest.fixture
def v108(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point the airway reader at the V108 fixture; returns a setter for fix longitudes."""
    cifp_file = tmp_path / "FAACIFP18"
    cifp_file.write_text("\n".join(V108_RECORDS) + "\n", encoding="latin-1")
    monkeypatch.setattr(airways, "ensure_cifp_data", lambda: cifp_file)
    airways.get_airway.cache_clear()

    def place(step: float) -> None:
        coords = {name: WaypointInfo(name, None, 38.0, -122.0 + step * i, "FIX") for i, name in enumerate(V108_FIXES)}
        monkeypatch.setattr("zoa_ref.waypoints.get_point_coordinates", coords.get)

    yield place
    airways.get_airway.cache_clear()


def test_parse_airway_record_reads_end_of_continuous_airway():
    croit = airways.parse_airway_record(V108_RECORDS[2])
    oakey = airways.parse_airway_record(V108_RECORDS[3])
    lin = airways.parse_airway_record(V108_RECORDS[4])

    assert croit.fix_id == "CROIT" and croit.ends_segment
    assert oakey.fix_id == "OAKEY" and not oakey.ends_segment
    assert lin.fix_id == "LIN" and lin.is_navaid and lin.ends_segment


def test_get_airway_splits_at_each_end_mark(v108):
    v108(1.0)

    airway = airways.get_airway("V108")

    assert _segment_names(airway) == [["ROZZA", "SGD", "CROIT"], ["OAKEY", "LIN"], ["EKR", "HLC"]]
    assert airway.fix_names == V108_FIXES


def test_get_airway_reversed_keeps_the_breaks_between_the_same_fixes(v108):
    v108(-1.0)

    airway = airways.get_airway("V108")

    assert _segment_names(airway) == [["HLC", "EKR"], ["LIN", "OAKEY"], ["CROIT", "SGD", "ROZZA"]]


def _v108_info() -> AirwayInfo:
    def seg(*names: str) -> list[AirwayFix]:
        return [AirwayFix(identifier=name, sequence=0) for name in names]

    return AirwayInfo(identifier="V108", segments=[seg("ROZZA", "SGD", "CROIT"), seg("OAKEY", "LIN"), seg("EKR", "HLC")])


def _output(capsys: pytest.CaptureFixture[str]) -> str:
    return click.unstyle(capsys.readouterr().out)


def test_display_airway_shows_each_gap(capsys):
    display_airway(AirwaySearchResult(query="V108", airway=_v108_info()))

    out = _output(capsys)
    assert "7 fixes in 3 segments" in out
    assert "ROZZA..SGD..CROIT\n" in out
    assert "CROIT..OAKEY" not in out
    assert "LIN..EKR" not in out
    assert "no airway between CROIT and OAKEY" in out
    assert "no airway between LIN and EKR" in out


def test_display_airway_single_segment_has_no_gap_line(capsys):
    info = AirwayInfo(identifier="V1", segments=[[AirwayFix(identifier=n, sequence=0) for n in ("AAA", "BBB")]])

    display_airway(AirwaySearchResult(query="V1", airway=info))

    out = _output(capsys)
    assert "2 fixes\n" in out
    assert "AAA..BBB" in out
    assert "no airway between" not in out


def test_display_fix_airways_snippet_stays_inside_the_segment(capsys):
    display_fix_airways(FixAirwaysResult(query="OAKEY", airways=[_v108_info()]))

    out = _output(capsys)
    assert "[OAKEY]..LIN " in out or out.rstrip().endswith("[OAKEY]..LIN")
    assert "CROIT" not in out
    assert "EKR" not in out
