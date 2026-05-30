"""Bearing calculation unit tests.

Covers initial_bearing_deg, cardinal_from_bearing, and calculate_bearing in
zoa_ref.waypoints, plus the compute_bearing/DistanceResult additions in
zoa_ref.distance.
"""

from __future__ import annotations

import pytest

from zoa_ref.waypoints import (
    calculate_bearing,
    cardinal_from_bearing,
    initial_bearing_deg,
)


# ---------------------------------------------------------------------------
# initial_bearing_deg — pure math, no external data
# ---------------------------------------------------------------------------


def test_due_north():
    """Point directly north has bearing 0°."""
    assert initial_bearing_deg(0.0, 0.0, 1.0, 0.0) == pytest.approx(0.0, abs=0.01)


def test_due_east():
    """Point directly east has bearing 90°."""
    assert initial_bearing_deg(0.0, 0.0, 0.0, 1.0) == pytest.approx(90.0, abs=0.01)


def test_due_south():
    """Point directly south has bearing 180°."""
    assert initial_bearing_deg(1.0, 0.0, 0.0, 0.0) == pytest.approx(180.0, abs=0.01)


def test_due_west():
    """Point directly west has bearing 270°."""
    assert initial_bearing_deg(0.0, 1.0, 0.0, 0.0) == pytest.approx(270.0, abs=0.01)


def test_reverse_bearing_differs_by_approx_180():
    """Reverse bearing should be roughly 180° different (not exactly, due to great-circle geometry)."""
    fwd = initial_bearing_deg(37.0, -122.0, 38.5, -121.5)
    rev = initial_bearing_deg(38.5, -121.5, 37.0, -122.0)
    diff = abs(fwd - rev)
    if diff > 180:
        diff = 360 - diff
    assert 170 <= diff <= 190, f"Forward={fwd:.1f}, Reverse={rev:.1f}, diff={diff:.1f}"


def test_result_in_range():
    """Result must always be in [0, 360)."""
    for lat1, lon1, lat2, lon2 in [
        (0.0, 0.0, 1.0, 0.0),
        (0.0, 0.0, 0.0, -1.0),
        (-33.0, 151.0, 51.5, -0.1),
    ]:
        b = initial_bearing_deg(lat1, lon1, lat2, lon2)
        assert 0.0 <= b < 360.0, f"Bearing {b} out of [0, 360)"


# ---------------------------------------------------------------------------
# cardinal_from_bearing — pure logic, no external data
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bearing, expected",
    [
        (0.0, "N"),
        (22.5, "NNE"),
        (45.0, "NE"),
        (67.5, "ENE"),
        (90.0, "E"),
        (112.5, "ESE"),
        (135.0, "SE"),
        (157.5, "SSE"),
        (180.0, "S"),
        (202.5, "SSW"),
        (212.0, "SSW"),
        (225.0, "SW"),
        (247.5, "WSW"),
        (270.0, "W"),
        (292.5, "WNW"),
        (315.0, "NW"),
        (337.5, "NNW"),
        (359.9, "N"),
    ],
)
def test_cardinal_exact_boundaries(bearing: float, expected: str):
    assert cardinal_from_bearing(bearing) == expected


def test_cardinal_360_wraps_to_north():
    """360 degrees should wrap to N, same as 0."""
    assert cardinal_from_bearing(360.0) == "N"


# ---------------------------------------------------------------------------
# calculate_bearing — requires CIFP/NASR data
# ---------------------------------------------------------------------------


def test_ksmf_to_suu_bearing():
    """SMF is ~212° (SSW) from KSMF to SUU — the original bug report case.

    SUU was incorrectly described as 'east of SMF'; this regression guard
    ensures the bearing is SSW, not east.
    """
    try:
        bearing_deg, from_type, to_type = calculate_bearing("KSMF", "SUU")
    except Exception as exc:
        pytest.skip(f"Reference data unavailable: {exc}")

    assert 195 <= bearing_deg <= 230, f"Expected ~212°, got {bearing_deg:.1f}°"

    cardinal = cardinal_from_bearing(bearing_deg)
    assert cardinal in {"S", "SSW", "SW"}, f"Expected SSW-ish cardinal, got {cardinal}"
    assert "E" not in cardinal, f"Cardinal must not contain E (got {cardinal})"


def test_calculate_bearing_unknown_from():
    """Unknown from_ident raises ValueError."""
    with pytest.raises(ValueError, match="Unknown identifier"):
        calculate_bearing("ZZZZZ", "KSMF")


def test_calculate_bearing_unknown_to():
    """Unknown to_ident raises ValueError."""
    with pytest.raises(ValueError, match="Unknown identifier"):
        calculate_bearing("KSMF", "ZZZZZ")


def test_calculate_bearing_returns_three_tuple():
    """Return value is (float, str, str)."""
    try:
        result = calculate_bearing("KSMF", "SUU")
    except Exception as exc:
        pytest.skip(f"Reference data unavailable: {exc}")

    assert len(result) == 3
    bearing_deg, from_type, to_type = result
    assert isinstance(bearing_deg, float)
    assert isinstance(from_type, str)
    assert isinstance(to_type, str)


# ---------------------------------------------------------------------------
# DistanceResult augmentation — bearing_deg and cardinal fields
# ---------------------------------------------------------------------------


def test_compute_distance_has_bearing_fields():
    """DistanceResult must carry bearing_deg and cardinal after augmentation."""
    from zoa_ref.distance import compute_distance

    try:
        result = compute_distance("KSMF", "SUU")
    except Exception as exc:
        pytest.skip(f"Reference data unavailable: {exc}")

    assert hasattr(result, "bearing_deg")
    assert hasattr(result, "cardinal")
    assert isinstance(result.bearing_deg, float)
    assert isinstance(result.cardinal, str)
    assert 0.0 <= result.bearing_deg < 360.0


def test_compute_distance_bearing_matches_cardinal():
    """The cardinal field in DistanceResult must be consistent with bearing_deg."""
    from zoa_ref.distance import compute_distance

    try:
        result = compute_distance("KSMF", "SUU")
    except Exception as exc:
        pytest.skip(f"Reference data unavailable: {exc}")

    assert cardinal_from_bearing(result.bearing_deg) == result.cardinal


# ---------------------------------------------------------------------------
# BearingResult / compute_bearing
# ---------------------------------------------------------------------------


def test_compute_bearing_ksmf_to_suu():
    """compute_bearing for KSMF->SUU must report SSW direction."""
    from zoa_ref.distance import compute_bearing

    try:
        result = compute_bearing("KSMF", "SUU")
    except Exception as exc:
        pytest.skip(f"Reference data unavailable: {exc}")

    assert result.bearing_deg == pytest.approx(211.8, abs=1.0)
    assert result.cardinal == "SSW"
    assert result.distance_nm > 0
    assert result.from_ident == "KSMF"
    assert result.to_ident == "SUU"


def test_compute_bearing_unknown_raises():
    """compute_bearing propagates ValueError for unknown identifiers."""
    from zoa_ref.distance import compute_bearing

    with pytest.raises(ValueError, match="Unknown identifier"):
        compute_bearing("ZZZZZ", "KSMF")
