"""MEA (Minimum Enroute Altitude) lookup for route analysis.

This module downloads FAA NASR (National Airspace System Resources) data
to extract MEA/MOCA restrictions for airways and analyzes routes to determine
altitude requirements.

NASR data is downloaded once per 28-day AIRAC cycle and cached locally.
"""

import io
import re
import urllib.request
import urllib.error
import zipfile
from dataclasses import dataclass
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

from zoa_ref.cache import get_current_airac_cycle, CACHE_DIR, AIRAC_EPOCH, CYCLE_DAYS

# NASR download settings
NASR_BASE_URL = "https://nfdc.faa.gov/webContent/28DaySub/"
NASR_TIMEOUT = 120  # seconds for download


# --- Data Classes ---


@dataclass
class AirwaySegmentRestriction:
    """MEA/MOCA altitude restrictions for an airway segment.

    Each segment is identified by its sequence number, which corresponds
    to the point-to-point segment ending at that sequence in the airway.
    """

    airway: str  # e.g., "V23", "J80"
    sequence: int  # Links to AirwayFix sequence (segment ends at this point)
    mea: int | None  # Minimum Enroute Altitude in feet (e.g., 5000)
    mea_opposite: int | None  # MEA for opposite direction (may differ)
    moca: int | None  # Minimum Obstruction Clearance Altitude in feet


@dataclass
class AirwayFixNasr:
    """A fix along an airway with sequence number (from NASR data)."""

    identifier: str  # e.g., "MZB", "SUNOL"
    sequence: int  # Order along the airway
    latitude: float
    longitude: float


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


# --- NASR Cycle Calculation ---


def _get_nasr_cycle_date() -> str:
    """Get the effective date string for current NASR cycle.

    Returns:
        Date string in YYYY-MM-DD format
    """
    today = date.today()
    days_since_epoch = (today - AIRAC_EPOCH).days
    cycle_number = days_since_epoch // CYCLE_DAYS

    effective_date = AIRAC_EPOCH + timedelta(days=cycle_number * CYCLE_DAYS)
    return effective_date.strftime("%Y-%m-%d")


def _get_nasr_cache_path() -> Path:
    """Get the cache directory for NASR data.

    Returns:
        Path to the cached NASR data directory
    """
    cycle_id, _, _ = get_current_airac_cycle()
    return CACHE_DIR / "nasr" / cycle_id


# --- NASR Download and Parsing ---


def _download_nasr_file(url: str, dest_file: Path, quiet: bool = False) -> bool:
    """Download a single NASR zip file and extract its .txt file.

    Args:
        url: URL to download from
        dest_file: Path to save the extracted .txt file
        quiet: If True, suppress print output

    Returns:
        True if successful, False otherwise
    """
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "ZOA-Reference-CLI/1.0"}
        )
        with urllib.request.urlopen(req, timeout=NASR_TIMEOUT) as response:
            zip_data = response.read()

        with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
            # Find the .txt file in the zip
            txt_name = dest_file.stem + ".txt"
            for name in zf.namelist():
                if name.endswith(txt_name) or name == txt_name:
                    with zf.open(name) as src:
                        dest_file.write_bytes(src.read())
                    return True

        if not quiet:
            print(f"{txt_name} not found in {url}")
        return False

    except (urllib.error.URLError, TimeoutError, zipfile.BadZipFile) as e:
        if not quiet:
            print(f"Failed to download {url}: {e}")
        return False


def ensure_nasr_data(quiet: bool = False) -> Path | None:
    """Download NASR data if missing or outdated.

    Auto-downloads new NASR data when a new cycle begins.

    Args:
        quiet: If True, suppress print output

    Returns:
        Path to the NASR data directory, or None if download failed
    """
    cache_path = _get_nasr_cache_path()
    awy_file = cache_path / "AWY.txt"

    # Check if we already have the data
    if awy_file.exists():
        return cache_path

    cache_path.mkdir(parents=True, exist_ok=True)
    cycle_date = _get_nasr_cycle_date()

    # Download AWY.zip
    awy_url = f"{NASR_BASE_URL}{cycle_date}/AWY.zip"

    if not quiet:
        print(f"Downloading NASR airway data from {awy_url}...")
    if not _download_nasr_file(awy_url, awy_file, quiet):
        return None

    if not quiet:
        print(f"NASR data cached to {cache_path}")
    return cache_path


# --- AWY.txt Parsing ---


def _parse_awy1_record(line: str) -> tuple[str, AirwaySegmentRestriction] | None:
    """Parse an AWY.txt AWY1 record line for MEA/MOCA data.

    AWY.txt format is fixed-width. AWY1 records contain altitude restrictions:
    - Positions 0-4: Record type "AWY1"
    - Positions 4-9: Airway designator (e.g., "V27  ", "J1   ")
    - Positions 10-15: Sequence number
    - Positions 74-79: MEA (5 digits, right-justified, e.g., "05000")
    - Positions 85-90: MEA opposite direction (may be blank)
    - Positions 101-106: MOCA (5 digits or blank)

    Args:
        line: Raw AWY.txt record line

    Returns:
        Tuple of (airway_designator, AirwaySegmentRestriction) if valid, None otherwise
    """
    if len(line) < 110:
        return None

    # Only process AWY1 records
    record_type = line[0:4].strip()
    if record_type != "AWY1":
        return None

    try:
        # Extract airway designator (positions 4-9)
        airway = line[4:9].strip()
        if not airway:
            return None

        # Extract sequence number (positions 10-15)
        seq_str = line[10:15].strip()
        if not seq_str:
            return None
        sequence = int(seq_str)

        # Extract MEA (positions 74-79)
        mea_str = line[74:79].strip()
        mea = int(mea_str) if mea_str and mea_str.isdigit() else None

        # Extract MEA opposite direction (positions 85-90)
        mea_opp_str = line[85:90].strip()
        mea_opposite = (
            int(mea_opp_str) if mea_opp_str and mea_opp_str.isdigit() else None
        )

        # Extract MOCA (positions 101-106)
        moca_str = line[101:106].strip()
        moca = int(moca_str) if moca_str and moca_str.isdigit() else None

        # Skip if no altitude data at all
        if mea is None and mea_opposite is None and moca is None:
            return None

        return (
            airway,
            AirwaySegmentRestriction(
                airway=airway,
                sequence=sequence,
                mea=mea,
                mea_opposite=mea_opposite,
                moca=moca,
            ),
        )

    except (IndexError, ValueError):
        return None


