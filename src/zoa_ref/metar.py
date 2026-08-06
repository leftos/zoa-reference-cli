"""METAR lookup from aviationweather.gov."""

import json
from dataclasses import dataclass
from urllib.request import urlopen, Request
from urllib.error import URLError

METAR_API_URL = "https://aviationweather.gov/api/data/metar"


@dataclass
class MetarInfo:
    """Parsed METAR information."""

    station: str
    name: str
    raw: str
    temp_c: float | None
    dewp_c: float | None
    wind_dir: int | str | None
    wind_speed: int | None
    wind_gust: int | None
    visibility: str
    altimeter: float | None
    flight_category: str
    clouds: list[dict]
    wx_string: str


def _normalize_station(station: str) -> str:
    """Ensure station ID is ICAO format (4 chars, K-prefixed for US)."""
    station = station.upper().strip()
    if len(station) == 3:
        station = "K" + station
    return station


def fetch_metar(station: str) -> MetarInfo | None:
    """Fetch latest METAR for a station from aviationweather.gov.

    Args:
        station: ICAO or FAA identifier (e.g., KSFO or SFO).

    Returns:
        MetarInfo or None if fetch failed.
    """
    icao = _normalize_station(station)
    url = f"{METAR_API_URL}?ids={icao}&format=json"

    req = Request(url, headers={"User-Agent": "zoa-ref-cli/1.0"})
    try:
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
    except (URLError, json.JSONDecodeError, TimeoutError) as exc:
        raise RuntimeError(f"Failed to fetch METAR for {icao}: {exc}") from exc

    if not data:
        return None

    obs = data[0]

    clouds = obs.get("clouds", [])
    if clouds is None:
        clouds = []

    return MetarInfo(
        station=obs.get("icaoId", icao),
        name=obs.get("name", ""),
        raw=obs.get("rawOb", ""),
        temp_c=obs.get("temp"),
        dewp_c=obs.get("dewp"),
        wind_dir=obs.get("wdir"),
        wind_speed=obs.get("wspd"),
        wind_gust=obs.get("wgst"),
        visibility=str(obs.get("visib", "")),
        altimeter=obs.get("altim"),
        flight_category=obs.get("fltCat", ""),
        clouds=clouds,
        wx_string=obs.get("wxString", "") or "",
    )


def fetch_metars(stations: list[str]) -> list[MetarInfo]:
    """Fetch METARs for multiple stations in a single request."""
    icao_ids = [_normalize_station(s) for s in stations]
    ids_param = ",".join(icao_ids)
    url = f"{METAR_API_URL}?ids={ids_param}&format=json"

    req = Request(url, headers={"User-Agent": "zoa-ref-cli/1.0"})
    try:
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
    except (URLError, json.JSONDecodeError, TimeoutError) as exc:
        raise RuntimeError(f"Failed to fetch METARs: {exc}") from exc

    if not data:
        return []

    results = []
    for obs in data:
        clouds = obs.get("clouds", [])
        if clouds is None:
            clouds = []

        results.append(
            MetarInfo(
                station=obs.get("icaoId", ""),
                name=obs.get("name", ""),
                raw=obs.get("rawOb", ""),
                temp_c=obs.get("temp"),
                dewp_c=obs.get("dewp"),
                wind_dir=obs.get("wdir"),
                wind_speed=obs.get("wspd"),
                wind_gust=obs.get("wgst"),
                visibility=str(obs.get("visib", "")),
                altimeter=obs.get("altim"),
                flight_category=obs.get("fltCat", ""),
                clouds=clouds,
                wx_string=obs.get("wxString", "") or "",
            )
        )
    return results
