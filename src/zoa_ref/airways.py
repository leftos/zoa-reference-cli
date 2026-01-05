"""Airway lookup from CIFP data.

This module parses FAA CIFP data to extract airway (victor, jet, etc.) information
including the sequence of fixes/waypoints that make up each airway.
"""

import re
from dataclasses import dataclass
from functools import lru_cache

from zoa_ref.cifp import ensure_cifp_data


@dataclass
class AirwayFix:
    """A single fix/waypoint on an airway."""

    identifier: str  # e.g., "MZB", "CARIF", "OCN"
    sequence: int  # Order on the airway
    is_navaid: bool = False  # True if this is a VOR/DME/NDB
    latitude: float | None = None
    longitude: float | None = None

    def __str__(self) -> str:
        return self.identifier


@dataclass
class AirwayInfo:
    """An airway with its sequence of fixes."""

    identifier: str  # e.g., "V23", "J60", "T270"
    fixes: list[AirwayFix]
    min_altitude: int | None = None  # MEA in feet
    max_altitude: int | None = None  # Maximum altitude in feet
    direction: str | None = None  # e.g., "SE to NW", "S to N"

    @property
    def fix_names(self) -> list[str]:
        """Get list of fix identifiers in order."""
        return [f.identifier for f in self.fixes]


@dataclass
class AirwaySearchResult:
    """Result of an airway search."""

    query: str
    airway: AirwayInfo | None
    highlight_fixes: list[str] | None = None  # Fixes to highlight in display


def parse_airway_record(line: str) -> tuple[str, str, int, bool] | None:
    """Parse a single CIFP airway record.

    ARINC 424 airway records (section E, subsection R):
    - Position 1-4: Customer area (SUSA)
    - Position 5: Section code (E = Enroute)
    - Position 6: Subsection code (R = Airways)
    - Position 14-18: Route identifier (e.g., "V23", "J60")
    - Position 26-29: Sequence number
    - Position 30-34: Fix identifier
    - Position 35-36: ICAO region
    - Position 37: Subsection code (D = VOR, B = NDB, A = Enroute waypoint)

    Args:
        line: Raw CIFP record line

    Returns:
        Tuple of (airway_id, fix_identifier, sequence, is_navaid) or None
    """
    if len(line) < 40:
        return None

    # Check record type - must be SUSAER (US, Enroute, Routes)
    if not line.startswith("SUSAER"):
        return None

    # Extract airway identifier (positions 14-18, 0-indexed: 13-17)
    # The format has variable spacing, so we need to find the route ID
    # Looking at the data: "SUSAER       V23         0100MZB  K2D 0V"
    # Route ID appears around position 13, padded with spaces

    # Extract the route section (after SUSAER, before sequence)
    route_section = line[6:22].strip()

    # Route ID is typically V##, J##, T###, Q###, etc.
    route_match = re.match(r"^([VJQT]\d+|[A-Z]\d+)$", route_section)
    if not route_match:
        return None

    airway_id = route_match.group(1)

    # Sequence number: 4 digits after the route section padding
    # It's at a fixed position after the route ID area
    try:
        # Find sequence by looking for 4-digit number pattern after route area
        seq_match = re.search(r"(\d{4})", line[18:30])
        if not seq_match:
            return None
        sequence = int(seq_match.group(1))
    except (ValueError, IndexError):
        return None

    # Fix identifier: 5 characters after sequence
    # Typically starts around position 26-30 after the sequence
    seq_end = 18 + seq_match.end()
    fix_identifier = line[seq_end : seq_end + 5].strip()

    if not fix_identifier:
        return None

    # Check if it's a navaid (VOR/DME/NDB) vs waypoint
    # Position after fix has region code (2 chars) then subsection
    # D = VOR, B = NDB, A/E = Waypoint
    is_navaid = False
    if len(line) > seq_end + 8:
        fix_type = line[seq_end + 7]
        is_navaid = fix_type in ("D", "B")  # VOR or NDB

    return (airway_id, fix_identifier, sequence, is_navaid)


