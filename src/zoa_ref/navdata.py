"""Navdata API client for STAR/arrival procedure data.

The navdata API at navdata.oakartcc.org provides structured STAR data
including waypoints, transitions, and altitude restrictions. This is more
reliable than OCR extraction from PDF charts.
"""

import json
import re
import urllib.request
import urllib.error
from dataclasses import dataclass
from functools import lru_cache


NAVDATA_BASE_URL = "https://navdata.oakartcc.org"
REQUEST_TIMEOUT = 10


@dataclass
class NavdataSTAR:
    """STAR data from the navdata API."""

    identifier: str
    waypoints: list[str]
    transitions: list[str]


def fetch_arrivals(airport: str) -> list[dict] | None:
    """Fetch all arrival procedures for an airport from the navdata API.

    Args:
        airport: Airport code (e.g., "RNO", "SMF"). Can include K prefix.

    Returns:
        List of arrival procedure dicts, or None if request failed.
    """
    # Normalize airport code - remove K prefix if present
    apt = airport.upper().lstrip("K")

    url = f"{NAVDATA_BASE_URL}/arrivals/{apt}"

    try:
        with urllib.request.urlopen(url, timeout=REQUEST_TIMEOUT) as response:
            data = json.loads(response.read().decode())
            # API returns empty array if no data
            return data if data else None
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError):
        return None


def extract_waypoints_from_arrival(arrival: dict) -> list[str]:
    """Extract all unique waypoints from an arrival procedure.

    Collects waypoints from all sequences/transitions in the arrival.

    Args:
        arrival: Arrival dict from the navdata API

    Returns:
        Sorted list of unique 5-letter waypoint identifiers
    """
    waypoints = set()

    for sequence in arrival.get("sequences", []):
        for point in sequence.get("points", []):
            identifier = point.get("identifier", "")
            # Only include 5-letter waypoints (fixes), not navaids like "FMG"
            # But also include 3-letter navaids as they can be STAR endpoints
            if identifier and 3 <= len(identifier) <= 5:
                waypoints.add(identifier.upper())

    return sorted(waypoints)


def extract_transitions_from_arrival(arrival: dict) -> list[str]:
    """Extract all transition names from an arrival procedure.

    Args:
        arrival: Arrival dict from the navdata API

    Returns:
        List of transition names (entry points into the STAR)
    """
    transitions = []
    for sequence in arrival.get("sequences", []):
        transition = sequence.get("transition", "")
        trans_type = sequence.get("transitionType", "")
        # Only include enroute transitions (entry points), not runway transitions
        if transition and "Enroute" in trans_type:
            if transition not in transitions:
                transitions.append(transition)
    return transitions


def normalize_star_name(name: str) -> str:
    """Normalize a STAR name for matching.

    Converts shorthand like "SCOLA1" to match API format "SCOLA1".
    The API uses the abbreviated form with digits.

    Args:
        name: STAR name (e.g., "SCOLA1", "SCOLA ONE", "SCOLA 1")

    Returns:
        Normalized name for API matching
    """
    name = name.upper().strip()

    # If already in short form (e.g., "SCOLA1"), return as-is
    if re.match(r"^[A-Z]+\d$", name):
        return name

    # Convert word numbers to digits
    word_to_digit = {
        "ONE": "1", "TWO": "2", "THREE": "3", "FOUR": "4", "FIVE": "5",
        "SIX": "6", "SEVEN": "7", "EIGHT": "8", "NINE": "9",
    }

    # Handle "SCOLA ONE" or "SCOLA 1" format
    for word, digit in word_to_digit.items():
        # "SCOLA ONE" -> "SCOLA1"
        if name.endswith(f" {word}"):
            return name.replace(f" {word}", digit)
        # "SCOLA 1" -> "SCOLA1"
        if name.endswith(f" {digit}"):
            return name.replace(f" {digit}", digit)

    return name


def find_star_in_arrivals(arrivals: list[dict], star_name: str) -> dict | None:
    """Find a specific STAR in the arrivals list.

    Args:
        arrivals: List of arrival dicts from the API
        star_name: STAR name to find (e.g., "SCOLA1", "SCOLA ONE")

    Returns:
        Matching arrival dict, or None if not found
    """
    normalized = normalize_star_name(star_name)

    for arrival in arrivals:
        arr_id = arrival.get("arrivalIdentifier", "").upper()
        if arr_id == normalized:
            return arrival

    # Fuzzy match - check if the base name matches
    base_name = re.match(r"^([A-Z]+)", normalized)
    if base_name:
        base = base_name.group(1)
        for arrival in arrivals:
            arr_id = arrival.get("arrivalIdentifier", "").upper()
            if arr_id.startswith(base):
                return arrival

    return None


def get_star_data(airport: str, star_name: str) -> NavdataSTAR | None:
    """Get STAR waypoints and transitions from the navdata API.

    Args:
        airport: Airport code (e.g., "RNO")
        star_name: STAR name (e.g., "SCOLA1", "SCOLA ONE")

    Returns:
        NavdataSTAR with waypoints and transitions, or None if not found
    """
    arrivals = fetch_arrivals(airport)
    if not arrivals:
        return None

    arrival = find_star_in_arrivals(arrivals, star_name)
    if not arrival:
        return None

    waypoints = extract_waypoints_from_arrival(arrival)
    transitions = extract_transitions_from_arrival(arrival)

    return NavdataSTAR(
        identifier=arrival.get("arrivalIdentifier", star_name.upper()),
        waypoints=waypoints,
        transitions=transitions,
    )


@lru_cache(maxsize=32)
def get_all_stars_cached(airport: str) -> dict[str, NavdataSTAR] | None:
    """Get all STARs for an airport (cached).

    Args:
        airport: Airport code

    Returns:
        Dict mapping STAR identifier to NavdataSTAR, or None if unavailable
    """
    arrivals = fetch_arrivals(airport)
    if not arrivals:
        return None

    stars = {}
    for arrival in arrivals:
        identifier = arrival.get("arrivalIdentifier", "")
        if identifier:
            waypoints = extract_waypoints_from_arrival(arrival)
            transitions = extract_transitions_from_arrival(arrival)
            stars[identifier.upper()] = NavdataSTAR(
                identifier=identifier,
                waypoints=waypoints,
                transitions=transitions,
            )

    return stars if stars else None
