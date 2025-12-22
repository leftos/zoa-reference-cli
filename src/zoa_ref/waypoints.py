"""Waypoint/fix/airport coordinate lookup for distance calculations.

This module provides a unified interface to look up coordinates for:
- Navaids (VORs, VORTACs, TACANs) from local NAVAID_System.geojson
- Airports from CIFP PA (airport reference point) records
- Fixes/waypoints from CIFP EA (enroute waypoint) records
"""

from dataclasses import dataclass
from functools import lru_cache

from zoa_ref.cifp import ensure_cifp_data
from zoa_ref.navaids import search_navaids, _haversine_distance


@dataclass
class WaypointInfo:
    """Information about a waypoint/fix/airport/navaid."""

    ident: str
    name: str | None
    latitude: float
    longitude: float
    point_type: str  # "FIX", "AIRPORT", "NAVAID"


def parse_arinc424_latitude(lat_str: str) -> float | None:
    """Parse ARINC 424 latitude format to decimal degrees.

    Format: N/S + DDMMSSSS (degrees, minutes, seconds * 100)
    Example: 'N38573910' = N 38°57'39.10" = 38.960861

    Args:
        lat_str: ARINC 424 latitude string (9 characters)

    Returns:
        Latitude in decimal degrees (positive for N, negative for S)
    """
    if not lat_str or len(lat_str) < 9:
        return None

    try:
        hemisphere = lat_str[0]
        degrees = int(lat_str[1:3])
        minutes = int(lat_str[3:5])
        seconds = int(lat_str[5:7])
        hundredths = int(lat_str[7:9])

        decimal = degrees + minutes / 60 + (seconds + hundredths / 100) / 3600

        if hemisphere == 'S':
            decimal = -decimal

        return decimal
    except (ValueError, IndexError):
        return None


def parse_arinc424_longitude(lon_str: str) -> float | None:
    """Parse ARINC 424 longitude format to decimal degrees.

    Format: E/W + DDDMMSSSS (degrees, minutes, seconds * 100)
    Example: 'W121292540' = W 121°29'25.40" = -121.490389

    Args:
        lon_str: ARINC 424 longitude string (10 characters)

    Returns:
        Longitude in decimal degrees (positive for E, negative for W)
    """
    if not lon_str or len(lon_str) < 10:
        return None

    try:
        hemisphere = lon_str[0]
        degrees = int(lon_str[1:4])
        minutes = int(lon_str[4:6])
        seconds = int(lon_str[6:8])
        hundredths = int(lon_str[8:10])

        decimal = degrees + minutes / 60 + (seconds + hundredths / 100) / 3600

        if hemisphere == 'W':
            decimal = -decimal

        return decimal
    except (ValueError, IndexError):
        return None


@lru_cache(maxsize=1)
def _load_enroute_waypoints() -> dict[str, tuple[float, float]]:
    """Load enroute waypoint coordinates from CIFP data.

    Parses EA (Enroute Waypoint) records from the CIFP file.

    ARINC 424 EA record format (relevant fields):
    - Position 5-6: Section code (EA)
    - Position 14-18: Waypoint identifier
    - Coordinates found by locating N/S marker

    Returns:
        Dict mapping waypoint identifier to (latitude, longitude) tuple
    """
    cifp_path = ensure_cifp_data()
    if not cifp_path:
        return {}

    waypoints: dict[str, tuple[float, float]] = {}

    try:
        with open(cifp_path, "r", encoding="latin-1") as f:
            for line in f:
                if len(line) < 52:
                    continue

                # Check section code - 'EA' for enroute waypoints
                if line[4:6] != 'EA':
                    continue

                # Extract waypoint identifier (positions 14-18, 0-indexed: 13-17)
                ident = line[13:18].strip()
                if not ident:
                    continue

                # Find coordinates by locating N/S marker
                lat_start = -1
                for i in range(28, min(40, len(line))):
                    if line[i] in 'NS':
                        lat_start = i
                        break

                if lat_start < 0 or len(line) < lat_start + 19:
                    continue

                lat_str = line[lat_start:lat_start + 9]
                lon_str = line[lat_start + 9:lat_start + 19]

                lat = parse_arinc424_latitude(lat_str)
                lon = parse_arinc424_longitude(lon_str)

                if lat is not None and lon is not None:
                    waypoints[ident] = (lat, lon)

    except (OSError, IOError):
        pass

    return waypoints


@lru_cache(maxsize=1)
def _load_terminal_waypoints() -> dict[str, tuple[float, float]]:
    """Load terminal waypoint coordinates from CIFP data.

    Parses terminal waypoint records from the CIFP file.
    These are identified by 'SUSAP' prefix and 'C' subsection at position 13.

    Format: SUSAP KSMFK2CTUDOR K20    C     N38591149W121354725...

    Returns:
        Dict mapping waypoint identifier to (latitude, longitude) tuple
    """
    cifp_path = ensure_cifp_data()
    if not cifp_path:
        return {}

    waypoints: dict[str, tuple[float, float]] = {}

    try:
        with open(cifp_path, "r", encoding="latin-1") as f:
            for line in f:
                if len(line) < 52:
                    continue

                # Must start with 'SUSAP' and have 'C' at position 13 (0-indexed: 12)
                # for terminal waypoints
                if not line.startswith('SUSAP'):
                    continue
                if line[12] != 'C':
                    continue

                # Extract waypoint identifier (positions 14-18, 0-indexed: 13-17)
                ident = line[13:18].strip()
                if not ident:
                    continue

                # Skip if already have this waypoint (first occurrence wins)
                if ident in waypoints:
                    continue

                # Find coordinates by locating N/S marker
                lat_start = -1
                for i in range(28, min(45, len(line))):
                    if line[i] in 'NS':
                        lat_start = i
                        break

                if lat_start < 0 or len(line) < lat_start + 19:
                    continue

                lat_str = line[lat_start:lat_start + 9]
                lon_str = line[lat_start + 9:lat_start + 19]

                lat = parse_arinc424_latitude(lat_str)
                lon = parse_arinc424_longitude(lon_str)

                if lat is not None and lon is not None:
                    waypoints[ident] = (lat, lon)

    except (OSError, IOError):
        pass

    return waypoints


