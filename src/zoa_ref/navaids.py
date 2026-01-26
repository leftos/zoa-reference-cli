"""NAVAID data loading and lookup for chart name aliasing.

This module provides navaid lookup functionality using NASR data.
All navaid data is loaded from the FAA NASR NAV.txt file which is
automatically downloaded and cached per AIRAC cycle.

This module re-exports functions from the nasr module for backwards
compatibility.
"""

# Re-export navaid functionality from nasr module
from zoa_ref.nasr import (
    NavaidInfo,
    NavaidSearchResult,
    get_all_identifiers,
    get_all_navaid_identifiers,
    get_navaid_identifier,
    get_navaid_name,
    haversine_distance as _haversine_distance,
    resolve_navaid_alias,
    search_navaids,
)

__all__ = [
    "NavaidInfo",
    "NavaidSearchResult",
    "get_all_identifiers",
    "get_all_navaid_identifiers",
    "get_navaid_identifier",
    "get_navaid_name",
    "resolve_navaid_alias",
    "search_navaids",
    "_haversine_distance",
]
