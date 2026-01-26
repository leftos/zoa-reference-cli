"""FAA NASR (National Airspace System Resources) data parser.

This module downloads and parses FAA NASR data to extract navigation aids,
airways, and other aeronautical information. NASR data is published every
28 days aligned with AIRAC cycles.

Data is cached locally per cycle and automatically refreshed when a new
cycle begins.
"""

import io
import math
import re
import urllib.request
import urllib.error
import zipfile
from dataclasses import dataclass
from datetime import timedelta
from functools import lru_cache
from pathlib import Path

from zoa_ref.cache import get_current_airac_cycle, CACHE_DIR, AIRAC_EPOCH, CYCLE_DAYS


# NASR download settings
NASR_BASE_URL = "https://nfdc.faa.gov/webContent/28DaySub/"
NASR_TIMEOUT = 120  # seconds for download

# OAK VOR coordinates for distance sorting
OAK_VOR_LAT = 37.7259
OAK_VOR_LON = -122.2236


# --- Data Classes ---


@dataclass
class NavaidInfo:
    """NAVAID information from NASR data."""

    ident: str  # e.g., "FMG", "OAK"
    name: str  # e.g., "MUSTANG", "OAKLAND"
    navaid_type: str  # e.g., "VORTAC", "VOR/DME", "TACAN"
    city: str  # e.g., "OAKLAND"
    state: str  # e.g., "CA" (2-letter code)
    latitude: float
    longitude: float


@dataclass
class NavaidSearchResult:
    """Result of a navaid search."""

    query: str
    results: list[NavaidInfo]


@dataclass
class AirwayFix:
    """A fix along an airway with sequence number."""

    identifier: str  # e.g., "MZB", "SUNOL"
    sequence: int  # Order along the airway
    latitude: float
    longitude: float


@dataclass
class AirwayRestriction:
    """MEA/MOCA altitude restrictions for an airway segment."""

    airway: str  # e.g., "V23", "J80"
    sequence: int  # Links to AirwayFix sequence (segment ends at this point)
    mea: int | None  # Minimum Enroute Altitude in feet
    mea_opposite: int | None  # MEA for opposite direction (may differ)
    moca: int | None  # Minimum Obstruction Clearance Altitude in feet


# --- NASR Cycle and Download Management ---


def _get_nasr_cycle_date() -> str:
    """Get the effective date string for current NASR cycle.

    Returns:
        Date string in YYYY-MM-DD format
    """
    from datetime import date

    today = date.today()
    days_since_epoch = (today - AIRAC_EPOCH).days
    cycle_number = days_since_epoch // CYCLE_DAYS

    effective_date = AIRAC_EPOCH + timedelta(days=cycle_number * CYCLE_DAYS)
    return effective_date.strftime("%Y-%m-%d")


def get_nasr_cache_path() -> Path:
    """Get the cache directory for NASR data.

    Returns:
        Path to the cached NASR data directory
    """
    cycle_id, _, _ = get_current_airac_cycle()
    return CACHE_DIR / "nasr" / cycle_id


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


def ensure_nasr_data(files: list[str] | None = None, quiet: bool = False) -> Path | None:
    """Download NASR data files if missing or outdated.

    Auto-downloads new NASR data when a new cycle begins.

    Args:
        files: List of file stems to download (e.g., ["NAV", "AWY"]).
               Defaults to ["NAV"] if None.
        quiet: If True, suppress print output

    Returns:
        Path to the NASR data directory, or None if download failed
    """
    if files is None:
        files = ["NAV"]

    cache_path = get_nasr_cache_path()
    cycle_date = _get_nasr_cycle_date()

    # Check which files need downloading
    files_to_download = []
    for file_stem in files:
        file_path = cache_path / f"{file_stem}.txt"
        if not file_path.exists():
            files_to_download.append(file_stem)

    if not files_to_download:
        return cache_path

    cache_path.mkdir(parents=True, exist_ok=True)

    for file_stem in files_to_download:
        url = f"{NASR_BASE_URL}{cycle_date}/{file_stem}.zip"
        dest_file = cache_path / f"{file_stem}.txt"

        if not quiet:
            print(f"Downloading NASR {file_stem} data...")
        if not _download_nasr_file(url, dest_file, quiet):
            return None

    if not quiet:
        print(f"NASR data cached to {cache_path}")
    return cache_path


