"""NAVAID data loading and lookup for chart name aliasing."""

import json
import math
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

# OAK VOR coordinates for distance sorting
OAK_VOR_LAT = 37.7259
OAK_VOR_LON = -122.2236


@dataclass
class NavaidInfo:
    """NAVAID information entry."""

    ident: str
    name: str
    navaid_type: str  # e.g., "VORTAC", "VOR/DME", "TACAN"
    city: str
    state: str
    latitude: float
    longitude: float


@dataclass
class NavaidSearchResult:
    """Result of a navaid search."""

    query: str
    results: list[NavaidInfo]


@lru_cache(maxsize=1)
def _load_navaid_features() -> list[dict]:
    """Load raw navaid features from GeoJSON.

    Returns:
        List of feature dictionaries from the GeoJSON file.
    """
    geojson_path = Path(__file__).parent / "NAVAID_System.geojson"

    if not geojson_path.exists():
        return []

    try:
        with open(geojson_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []

    return data.get("features", [])


def _haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance in nautical miles between two coordinates using Haversine formula."""
    R = 3440.065  # Earth's radius in nautical miles

    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c


def _distance_from_oak(navaid: "NavaidInfo") -> float:
    """Calculate distance from OAK VOR to a navaid."""
    return _haversine_distance(OAK_VOR_LAT, OAK_VOR_LON, navaid.latitude, navaid.longitude)


def _parse_navaid_type(class_txt: str) -> str:
    """Parse the CLASS_TXT field into a friendly navaid type.

    Examples:
        "H-VORTAC" -> "VORTAC"
        "H-VORW/DME" -> "VOR/DME"
        "H-TACAN" -> "TACAN"
        "HW/DME" -> "VOR/DME"
        "HW" -> "VOR"
    """
    if not class_txt:
        return "UNKNOWN"

    # Remove altitude prefix (H-, L-, T-, etc.)
    cleaned = re.sub(r"^[HLT]-?", "", class_txt)

    # Map common types
    type_map = {
        "VORTAC": "VORTAC",
        "VORTACW": "VORTAC",
        "TACAN": "TACAN",
        "VOR": "VOR",
        "VORW": "VOR",
        "VOR/DME": "VOR/DME",
        "VORW/DME": "VOR/DME",
        "W/DME": "VOR/DME",
        "DME": "DME",
        "NDB": "NDB",
        "NDB/DME": "NDB/DME",
    }

    for key, value in type_map.items():
        if key in cleaned.upper():
            return value

    return cleaned or "UNKNOWN"


@lru_cache(maxsize=1)
def _load_navaid_data() -> tuple[dict[str, str], dict[str, str]]:
    """
    Load NAVAID data from GeoJSON and build bidirectional mappings.

    Returns:
        Tuple of (name_to_ident, ident_to_name) dictionaries.
        e.g., ({"MUSTANG": "FMG"}, {"FMG": "MUSTANG"})
    """
    features = _load_navaid_features()

    name_to_ident: dict[str, str] = {}
    ident_to_name: dict[str, str] = {}

    for feature in features:
        props = feature.get("properties", {})
        ident = props.get("IDENT", "")
        name = props.get("NAME_TXT", "")

        if ident and name:
            ident_upper = ident.upper()
            name_upper = name.upper()
            name_to_ident[name_upper] = ident_upper
            ident_to_name[ident_upper] = name_upper

    return name_to_ident, ident_to_name


def get_all_identifiers() -> list[str]:
    """
    Get all navaid identifiers.

    Returns:
        List of all navaid identifiers (e.g., ["FMG", "SWR", "CCR", ...])
    """
    _, ident_to_name = _load_navaid_data()
    return list(ident_to_name.keys())


def get_navaid_identifier(name: str) -> str | None:
    """
    Look up a navaid identifier by its name.

    Args:
        name: Navaid name (e.g., "MUSTANG", "SQUAW")

    Returns:
        Navaid identifier (e.g., "FMG", "SWR") or None if not found.
    """
    name_to_ident, _ = _load_navaid_data()
    return name_to_ident.get(name.upper())


def get_all_navaid_identifiers(name: str) -> list[str]:
    """
    Look up all navaid identifiers that have a given name.

    Since multiple navaids can share the same name (e.g., "CONCORD" exists
    as both CCR and CON in different locations), this returns all matching
    identifiers.

    Args:
        name: Navaid name (e.g., "CONCORD")

    Returns:
        List of navaid identifiers (e.g., ["CCR", "CON"]).
    """
    features = _load_navaid_features()
    name_upper = name.upper()
    identifiers = []

    for feature in features:
        props = feature.get("properties", {})
        ident = props.get("IDENT", "")
        navaid_name = props.get("NAME_TXT", "")

        if ident and navaid_name and navaid_name.upper() == name_upper:
            identifiers.append(ident.upper())

    return identifiers


def get_navaid_name(ident: str) -> str | None:
    """
    Look up a navaid name by its identifier.

    Args:
        ident: Navaid identifier (e.g., "FMG", "SWR")

    Returns:
        Navaid name (e.g., "MUSTANG", "SQUAW") or None if not found.
    """
    _, ident_to_name = _load_navaid_data()
    return ident_to_name.get(ident.upper())


def resolve_navaid_alias(chart_name: str) -> str:
    """
    Resolve navaid aliases in a chart name.

    Since chart databases typically use navaid names (e.g., "MUSTANG ONE"),
    this converts navaid identifiers to names (e.g., "FMG1" -> "MUSTANG1").

    Args:
        chart_name: Original chart name (e.g., "FMG1", "FMG FIVE")

    Returns:
        Chart name with navaid identifiers replaced by names.
    """
    # Pattern 1: Identifier followed by digit (FMG1, SWR2)
    match = re.match(r"^([A-Z]+)(\d)$", chart_name)
    if match:
        ident_part = match.group(1)
        digit_part = match.group(2)
        name = get_navaid_name(ident_part)
        if name:
            return f"{name}{digit_part}"

    # Pattern 2: Identifier followed by word number (FMG FIVE, SWR TWO)
    parts = chart_name.split()
    if len(parts) >= 2:
        ident_part = parts[0]
        rest = " ".join(parts[1:])
        name = get_navaid_name(ident_part)
        if name:
            return f"{name} {rest}"

    # Pattern 3: Just the identifier (FMG, SWR) - check if it's a navaid
    name = get_navaid_name(chart_name)
    if name:
        return name

    return chart_name


def search_navaids(query: str) -> NavaidSearchResult:
    """
    Search for navaids by identifier or name.

    Searches both the navaid identifier (e.g., "FMG") and the name
    (e.g., "MUSTANG"). Exact matches on identifier are prioritized,
    followed by partial matches on name. When multiple results are found,
    they are sorted by distance from OAK VOR.

    Args:
        query: Search query (identifier or name)

    Returns:
        NavaidSearchResult with matching navaids.
    """
    features = _load_navaid_features()
    query_upper = query.upper().strip()
    results: list[NavaidInfo] = []

    # First pass: exact identifier match
    for feature in features:
        props = feature.get("properties", {})
        ident = props.get("IDENT", "").upper()

        if ident == query_upper:
            coords = feature.get("geometry", {}).get("coordinates", [0, 0])
            results.append(
                NavaidInfo(
                    ident=ident,
                    name=props.get("NAME_TXT", ""),
                    navaid_type=_parse_navaid_type(props.get("CLASS_TXT", "")),
                    city=props.get("CITY", ""),
                    state=props.get("STATE", "") or "",
                    latitude=coords[1] if len(coords) > 1 else 0,
                    longitude=coords[0] if len(coords) > 0 else 0,
                )
            )

    # If exact identifier match found, return it (sorted by distance if multiple)
    if results:
        if len(results) > 1:
            results.sort(key=_distance_from_oak)
        return NavaidSearchResult(query=query, results=results)

    # Second pass: exact name match or partial matches
    exact_name_matches: list[NavaidInfo] = []
    partial_matches: list[NavaidInfo] = []

    for feature in features:
        props = feature.get("properties", {})
        ident = props.get("IDENT", "").upper()
        name = props.get("NAME_TXT", "").upper()

        coords = feature.get("geometry", {}).get("coordinates", [0, 0])
        navaid = NavaidInfo(
            ident=ident,
            name=props.get("NAME_TXT", ""),
            navaid_type=_parse_navaid_type(props.get("CLASS_TXT", "")),
            city=props.get("CITY", ""),
            state=props.get("STATE", "") or "",
            latitude=coords[1] if len(coords) > 1 else 0,
            longitude=coords[0] if len(coords) > 0 else 0,
        )

        if name == query_upper:
            exact_name_matches.append(navaid)
        elif query_upper in name or query_upper in ident:
            partial_matches.append(navaid)

    # Prioritize exact name matches, then partial matches
    # Sort by distance from OAK VOR when multiple results
    if exact_name_matches:
        if len(exact_name_matches) > 1:
            exact_name_matches.sort(key=_distance_from_oak)
        return NavaidSearchResult(query=query, results=exact_name_matches)

    if len(partial_matches) > 1:
        partial_matches.sort(key=_distance_from_oak)
    return NavaidSearchResult(query=query, results=partial_matches)
