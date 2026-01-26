"""MEA (Minimum Enroute Altitude) lookup for route analysis.

This module analyzes routes to determine MEA/MOCA altitude requirements
using airway data from the NASR module.
"""

import re
from dataclasses import dataclass

from zoa_ref.nasr import (
    AirwayFix,
    AirwayRestriction,
    load_airway_restrictions,
    load_airways,
)


# --- Data Classes ---


@dataclass
class MeaSegment:
    """Information about an MEA requirement on a route segment."""

    airway: str  # e.g., "V23"
    segment_start: str  # Fix identifier where segment starts
    segment_end: str  # Fix identifier where segment ends
    mea: int  # Required MEA in feet
    moca: int | None  # MOCA in feet (if available)


@dataclass
class MeaResult:
    """Result of MEA analysis for a route."""

    route: str  # Original route string
    altitude: int | None  # Filed/specified altitude in feet (if provided)
    max_mea: int | None  # Maximum MEA required across all airways
    segments: list[MeaSegment]  # All segments with MEA data
    is_safe: bool | None  # True if altitude >= max_mea, None if no altitude given


# --- Backwards compatibility aliases ---
# These are kept for any code that imports from mea directly

AirwaySegmentRestriction = AirwayRestriction
AirwayFixNasr = AirwayFix


def load_airways_nasr() -> dict[str, list[AirwayFix]]:
    """Load all airways from NASR data.

    Deprecated: Use nasr.load_airways() directly.
    """
    return load_airways()


def clear_nasr_cache() -> None:
    """Clear the LRU caches for NASR lookups.

    Deprecated: Use nasr.clear_nasr_cache() directly.
    """
    from zoa_ref.nasr import clear_nasr_cache as _clear
    _clear()


# --- MEA Analysis ---


def get_mea_for_route(route: str, altitude: int | None = None) -> MeaResult:
    """Get MEA requirements for airways in a route.

    Parses the route string, identifies airways used, and looks up
    MEA requirements for each airway segment.

    Args:
        route: Filed route string (e.g., "KSFO V25 SAC J80 RNO KRNO")
        altitude: Optional altitude in feet to check against MEA

    Returns:
        MeaResult with MEA information and safety status
    """
    if not route:
        return MeaResult(
            route=route, altitude=altitude, max_mea=None, segments=[], is_safe=None
        )

    restrictions = load_airway_restrictions()
    airways_data = load_airways()

    if not restrictions:
        return MeaResult(
            route=route, altitude=altitude, max_mea=None, segments=[], is_safe=None
        )

    # Parse route to find airways and their entry/exit points
    parts = route.upper().split()
    segments: list[MeaSegment] = []
    max_mea: int | None = None

    i = 0
    while i < len(parts):
        part = parts[i]

        # Check if this is an airway (V##, J##, T##, Q##)
        if re.match(r"^[VJTQ]\d+$", part):
            airway = part

            # Find entry fix (previous non-airway, non-DCT part)
            entry_fix = None
            for j in range(i - 1, -1, -1):
                prev = parts[j]
                if prev != "DCT" and not re.match(r"^[VJTQ]\d+$", prev):
                    # Skip SID/STAR names
                    if not (re.match(r"^[A-Z]+\d+[A-Z]*$", prev) and len(prev) > 5):
                        entry_fix = prev
                        break

            # Find exit fix (next non-airway, non-DCT part)
            exit_fix = None
            for j in range(i + 1, len(parts)):
                next_part = parts[j]
                if next_part != "DCT" and not re.match(r"^[VJTQ]\d+$", next_part):
                    # Skip SID/STAR names
                    if not (
                        re.match(r"^[A-Z]+\d+[A-Z]*$", next_part) and len(next_part) > 5
                    ):
                        exit_fix = next_part
                        break

            # Look up MEA for this airway
            if airway in restrictions and airway in airways_data:
                airway_restrictions = restrictions[airway]
                airway_fixes = airways_data[airway]

                # Find the sequence range for entry/exit fixes
                entry_seq = None
                exit_seq = None

                for fix in airway_fixes:
                    if entry_fix and fix.identifier == entry_fix:
                        entry_seq = fix.sequence
                    if exit_fix and fix.identifier == exit_fix:
                        exit_seq = fix.sequence

                # Get MEA for segments in the used portion
                for seq, restr in airway_restrictions.items():
                    # Determine if this segment is in our used portion
                    in_range = True
                    if entry_seq is not None and exit_seq is not None:
                        min_seq = min(entry_seq, exit_seq)
                        max_seq = max(entry_seq, exit_seq)
                        # Segment at sequence N is between fix N-1 and fix N
                        in_range = min_seq < seq <= max_seq

                    if in_range and restr.mea is not None:
                        # Find the fix identifiers for this segment
                        segment_end = None
                        segment_start = None
                        for fix in airway_fixes:
                            if fix.sequence == seq:
                                segment_end = fix.identifier
                            elif fix.sequence == seq - 10:  # Typical spacing is 10
                                segment_start = fix.identifier

                        # If we can't find exact fixes, use generic labels
                        if not segment_start:
                            segment_start = f"seq{seq - 10}"
                        if not segment_end:
                            segment_end = f"seq{seq}"

                        segments.append(
                            MeaSegment(
                                airway=airway,
                                segment_start=segment_start,
                                segment_end=segment_end,
                                mea=restr.mea,
                                moca=restr.moca,
                            )
                        )

                        if max_mea is None or restr.mea > max_mea:
                            max_mea = restr.mea

        i += 1

    # Determine safety if altitude provided
    is_safe = None
    if altitude is not None and max_mea is not None:
        is_safe = altitude >= max_mea

    # If altitude provided, filter out segments at or below that altitude
    if altitude is not None:
        segments = [s for s in segments if s.mea > altitude]

    return MeaResult(
        route=route,
        altitude=altitude,
        max_mea=max_mea,
        segments=segments,
        is_safe=is_safe,
    )