# --- Coordinate Utilities ---


def _parse_nasr_latitude(lat_str: str) -> float | None:
    """Parse NASR formatted latitude to decimal degrees.

    Format: DD-MM-SS.SSSH where H is hemisphere (N/S)
    Example: "37-43-33.240N" -> 37.7259

    Args:
        lat_str: NASR latitude string (14 characters)

    Returns:
        Latitude in decimal degrees (positive for N, negative for S)
    """
    lat_str = lat_str.strip()
    if not lat_str:
        return None

    try:
        # Match pattern: DD-MM-SS.SSSH
        match = re.match(r"(\d{2})-(\d{2})-([\d.]+)([NS])", lat_str)
        if not match:
            return None

        degrees = int(match.group(1))
        minutes = int(match.group(2))
        seconds = float(match.group(3))
        hemisphere = match.group(4)

        decimal = degrees + minutes / 60 + seconds / 3600

        if hemisphere == "S":
            decimal = -decimal

        return decimal
    except (ValueError, AttributeError):
        return None


def _parse_nasr_longitude(lon_str: str) -> float | None:
    """Parse NASR formatted longitude to decimal degrees.

    Format: DDD-MM-SS.SSSH where H is hemisphere (E/W)
    Example: "122-13-25.360W" -> -122.2237

    Args:
        lon_str: NASR longitude string (14 characters)

    Returns:
        Longitude in decimal degrees (positive for E, negative for W)
    """
    lon_str = lon_str.strip()
    if not lon_str:
        return None

    try:
        # Match pattern: DDD-MM-SS.SSSH
        match = re.match(r"(\d{2,3})-(\d{2})-([\d.]+)([EW])", lon_str)
        if not match:
            return None

        degrees = int(match.group(1))
        minutes = int(match.group(2))
        seconds = float(match.group(3))
        hemisphere = match.group(4)

        decimal = degrees + minutes / 60 + seconds / 3600

        if hemisphere == "W":
            decimal = -decimal

        return decimal
    except (ValueError, AttributeError):
        return None


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance in nautical miles between two coordinates.

    Uses the Haversine formula for great-circle distance.

    Args:
        lat1, lon1: First coordinate (decimal degrees)
        lat2, lon2: Second coordinate (decimal degrees)

    Returns:
        Distance in nautical miles
    """
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


def _distance_from_oak(navaid: NavaidInfo) -> float:
    """Calculate distance from OAK VOR to a navaid."""
    return haversine_distance(
        OAK_VOR_LAT, OAK_VOR_LON, navaid.latitude, navaid.longitude
    )


# --- NAV.txt Parsing ---


def _parse_navaid_type(type_str: str) -> str:
    """Parse the NAVAID type field into a friendly type.

    Args:
        type_str: Raw type string from NAV.txt (e.g., "VOR/DME", "VORTAC")

    Returns:
        Normalized navaid type string
    """
    type_str = type_str.strip()
    if not type_str:
        return "UNKNOWN"

    # Clean up and normalize
    # Replace multiple spaces with single space
    type_str = re.sub(r"\s+", " ", type_str)

    return type_str


def _parse_nav1_record(line: str) -> NavaidInfo | None:
    """Parse a NAV1 record from NAV.txt.

    NAV1 record layout (1-indexed positions, record length 805):
    - 1-4: Record type "NAV1"
    - 5-8: Facility identifier (4 chars)
    - 9-28: Facility type (20 chars)
    - 43-72: Facility name (30 chars)
    - 73-112: City (40 chars)
    - 113-142: State name (30 chars)
    - 143-144: State P.O. code (2 chars)
    - 372-385: Latitude formatted (14 chars) - DD-MM-SS.SSSH
    - 397-410: Longitude formatted (14 chars) - DDD-MM-SS.SSSH

    Args:
        line: Raw NAV.txt record line

    Returns:
        NavaidInfo if valid NAV1 record, None otherwise
    """
    if len(line) < 420:
        return None

    # Check record type (positions 1-4, 0-indexed: 0-3)
    record_type = line[0:4].strip()
    if record_type != "NAV1":
        return None

    # Extract fields (convert 1-indexed to 0-indexed)
    ident = line[4:8].strip()  # Position 5-8
    navaid_type = line[8:28].strip()  # Position 9-28
    name = line[42:72].strip()  # Position 43-72
    city = line[72:112].strip()  # Position 73-112
    state_code = line[142:144].strip()  # Position 143-144

    # Coordinates (positions 372-385 and 397-410, 0-indexed: 371-384 and 396-409)
    lat_str = line[371:385].strip()  # Position 372-385
    lon_str = line[396:410].strip()  # Position 397-410

    # Parse coordinates
    latitude = _parse_nasr_latitude(lat_str)
    longitude = _parse_nasr_longitude(lon_str)

    if not ident or latitude is None or longitude is None:
        return None

    return NavaidInfo(
        ident=ident,
        name=name,
        navaid_type=_parse_navaid_type(navaid_type),
        city=city,
        state=state_code,
        latitude=latitude,
        longitude=longitude,
    )


@lru_cache(maxsize=1)
def _load_navaid_data() -> list[NavaidInfo]:
    """Load all navaids from NASR NAV.txt.

    Returns:
        List of NavaidInfo objects
    """
    cache_path = ensure_nasr_data(["NAV"], quiet=True)
    if not cache_path:
        return []

    nav_file = cache_path / "NAV.txt"
    if not nav_file.exists():
        return []

    navaids: list[NavaidInfo] = []

    try:
        with open(nav_file, "r", encoding="latin-1") as f:
            for line in f:
                navaid = _parse_nav1_record(line)
                if navaid:
                    navaids.append(navaid)
    except (OSError, IOError):
        return []

    return navaids


@lru_cache(maxsize=1)
def _build_navaid_indexes() -> tuple[dict[str, list[NavaidInfo]], dict[str, list[NavaidInfo]]]:
    """Build indexes for fast navaid lookup.

    Returns:
        Tuple of (ident_to_navaids, name_to_navaids) dictionaries.
        Each maps to a list because multiple navaids can share an ident or name.
    """
    navaids = _load_navaid_data()

    ident_to_navaids: dict[str, list[NavaidInfo]] = {}
    name_to_navaids: dict[str, list[NavaidInfo]] = {}

    for navaid in navaids:
        ident_upper = navaid.ident.upper()
        name_upper = navaid.name.upper()

        if ident_upper not in ident_to_navaids:
            ident_to_navaids[ident_upper] = []
        ident_to_navaids[ident_upper].append(navaid)

        if name_upper not in name_to_navaids:
            name_to_navaids[name_upper] = []
        name_to_navaids[name_upper].append(navaid)

    return ident_to_navaids, name_to_navaids


# --- Public Navaid API ---


def get_all_identifiers() -> list[str]:
    """Get all navaid identifiers.

    Returns:
        List of all navaid identifiers (e.g., ["FMG", "SWR", "CCR", ...])
    """
    ident_to_navaids, _ = _build_navaid_indexes()
    return list(ident_to_navaids.keys())


def get_navaid_identifier(name: str) -> str | None:
    """Look up a navaid identifier by its name.

    If multiple navaids have the same name, returns the one closest to OAK.

    Args:
        name: Navaid name (e.g., "MUSTANG", "SQUAW")

    Returns:
        Navaid identifier (e.g., "FMG", "SWR") or None if not found.
    """
    _, name_to_navaids = _build_navaid_indexes()
    navaids = name_to_navaids.get(name.upper())

    if not navaids:
        return None

    # Return closest to OAK if multiple
    if len(navaids) == 1:
        return navaids[0].ident

    closest = min(navaids, key=_distance_from_oak)
    return closest.ident


def get_all_navaid_identifiers(name: str) -> list[str]:
    """Look up all navaid identifiers that have a given name.

    Since multiple navaids can share the same name (e.g., "CONCORD" exists
    as both CCR and CON in different locations), this returns all matching
    identifiers.

    Args:
        name: Navaid name (e.g., "CONCORD")

    Returns:
        List of navaid identifiers (e.g., ["CCR", "CON"]).
    """
    _, name_to_navaids = _build_navaid_indexes()
    navaids = name_to_navaids.get(name.upper(), [])
    return [n.ident for n in navaids]


def get_navaid_name(ident: str) -> str | None:
    """Look up a navaid name by its identifier.

    If multiple navaids have the same identifier, returns the one closest to OAK.

    Args:
        ident: Navaid identifier (e.g., "FMG", "SWR")

    Returns:
        Navaid name (e.g., "MUSTANG", "SQUAW") or None if not found.
    """
    ident_to_navaids, _ = _build_navaid_indexes()
    navaids = ident_to_navaids.get(ident.upper())

    if not navaids:
        return None

    # Return closest to OAK if multiple
    if len(navaids) == 1:
        return navaids[0].name

    closest = min(navaids, key=_distance_from_oak)
    return closest.name


def resolve_navaid_alias(chart_name: str) -> str:
    """Resolve navaid aliases in a chart name.

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
    """Search for navaids by identifier or name.

    Searches both the navaid identifier (e.g., "FMG") and the name
    (e.g., "MUSTANG"). Exact matches on identifier are prioritized,
    followed by partial matches on name. When multiple results are found,
    they are sorted by distance from OAK VOR.

    Args:
        query: Search query (identifier or name)

    Returns:
        NavaidSearchResult with matching navaids.
    """
    ident_to_navaids, name_to_navaids = _build_navaid_indexes()
    query_upper = query.upper().strip()
    results: list[NavaidInfo] = []

    # First pass: exact identifier match
    if query_upper in ident_to_navaids:
        results = list(ident_to_navaids[query_upper])
        if len(results) > 1:
            results.sort(key=_distance_from_oak)
        return NavaidSearchResult(query=query, results=results)

    # Second pass: exact name match
    if query_upper in name_to_navaids:
        results = list(name_to_navaids[query_upper])
        if len(results) > 1:
            results.sort(key=_distance_from_oak)
        return NavaidSearchResult(query=query, results=results)

    # Third pass: partial matches on name or ident
    all_navaids = _load_navaid_data()
    partial_matches: list[NavaidInfo] = []

    for navaid in all_navaids:
        if query_upper in navaid.name.upper() or query_upper in navaid.ident.upper():
            partial_matches.append(navaid)

    if partial_matches:
        partial_matches.sort(key=_distance_from_oak)

    return NavaidSearchResult(query=query, results=partial_matches)