def _compute_direction_and_should_reverse(
    first_lat: float, first_lon: float, last_lat: float, last_lon: float
) -> tuple[str, bool]:
    """Compute cardinal direction and whether to reverse fix order.

    Airways are normalized to display clockwise from W:
    - W to E preferred over E to W
    - N to S preferred over S to N (when roughly N-S oriented)

    Args:
        first_lat, first_lon: Coordinates of first fix
        last_lat, last_lon: Coordinates of last fix

    Returns:
        Tuple of (direction string like "W to E", should_reverse)
    """
    lat_diff = last_lat - first_lat
    lon_diff = last_lon - first_lon

    # Determine cardinal/intercardinal direction
    def get_cardinal(lat_d: float, lon_d: float) -> str:
        # Threshold for considering movement significant in that axis
        threshold = 0.5  # About 30 nm

        ns = ""
        ew = ""

        if abs(lat_d) > threshold:
            ns = "N" if lat_d > 0 else "S"
        if abs(lon_d) > threshold:
            ew = "E" if lon_d > 0 else "W"

        if not ns and not ew:
            # Very short airway, use primary direction
            if abs(lat_d) > abs(lon_d):
                return "N" if lat_d > 0 else "S"
            else:
                return "E" if lon_d > 0 else "W"

        return ns + ew if ns and ew else (ns or ew)

    end_dir = get_cardinal(lat_diff, lon_diff)

    # Determine if we should reverse to get preferred direction
    # Preference: W to E, N to S (clockwise from W)
    should_reverse = False

    # If there's significant E-W movement, prefer W to E
    if abs(lon_diff) > 0.5:
        should_reverse = lon_diff < 0  # Going west, so reverse to go east
    # If primarily N-S oriented, prefer N to S
    elif abs(lat_diff) > 0.5:
        should_reverse = lat_diff > 0  # Going north, so reverse to go south

    if should_reverse:
        # Recompute direction for reversed order
        end_dir = get_cardinal(-lat_diff, -lon_diff)

    start_dir = get_cardinal(
        -lat_diff if not should_reverse else lat_diff,
        -lon_diff if not should_reverse else lon_diff,
    )

    return f"{start_dir} to {end_dir}", should_reverse


@lru_cache(maxsize=128)
def get_airway(airway_id: str) -> AirwayInfo | None:
    """Get all fixes for a specific airway.

    Args:
        airway_id: Airway identifier (e.g., "V23", "J60", "T270")

    Returns:
        AirwayInfo with ordered fixes, or None if not found
    """
    from zoa_ref.waypoints import get_point_coordinates

    cifp_path = ensure_cifp_data()
    if not cifp_path:
        return None

    # Normalize airway ID
    airway_id = airway_id.upper().strip()

    # Collect all fixes for this airway
    fixes: dict[int, tuple[str, bool]] = {}  # sequence -> (fix_id, is_navaid)

    with open(cifp_path, "r", encoding="latin-1") as f:
        for line in f:
            if not line.startswith("SUSAER"):
                continue

            result = parse_airway_record(line)
            if not result:
                continue

            parsed_airway, fix_id, sequence, is_navaid = result

            if parsed_airway == airway_id:
                fixes[sequence] = (fix_id, is_navaid)

    if not fixes:
        return None

    # Sort by sequence and build fix list with coordinates
    sorted_fixes = []
    for seq, (fix_id, is_navaid) in sorted(fixes.items()):
        fix = AirwayFix(identifier=fix_id, sequence=seq, is_navaid=is_navaid)
        # Look up coordinates
        coords = get_point_coordinates(fix_id)
        if coords:
            fix.latitude = coords.latitude
            fix.longitude = coords.longitude
        sorted_fixes.append(fix)

    # Compute direction from first to last fix with coordinates
    # and determine if we should reverse for consistent display order
    direction = None
    fixes_with_coords = [f for f in sorted_fixes if f.latitude is not None]
    if len(fixes_with_coords) >= 2:
        first = fixes_with_coords[0]
        last = fixes_with_coords[-1]
        direction, should_reverse = _compute_direction_and_should_reverse(
            first.latitude, first.longitude, last.latitude, last.longitude
        )
        if should_reverse:
            sorted_fixes = list(reversed(sorted_fixes))

    return AirwayInfo(identifier=airway_id, fixes=sorted_fixes, direction=direction)


def search_airway(
    query: str, highlights: list[str] | None = None
) -> AirwaySearchResult:
    """Search for an airway and optionally highlight fixes.

    Args:
        query: Airway identifier (e.g., "V23", "J60")
        highlights: Optional list of fix identifiers to highlight in results

    Returns:
        AirwaySearchResult with the airway data and highlight info
    """
    airway = get_airway(query)

    highlight_fixes = None
    if highlights and airway:
        # Normalize and validate highlight fixes
        valid_fixes = []
        for h in highlights:
            h_upper = h.upper().strip()
            if h_upper in airway.fix_names:
                valid_fixes.append(h_upper)
        if valid_fixes:
            highlight_fixes = valid_fixes

    return AirwaySearchResult(
        query=query, airway=airway, highlight_fixes=highlight_fixes
    )
