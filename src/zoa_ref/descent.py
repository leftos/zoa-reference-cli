"""Descent calculator for 3-degree glideslope calculations."""

from dataclasses import dataclass
from enum import Enum

# 3-degree glideslope: tan(3°) × 6076 ft/nm ≈ 318 ft/nm
FEET_PER_NM = 318.0


class DescentMode(Enum):
    """Calculation mode based on input type."""

    DISTANCE_NEEDED = "distance_needed"  # Calculate NM to reach target altitude
    ALTITUDE_AT_DISTANCE = "altitude_at_distance"  # Calculate altitude after X nm


@dataclass
class DescentResult:
    """Result of a descent calculation."""

    mode: DescentMode
    current_alt: int  # Current altitude in feet
    # For DISTANCE_NEEDED mode
    target_alt: int | None = None  # Target altitude in feet
    distance_needed: float | None = None  # NM required
    # For ALTITUDE_AT_DISTANCE mode
    distance_nm: float | None = None  # Distance traveled
    altitude_at: int | None = None  # Resulting altitude
    altitude_lost: int | None = None  # Feet descended


def parse_altitude(s: str) -> int:
    """Parse FL-style altitude string to feet.

    Args:
        s: Altitude string (e.g., "100" for 10,000 ft, "020" for 2,000 ft)

    Returns:
        Altitude in feet
    """
    return int(s) * 100


def is_distance_input(s: str) -> bool:
    """Determine if input represents distance (vs target altitude).

    Distance inputs are:
    - 1-2 digits (e.g., "5", "25")
    - Contains decimal point (e.g., "12.5")

    Target altitude inputs are:
    - 3 digits (e.g., "020", "100")

    Args:
        s: The second argument string

    Returns:
        True if this is a distance input, False if target altitude
    """
    if "." in s:
        return True
    # Count digits only (ignore leading zeros for length check)
    return len(s) <= 2


def calculate_descent(current_str: str, second_str: str) -> DescentResult:
    """Calculate descent parameters.

    Args:
        current_str: Current altitude in FL-style (e.g., "100" for 10,000 ft)
        second_str: Either target altitude (3 digits) or distance (1-2 digits or decimal)

    Returns:
        DescentResult with calculated values
    """
    current_alt = parse_altitude(current_str)

    if is_distance_input(second_str):
        # Mode: Calculate altitude after descending for X nm
        distance_nm = float(second_str)
        altitude_lost = int(distance_nm * FEET_PER_NM)
        altitude_at = current_alt - altitude_lost

        return DescentResult(
            mode=DescentMode.ALTITUDE_AT_DISTANCE,
            current_alt=current_alt,
            distance_nm=distance_nm,
            altitude_at=altitude_at,
            altitude_lost=altitude_lost,
        )
    else:
        # Mode: Calculate NM needed to reach target altitude
        target_alt = parse_altitude(second_str)
        altitude_change = current_alt - target_alt
        distance_needed = altitude_change / FEET_PER_NM

        return DescentResult(
            mode=DescentMode.DISTANCE_NEEDED,
            current_alt=current_alt,
            target_alt=target_alt,
            distance_needed=distance_needed,
        )