@lru_cache(maxsize=1)
def _load_airport_references() -> dict[str, tuple[float, float]]:
    """Load airport reference point coordinates from CIFP data.

    Parses airport reference point records from the CIFP file.
    These are identified by 'SUSAP' prefix and 'A' subsection at position 13.

    FAA CIFP format for airport reference points:
    - Positions 1-5: 'SUSAP' (US Airport procedure)
    - Position 7-10: Airport ICAO code (e.g., 'KSMF')
    - Position 13: Subsection 'A' = Airport Reference Point
    - Positions 32-40: Latitude (N/S + DDMMSSHH)
    - Positions 41-50: Longitude (E/W + DDDMMSSHH)

    Returns:
        Dict mapping airport identifier (with and without K prefix) to coordinates
    """
    cifp_path = ensure_cifp_data()
    if not cifp_path:
        return {}

    airports: dict[str, tuple[float, float]] = {}

    try:
        with open(cifp_path, "r", encoding="latin-1") as f:
            for line in f:
                # Check for airport reference point record
                # Format: SUSAP XXXXK?A... where X is airport code
                if len(line) < 52:
                    continue

                # Must start with 'SUSAP' and have 'A' at position 13 (0-indexed: 12)
                if not line.startswith('SUSAP'):
                    continue
                if line[12] != 'A':
                    continue

                # Extract airport ICAO code (positions 7-10, 0-indexed: 6-9)
                icao = line[6:10].strip()
                if not icao:
                    continue

                # Extract coordinates
                # The format includes status codes before coords
                # Find the N/S/E/W markers to locate coordinates
                # Example: '...086YHN38414360W121352680...'
                # Latitude: N/S + 8 digits, Longitude: E/W + 9 digits
                # Look for latitude starting with N or S after position 28
                lat_start = -1
                for i in range(28, min(35, len(line))):
                    if line[i] in 'NS':
                        lat_start = i
                        break

                if lat_start < 0 or len(line) < lat_start + 19:
                    continue

                lat_str = line[lat_start:lat_start + 9]
                lon_str = line[lat_start + 9:lat_start + 19]

                lat = parse_arinc424_latitude(lat_str)
                lon = parse_arinc424_longitude(lon_str)

                if lat is not None and lon is not None:
                    # Store both with and without K prefix
                    airports[icao] = (lat, lon)
                    if icao.startswith('K'):
                        airports[icao[1:]] = (lat, lon)
                    else:
                        airports['K' + icao] = (lat, lon)

    except (OSError, IOError):
        pass

    return airports


def get_point_coordinates(ident: str) -> WaypointInfo | None:
    """Look up coordinates for a fix, airport, or navaid.

    Search order:
    1. Navaids (from NAVAID_System.geojson) - fastest, local data
    2. Airports (from CIFP PA records)
    3. Terminal waypoints (from CIFP PC records)
    4. Enroute waypoints (from CIFP EA records)

    Args:
        ident: The identifier to look up (e.g., "TUDOR", "KSMF", "FMG")

    Returns:
        WaypointInfo if found, None otherwise
    """
    ident = ident.upper().strip()

    # 1. Try navaid lookup first (local data, fastest)
    navaid_result = search_navaids(ident)
    if navaid_result.results:
        navaid = navaid_result.results[0]  # Closest to OAK VOR
        return WaypointInfo(
            ident=navaid.ident,
            name=navaid.name,
            latitude=navaid.latitude,
            longitude=navaid.longitude,
            point_type="NAVAID",
        )

    # 2. Try airport lookup
    airports = _load_airport_references()
    if ident in airports:
        lat, lon = airports[ident]
        return WaypointInfo(
            ident=ident,
            name=None,
            latitude=lat,
            longitude=lon,
            point_type="AIRPORT",
        )

    # 3. Try terminal waypoint lookup
    terminal_waypoints = _load_terminal_waypoints()
    if ident in terminal_waypoints:
        lat, lon = terminal_waypoints[ident]
        return WaypointInfo(
            ident=ident,
            name=None,
            latitude=lat,
            longitude=lon,
            point_type="FIX",
        )

    # 4. Try enroute waypoint lookup
    enroute_waypoints = _load_enroute_waypoints()
    if ident in enroute_waypoints:
        lat, lon = enroute_waypoints[ident]
        return WaypointInfo(
            ident=ident,
            name=None,
            latitude=lat,
            longitude=lon,
            point_type="FIX",
        )

    return None


def calculate_distance_nm(from_ident: str, to_ident: str) -> tuple[float, str, str]:
    """Calculate distance in nautical miles between two points.

    Args:
        from_ident: Starting point identifier
        to_ident: Ending point identifier

    Returns:
        Tuple of (distance_nm, from_type, to_type)

    Raises:
        ValueError: If either identifier is not found
    """
    from_point = get_point_coordinates(from_ident)
    if not from_point:
        raise ValueError(f"Unknown identifier: {from_ident}")

    to_point = get_point_coordinates(to_ident)
    if not to_point:
        raise ValueError(f"Unknown identifier: {to_ident}")

    distance = _haversine_distance(
        from_point.latitude, from_point.longitude,
        to_point.latitude, to_point.longitude
    )

    return (distance, from_point.point_type, to_point.point_type)