def _parse_awy2_record(line: str) -> tuple[str, AirwayFixNasr] | None:
    """Parse an AWY.txt AWY2 record line for fix information.

    AWY.txt format is fixed-width. AWY2 records contain fix details.

    Args:
        line: Raw AWY.txt record line

    Returns:
        Tuple of (airway_designator, AirwayFixNasr) if valid, None otherwise
    """
    if len(line) < 120:
        return None

    # Only process AWY2 records (fix location data)
    record_type = line[0:4].strip()
    if record_type != "AWY2":
        return None

    try:
        # Extract airway designator and sequence number
        header_match = re.match(r"AWY2([A-Z][A-Z0-9]*)\s*(\d+)", line)
        if not header_match:
            return None

        airway = header_match.group(1)
        sequence = int(header_match.group(2))

        # Find latitude and longitude using regex
        lat_match = re.search(r"(\d{2})-(\d{2})-(\d{2}\.?\d*)([NS])", line)
        lon_match = re.search(r"(\d{2,3})-(\d{2})-(\d{2}\.?\d*)([EW])", line)

        if not lat_match or not lon_match:
            return None

        # Parse latitude
        lat_deg = int(lat_match.group(1))
        lat_min = int(lat_match.group(2))
        lat_sec = float(lat_match.group(3)) if lat_match.group(3) else 0.0
        latitude = lat_deg + lat_min / 60 + lat_sec / 3600
        if lat_match.group(4) == "S":
            latitude = -latitude

        # Parse longitude
        lon_deg = int(lon_match.group(1))
        lon_min = int(lon_match.group(2))
        lon_sec = float(lon_match.group(3)) if lon_match.group(3) else 0.0
        longitude = lon_deg + lon_min / 60 + lon_sec / 3600
        if lon_match.group(4) == "W":
            longitude = -longitude

        # Extract fix identifier from the remaining part of the line
        remaining = line[lon_match.end() :]

        fix_id = None

        # Pattern 1: Look for *FIXID* pattern (most common for fixes)
        star_match = re.search(r"\*([A-Z]{2,5})\*", remaining)
        if star_match:
            fix_id = star_match.group(1)
        else:
            # Pattern 2: Look for 3-letter code followed by airway (for VORTACs)
            id_match = re.search(r"\s+([A-Z]{2,5})\s+" + re.escape(airway), remaining)
            if id_match:
                fix_id = id_match.group(1)

        if not fix_id:
            return None

        return (
            airway,
            AirwayFixNasr(
                identifier=fix_id,
                sequence=sequence,
                latitude=latitude,
                longitude=longitude,
            ),
        )

    except (IndexError, ValueError):
        return None


# --- High-Level API ---


@lru_cache(maxsize=1)
def load_airway_restrictions() -> dict[str, dict[int, AirwaySegmentRestriction]]:
    """Load MEA/MOCA restrictions for all airways from NASR data.

    Returns:
        Dict mapping airway designator to dict of sequence -> restriction.
        Example: {"V23": {20: AirwaySegmentRestriction(...), 30: ...}}
    """
    cache_path = ensure_nasr_data(quiet=True)
    if not cache_path:
        return {}

    awy_file = cache_path / "AWY.txt"
    if not awy_file.exists():
        return {}

    restrictions: dict[str, dict[int, AirwaySegmentRestriction]] = {}

    try:
        with open(awy_file, "r", encoding="latin-1") as f:
            for line in f:
                result = _parse_awy1_record(line)
                if result:
                    airway, restriction = result
                    if airway not in restrictions:
                        restrictions[airway] = {}
                    restrictions[airway][restriction.sequence] = restriction

    except (OSError, IOError):
        return {}

    return restrictions


@lru_cache(maxsize=1)
def load_airways_nasr() -> dict[str, list[AirwayFixNasr]]:
    """Load all airways from NASR data.

    Returns:
        Dict mapping airway designator to ordered list of AirwayFixNasr objects
    """
    cache_path = ensure_nasr_data(quiet=True)
    if not cache_path:
        return {}

    awy_file = cache_path / "AWY.txt"
    if not awy_file.exists():
        return {}

    airways: dict[str, list[AirwayFixNasr]] = {}

    try:
        with open(awy_file, "r", encoding="latin-1") as f:
            for line in f:
                result = _parse_awy2_record(line)
                if result:
                    airway, fix = result
                    if airway not in airways:
                        airways[airway] = []
                    airways[airway].append(fix)

        # Sort each airway's fixes by sequence number
        for airway in airways:
            airways[airway].sort(key=lambda f: f.sequence)

    except (OSError, IOError):
        return {}

    return airways


def clear_nasr_cache() -> None:
    """Clear the LRU caches for NASR lookups."""
    load_airway_restrictions.cache_clear()
    load_airways_nasr.cache_clear()


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
    airways_data = load_airways_nasr()

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
