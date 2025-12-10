"""NAVAID data loading and lookup for chart name aliasing."""

import json
import re
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def _load_navaid_data() -> tuple[dict[str, str], dict[str, str]]:
    """
    Load NAVAID data from GeoJSON and build bidirectional mappings.

    Returns:
        Tuple of (name_to_ident, ident_to_name) dictionaries.
        e.g., ({"MUSTANG": "FMG"}, {"FMG": "MUSTANG"})
    """
    geojson_path = Path(__file__).parent / "NAVAID_System.geojson"

    if not geojson_path.exists():
        return {}, {}

    try:
        with open(geojson_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}, {}

    name_to_ident: dict[str, str] = {}
    ident_to_name: dict[str, str] = {}

    for feature in data.get("features", []):
        props = feature.get("properties", {})
        ident = props.get("IDENT", "")
        name = props.get("NAME_TXT", "")

        if ident and name:
            ident_upper = ident.upper()
            name_upper = name.upper()
            name_to_ident[name_upper] = ident_upper
            ident_to_name[ident_upper] = name_upper

    return name_to_ident, ident_to_name


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