# --- AWY.txt Parsing ---


def _parse_awy1_record(line: str) -> tuple[str, AirwayRestriction] | None:
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
        Tuple of (airway_designator, AirwayRestriction) if valid, None otherwise
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
            AirwayRestriction(
                airway=airway,
                sequence=sequence,
                mea=mea,
                mea_opposite=mea_opposite,
                moca=moca,
            ),
        )

    except (IndexError, ValueError):
        return None


def _parse_awy2_record(line: str) -> tuple[str, AirwayFix] | None:
    """Parse an AWY.txt AWY2 record line for fix information.

    AWY.txt format is fixed-width. AWY2 records contain fix details.

    Args:
        line: Raw AWY.txt record line

    Returns:
        Tuple of (airway_designator, AirwayFix) if valid, None otherwise
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
            AirwayFix(
                identifier=fix_id,
                sequence=sequence,
                latitude=latitude,
                longitude=longitude,
            ),
        )

    except (IndexError, ValueError):
        return None


@lru_cache(maxsize=1)
def load_airway_restrictions() -> dict[str, dict[int, AirwayRestriction]]:
    """Load MEA/MOCA restrictions for all airways from NASR data.

    Returns:
        Dict mapping airway designator to dict of sequence -> restriction.
        Example: {"V23": {20: AirwayRestriction(...), 30: ...}}
    """
    cache_path = ensure_nasr_data(["AWY"], quiet=True)
    if not cache_path:
        return {}

    awy_file = cache_path / "AWY.txt"
    if not awy_file.exists():
        return {}

    restrictions: dict[str, dict[int, AirwayRestriction]] = {}

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
def load_airways() -> dict[str, list[AirwayFix]]:
    """Load all airways from NASR data.

    Returns:
        Dict mapping airway designator to ordered list of AirwayFix objects
    """
    cache_path = ensure_nasr_data(["AWY"], quiet=True)
    if not cache_path:
        return {}

    awy_file = cache_path / "AWY.txt"
    if not awy_file.exists():
        return {}

    airways: dict[str, list[AirwayFix]] = {}

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
    _load_navaid_data.cache_clear()
    _build_navaid_indexes.cache_clear()
    load_airway_restrictions.cache_clear()
    load_airways.cache_clear()
