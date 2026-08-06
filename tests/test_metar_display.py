"""Tests for METAR wind formatting in display.py."""

from zoa_ref.display import _format_wind
from zoa_ref.metar import MetarInfo


def _metar(wind_dir, wind_speed, wind_gust=None) -> MetarInfo:
    return MetarInfo(
        station="KSMF",
        name="Sacramento Intl, CA, US",
        raw="",
        temp_c=None,
        dewp_c=None,
        wind_dir=wind_dir,
        wind_speed=wind_speed,
        wind_gust=wind_gust,
        visibility="10",
        altimeter=None,
        flight_category="VFR",
        clouds=[],
        wx_string="",
    )


def test_numeric_wind():
    assert _format_wind(_metar(270, 8)) == "27008KT"


def test_numeric_wind_with_gust():
    assert _format_wind(_metar(90, 15, 25)) == "09015G25KT"


def test_variable_wind():
    assert _format_wind(_metar("VRB", 4)) == "VRB04KT"


def test_calm_wind():
    assert _format_wind(_metar(0, 0)) == "Calm"


def test_missing_wind():
    assert _format_wind(_metar(None, None)) == "Calm"
