"""High-level distance and bearing results for named aviation waypoints.

Wraps the low-level functions in waypoints.py in dataclass results that
bundle all computed fields together so callers get a single, self-describing
object instead of a tuple.
"""

from dataclasses import dataclass

from zoa_ref.waypoints import (
    calculate_bearing,
    calculate_distance_nm,
    cardinal_from_bearing,
)


@dataclass
class DistanceResult:
    """Result of a distance query between two named points.

    Attributes:
        distance_nm: Distance in nautical miles.
        bearing_deg: Initial great-circle bearing from from_ident to to_ident, in [0, 360).
        cardinal: 16-point compass direction corresponding to bearing_deg.
        from_ident: Origin identifier as supplied by the caller.
        to_ident: Destination identifier as supplied by the caller.
        from_type: Point type of the origin (``"FIX"``, ``"AIRPORT"``, or ``"NAVAID"``).
        to_type: Point type of the destination.
    """

    distance_nm: float
    bearing_deg: float
    cardinal: str
    from_ident: str
    to_ident: str
    from_type: str
    to_type: str


@dataclass
class BearingResult:
    """Result of a bearing query between two named points.

    Attributes:
        bearing_deg: Initial great-circle bearing from from_ident to to_ident, in [0, 360).
        cardinal: 16-point compass direction corresponding to bearing_deg.
        distance_nm: Distance in nautical miles (computed alongside bearing).
        from_ident: Origin identifier as supplied by the caller.
        to_ident: Destination identifier as supplied by the caller.
        from_type: Point type of the origin (``"FIX"``, ``"AIRPORT"``, or ``"NAVAID"``).
        to_type: Point type of the destination.
    """

    bearing_deg: float
    cardinal: str
    distance_nm: float
    from_ident: str
    to_ident: str
    from_type: str
    to_type: str


def compute_distance(from_ident: str, to_ident: str) -> DistanceResult:
    """Compute distance (and bearing) between two named aviation points.

    Args:
        from_ident: Starting point identifier (fix, airport, or navaid).
        to_ident: Ending point identifier (fix, airport, or navaid).

    Returns:
        DistanceResult with distance, bearing, cardinal direction, and point types.

    Raises:
        ValueError: If either identifier cannot be resolved.
    """
    distance_nm, from_type, to_type = calculate_distance_nm(from_ident, to_ident)
    bearing_deg, _, _ = calculate_bearing(from_ident, to_ident)
    cardinal = cardinal_from_bearing(bearing_deg)

    return DistanceResult(
        distance_nm=distance_nm,
        bearing_deg=bearing_deg,
        cardinal=cardinal,
        from_ident=from_ident.upper(),
        to_ident=to_ident.upper(),
        from_type=from_type,
        to_type=to_type,
    )


def compute_bearing(from_ident: str, to_ident: str) -> BearingResult:
    """Compute bearing (and distance) from one named aviation point to another.

    Args:
        from_ident: Starting point identifier (fix, airport, or navaid).
        to_ident: Ending point identifier (fix, airport, or navaid).

    Returns:
        BearingResult with bearing, cardinal direction, distance, and point types.

    Raises:
        ValueError: If either identifier cannot be resolved.
    """
    bearing_deg, from_type, to_type = calculate_bearing(from_ident, to_ident)
    distance_nm, _, _ = calculate_distance_nm(from_ident, to_ident)
    cardinal = cardinal_from_bearing(bearing_deg)

    return BearingResult(
        bearing_deg=bearing_deg,
        cardinal=cardinal,
        distance_nm=distance_nm,
        from_ident=from_ident.upper(),
        to_ident=to_ident.upper(),
        from_type=from_type,
        to_type=to_type,
    )
