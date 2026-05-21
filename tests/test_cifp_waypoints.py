"""Terminal waypoint (subsection C) coordinate parsing tests."""

from __future__ import annotations

from zoa_ref.cifp import get_terminal_waypoints, _parse_arinc_lat, _parse_arinc_lon


def test_parse_lat_north():
    """N37461570 = N 37° 46' 15.70" = +37.77103..."""
    assert _parse_arinc_lat("N37461570") == _approx(37 + 46 / 60 + 15.70 / 3600)


def test_parse_lat_south():
    assert _parse_arinc_lat("S33510000") == _approx(-(33 + 51 / 60))


def test_parse_lon_west():
    """W121423091 = W 121° 42' 30.91" = -121.70864..."""
    assert _parse_arinc_lon("W121423091") == _approx(-(121 + 42 / 60 + 30.91 / 3600))


def test_parse_lon_east():
    assert _parse_arinc_lon("E150000000") == _approx(150.0)


def test_blank_returns_none():
    assert _parse_arinc_lat("         ") is None
    assert _parse_arinc_lon("          ") is None


def test_terminal_waypoints_ksfo_lookup():
    """KSFO ARCHI waypoint should resolve to ~37.49°N / -121.87°W."""
    waypoints = get_terminal_waypoints("KSFO")
    assert "ARCHI" in waypoints
    lat, lon = waypoints["ARCHI"]
    # ARCHI: N37292687 W121523195 = 37.491°N / -121.875°W roughly
    assert 37.4 < lat < 37.55
    assert -122.0 < lon < -121.8


def _approx(expected: float, tol: float = 1e-6) -> "_Approx":
    return _Approx(expected, tol)


class _Approx:
    def __init__(self, expected, tol):
        self.expected = expected
        self.tol = tol

    def __eq__(self, other):
        if other is None:
            return False
        return abs(other - self.expected) < self.tol

    def __repr__(self):
        return f"{self.expected} ± {self.tol}"
