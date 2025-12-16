"""CIFP (Coded Instrument Flight Procedures) parser.

This module downloads and parses FAA CIFP data in ARINC 424 format to extract
approach and STAR procedure data. CIFP provides authoritative, structured data
for instrument procedures including IAF/IF/FAF fix designations and complete
waypoint sequences.

CIFP data is downloaded once per AIRAC cycle and cached locally.
"""

import io
import re
import urllib.request
import urllib.error
import zipfile
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from zoa_ref.cache import get_current_airac_cycle, CACHE_DIR


CIFP_BASE_URL = "https://aeronav.faa.gov/Upload_313-d/cifp/"
CIFP_TIMEOUT = 60  # seconds for download


# --- Data Classes ---


@dataclass
class CifpApproachFix:
    """A fix/waypoint in an approach procedure."""

    approach_id: str  # e.g., "H17LZ" -> RNAV (GPS) Z RWY 17L
    transition: str  # e.g., "LIBGE" or "" for main route
    fix_identifier: str  # e.g., "LIBGE", "KLOCK", "FMG"
    fix_type: str  # "IAF", "IF", "FAF", or ""
    sequence: int  # Order in procedure
    path_terminator: str = ""  # e.g., "IF", "TF", "RF"


@dataclass
class CifpApproach:
    """An approach procedure with all its fixes."""

    airport: str
    approach_id: str  # e.g., "H17LZ"
    approach_type: str  # e.g., "RNAV (GPS)", "ILS", "LOC"
    runway: str | None  # e.g., "17L", "35R"
    fixes: list[CifpApproachFix] = field(default_factory=list)

    @property
    def iaf_fixes(self) -> list[str]:
        """Get all IAF (Initial Approach Fix) identifiers."""
        return [f.fix_identifier for f in self.fixes if f.fix_type == "IAF"]

    @property
    def if_fixes(self) -> list[str]:
        """Get all IF (Intermediate Fix) identifiers."""
        return [f.fix_identifier for f in self.fixes if f.fix_type == "IF"]

    @property
    def transitions(self) -> list[str]:
        """Get unique transition names."""
        return list(set(f.transition for f in self.fixes if f.transition))

    @property
    def feeder_fixes(self) -> list[str]:
        """Get transition entry fixes (feeder routes).

        These are the first fix in each transition - the point where aircraft
        join the approach from a feeder route (e.g., FMG feeding to ROXJO via NUKOE).
        Only includes fixes that aren't already IAF/IF.
        """
        return list(self.feeder_paths.keys())

    @property
    def feeder_paths(self) -> dict[str, str]:
        """Get feeder fixes with their destination IAF/IF.

        Returns a dict mapping feeder fix -> destination IAF/IF identifier.
        E.g., {"FMG": "ROXJO", "ISESY": "AMEER"}
        """
        feeders: dict[str, str] = {}
        iaf_if_set = set(self.iaf_fixes + self.if_fixes)

        # Group fixes by transition and find the first in each
        transitions: dict[str, list[CifpApproachFix]] = {}
        for fix in self.fixes:
            if fix.transition:
                if fix.transition not in transitions:
                    transitions[fix.transition] = []
                transitions[fix.transition].append(fix)

        for trans_name, trans_fixes in transitions.items():
            if trans_fixes:
                # Sort by sequence
                sorted_fixes = sorted(trans_fixes, key=lambda x: x.sequence)
                first_fix = sorted_fixes[0].fix_identifier

                # Only add if not already an IAF or IF
                if first_fix not in iaf_if_set:
                    # Find the first IAF or IF in this transition
                    dest_fix = None
                    for fix in sorted_fixes:
                        if fix.fix_type in ("IAF", "IF"):
                            dest_fix = fix.fix_identifier
                            break

                    if dest_fix and first_fix not in feeders:
                        feeders[first_fix] = dest_fix

        return feeders


@dataclass
class CifpSTAR:
    """A STAR (Standard Terminal Arrival Route) with waypoints."""

    identifier: str  # e.g., "SCOLA1"
    waypoints: list[str]  # All waypoints in the common route
    transitions: list[str]  # Entry transition names (e.g., "KENNO", "MVA")


# --- CIFP Download and Management ---


def _get_effective_date_for_cycle(cycle_id: str) -> str:
    """Convert AIRAC cycle ID to YYMMDD effective date format.

    FAA CIFP files are named like CIFP_251127.zip for cycle 2512 (Nov 27, 2025).

    Args:
        cycle_id: AIRAC cycle ID (e.g., "2512")

    Returns:
        Date string in YYMMDD format (e.g., "251127")
    """
    from datetime import timedelta
    from zoa_ref.cache import AIRAC_EPOCH, CYCLE_DAYS

    # Parse cycle ID
    year = 2000 + int(cycle_id[:2])
    cycle_in_year = int(cycle_id[2:])

    # Calculate days since epoch
    # Cycle 2501 = epoch, so subtract 1 from cycle_in_year
    cycles_since_2501 = (year - 2025) * 13 + (cycle_in_year - 1)
    effective_date = AIRAC_EPOCH + timedelta(days=cycles_since_2501 * CYCLE_DAYS)

    return effective_date.strftime("%y%m%d")


def get_cifp_url() -> str:
    """Get the CIFP download URL for the current AIRAC cycle.

    Returns:
        URL to the CIFP zip file
    """
    cycle_id, _, _ = get_current_airac_cycle()
    date_str = _get_effective_date_for_cycle(cycle_id)
    return f"{CIFP_BASE_URL}CIFP_{date_str}.zip"


def get_cifp_cache_path() -> Path:
    """Get the cache path for CIFP data.

    Returns:
        Path to the cached CIFP text file
    """
    cycle_id, _, _ = get_current_airac_cycle()
    return CACHE_DIR / "cifp" / f"FAACIFP18-{cycle_id}"


def ensure_cifp_data() -> Path | None:
    """Download CIFP data if missing or outdated.

    Auto-downloads new CIFP data when a new AIRAC cycle begins.

    Returns:
        Path to the CIFP data file, or None if download failed
    """
    cached_path = get_cifp_cache_path()

    if cached_path.exists():
        return cached_path

    # Download new CIFP
    url = get_cifp_url()
    print(f"Downloading CIFP data from {url}...")

    try:
        with urllib.request.urlopen(url, timeout=CIFP_TIMEOUT) as response:
            zip_data = response.read()
    except (urllib.error.URLError, TimeoutError) as e:
        print(f"Failed to download CIFP: {e}")
        return None

    # Extract the FAACIFP18 file from the zip
    try:
        with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
            # Find the main CIFP file
            cifp_filename = None
            for name in zf.namelist():
                if name.startswith("FAACIFP"):
                    cifp_filename = name
                    break

            if not cifp_filename:
                print("FAACIFP file not found in zip")
                return None

            # Extract to cache
            cached_path.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(cifp_filename) as src, open(cached_path, "wb") as dst:
                dst.write(src.read())

            print(f"CIFP data cached to {cached_path}")
            return cached_path

    except zipfile.BadZipFile as e:
        print(f"Invalid zip file: {e}")
        return None


# --- ARINC 424 Record Parsing ---


# Waypoint Description Code 1 (position 43, 1-indexed) meanings
WAYPOINT_DESC_CODES = {
    "A": "IAF",  # Initial Approach Fix
    "B": "IF",  # Intermediate Fix
    "C": "IAF",  # IAF and IF combined (treat as IAF)
    "D": "IAF",  # IAF and FAF combined (treat as IAF)
    "E": "FAF",  # Final Approach Course Fix / FAF
    "F": "FAF",  # Final Approach Fix
    "G": "MAHP",  # Missed Approach Point
    "I": "IF",  # Initial Fix (IF in path terminator context)
    "M": "MAHP",  # Missed Approach Holding Fix
}

# Approach type codes (first character of approach ID)
APPROACH_TYPE_CODES = {
    "B": "LOC/DME BC",
    "D": "VOR/DME",
    "F": "FMS",
    "G": "IGS",
    "H": "RNAV (GPS)",  # Could be RNAV (RNP) - needs further distinction
    "I": "ILS",
    "J": "GNSS",
    "L": "LOC",
    "N": "NDB",
    "P": "GPS",
    "Q": "NDB/DME",
    "R": "RNAV",
    "S": "VOR",  # VOR with DME required
    "T": "TACAN",
    "U": "SDF",
    "V": "VOR",
    "W": "MLS",
    "X": "LDA",
    "Y": "MLS",  # Type A/B/C
    "Z": "MLS",  # Type B/C
}


def _parse_runway_from_approach_id(approach_id: str) -> str | None:
    """Extract runway from approach ID.

    Args:
        approach_id: e.g., "H17LZ", "I35L", "V07"

    Returns:
        Runway string (e.g., "17L", "35L", "07") or None
    """
    # Skip first character (approach type)
    rest = approach_id[1:]

    # Match runway pattern: 1-2 digits optionally followed by L/R/C
    # The last character might be a variant letter (X, Y, Z, W)
    match = re.match(r"(\d{1,2}[LRC]?)", rest)
    if match:
        return match.group(1)
    return None


def _parse_approach_type(approach_id: str) -> str:
    """Get approach type from approach ID.

    Args:
        approach_id: e.g., "H17LZ"

    Returns:
        Approach type string (e.g., "RNAV (GPS)")
    """
    if not approach_id:
        return "UNKNOWN"

    type_code = approach_id[0]
    return APPROACH_TYPE_CODES.get(type_code, "UNKNOWN")


def parse_approach_record(line: str) -> CifpApproachFix | None:
    """Parse a single CIFP approach procedure record.

    ARINC 424 approach records have fixed column positions:
    - Position 7-10: Airport ICAO
    - Position 13: Subsection (F = Approach)
    - Position 14-19: Approach ID
    - Position 20: Route type (A = transition, H/I/L etc = main)
    - Position 21-25: Transition identifier
    - Position 27-29: Sequence number
    - Position 30-34: Fix identifier
    - Position 43: Waypoint Description Code 1
    - Position 48-49: Path terminator

    Args:
        line: Raw CIFP record line

    Returns:
        CifpApproachFix if valid approach record, None otherwise
    """
    if len(line) < 50:
        return None

    # Check record type and subsection
    if not line.startswith("SUSAP"):
        return None

    # Position 13 (0-indexed: 12) = Subsection
    if len(line) < 13 or line[12] != "F":
        return None

    # Extract fields (1-indexed positions converted to 0-indexed)
    approach_id = line[13:19].strip()  # Position 14-19
    route_type = line[19] if len(line) > 19 else ""  # Position 20
    transition = line[20:25].strip()  # Position 21-25
    sequence_str = line[26:29].strip()  # Position 27-29
    fix_identifier = line[29:34].strip()  # Position 30-34

    # Waypoint description code (position 43, 0-indexed: 42)
    waypoint_desc = line[42] if len(line) > 42 else " "

    # Path terminator (positions 48-49, 0-indexed: 47-48)
    path_terminator = line[47:49].strip() if len(line) > 48 else ""

    # Parse sequence number
    try:
        sequence = int(sequence_str)
    except ValueError:
        sequence = 0

    # Determine fix type from waypoint description code
    fix_type = WAYPOINT_DESC_CODES.get(waypoint_desc, "")

    # Skip if no fix identifier
    if not fix_identifier:
        return None

    # For transition records (route_type == 'A'), use transition name
    # For main route records, transition is empty
    if route_type != "A":
        transition = ""

    return CifpApproachFix(
        approach_id=approach_id,
        transition=transition,
        fix_identifier=fix_identifier,
        fix_type=fix_type,
        sequence=sequence,
        path_terminator=path_terminator,
    )


def parse_star_record(line: str) -> tuple[str, str, str, int] | None:
    """Parse a single CIFP STAR record.

    ARINC 424 STAR records (subsection E):
    - Position 7-10: Airport ICAO
    - Position 13: Subsection (E = STAR)
    - Position 14-19: STAR identifier (e.g., "SCOLA1")
    - Position 20: Route variant
    - Position 21-25: Transition name (or "ALL" for common route)
    - Position 27-29: Sequence number
    - Position 30-34: Fix identifier

    Args:
        line: Raw CIFP record line

    Returns:
        Tuple of (star_id, transition, fix_identifier, sequence) or None
    """
    if len(line) < 35:
        return None

    # Check record type and subsection
    if not line.startswith("SUSAP"):
        return None

    # Position 13 (0-indexed: 12) = Subsection
    if len(line) < 13 or line[12] != "E":
        return None

    # Extract fields
    star_id = line[13:19].strip()  # Position 14-19 (includes variant digit)
    transition = line[20:25].strip()  # Position 21-25
    sequence_str = line[26:29].strip()  # Position 27-29
    fix_identifier = line[29:34].strip()  # Position 30-34

    try:
        sequence = int(sequence_str)
    except ValueError:
        sequence = 0

    if not fix_identifier or not star_id:
        return None

    return (star_id, transition, fix_identifier, sequence)


# --- High-Level API ---


@lru_cache(maxsize=32)
def get_approaches_for_airport(airport: str) -> dict[str, CifpApproach]:
    """Get all approach procedures for an airport.

    Args:
        airport: Airport code (e.g., "RNO", "KRNO")

    Returns:
        Dict mapping approach_id to CifpApproach objects
    """
    cifp_path = ensure_cifp_data()
    if not cifp_path:
        return {}

    # Normalize airport code
    airport = airport.upper().lstrip("K")
    search_prefix = f"SUSAP K{airport}"

    approaches: dict[str, CifpApproach] = {}

    with open(cifp_path, "r", encoding="latin-1") as f:
        for line in f:
            if not line.startswith(search_prefix):
                continue

            fix = parse_approach_record(line)
            if not fix:
                continue

            # Create approach if not exists
            if fix.approach_id not in approaches:
                approaches[fix.approach_id] = CifpApproach(
                    airport=airport,
                    approach_id=fix.approach_id,
                    approach_type=_parse_approach_type(fix.approach_id),
                    runway=_parse_runway_from_approach_id(fix.approach_id),
                )

            approaches[fix.approach_id].fixes.append(fix)

    return approaches


def get_star_data(airport: str, star_name: str) -> CifpSTAR | None:
    """Get STAR data from CIFP.

    This replaces navdata.get_star_data() with local CIFP parsing.

    Args:
        airport: Airport code (e.g., "RNO")
        star_name: STAR name (e.g., "SCOLA1", "SCOLA ONE")

    Returns:
        CifpSTAR with waypoints and transitions, or None if not found
    """
    cifp_path = ensure_cifp_data()
    if not cifp_path:
        return None

    # Normalize inputs
    airport = airport.upper().lstrip("K")
    star_name = star_name.upper().strip()

    # Strip off common suffixes like "(RNAV)" from chart names
    star_name = re.sub(r"\s*\(RNAV\)$", "", star_name)

    # Normalize STAR name - extract base name and number
    # "SCOLA1" -> base="SCOLA", num="1"
    # "SCOLA ONE" -> base="SCOLA", num="1"
    # "CONCORD TWO" -> base="CONCORD", num="2" -> also try "CCR2" (navaid identifier)
    star_match = re.match(r"^([A-Z]+)\s*(\d|ONE|TWO|THREE|FOUR|FIVE|SIX|SEVEN|EIGHT|NINE)$", star_name)
    if star_match:
        base_name = star_match.group(1)
        num_part = star_match.group(2)
        # Convert word to digit if needed
        word_to_digit = {
            "ONE": "1", "TWO": "2", "THREE": "3", "FOUR": "4", "FIVE": "5",
            "SIX": "6", "SEVEN": "7", "EIGHT": "8", "NINE": "9",
        }
        if num_part in word_to_digit:
            num_part = word_to_digit[num_part]
        star_id_prefix = f"{base_name}{num_part}"

        # Also try navaid identifiers if base_name is a navaid name
        # e.g., "CONCORD" -> ["CCR", "CON"] so "CONCORD2" -> try "CCR2", "CON2"
        from zoa_ref.navaids import get_all_navaid_identifiers
        navaid_idents = get_all_navaid_identifiers(base_name)
        star_id_prefixes = [star_id_prefix]
        for navaid_ident in navaid_idents:
            if navaid_ident != base_name:
                star_id_prefixes.append(f"{navaid_ident}{num_part}")
    else:
        star_id_prefix = star_name
        star_id_prefixes = [star_id_prefix]

    search_prefix = f"SUSAP K{airport}"

    # Collect all records for this STAR
    star_records: dict[str, list[tuple[str, int]]] = {}  # transition -> [(fix, sequence)]

    with open(cifp_path, "r", encoding="latin-1") as f:
        for line in f:
            if not line.startswith(search_prefix):
                continue

            result = parse_star_record(line)
            if not result:
                continue

            star_id, transition, fix_id, sequence = result

            # Check if this matches our STAR (e.g., "SCOLA14" or "SCOLA15" for SCOLA1)
            if not any(star_id.startswith(prefix) for prefix in star_id_prefixes):
                continue

            if transition not in star_records:
                star_records[transition] = []
            star_records[transition].append((fix_id, sequence))

    if not star_records:
        return None

    # Extract waypoints from common route and runway transitions
    # Common route may be named "ALL" or have empty transition name ""
    # Runway transitions start with "RW" (e.g., "RW28B", "RW28L")
    all_waypoints = []
    seen_waypoints = set()

    # First add common route waypoints (may be "ALL" or "")
    common_route_key = "ALL" if "ALL" in star_records else "" if "" in star_records else None
    if common_route_key is not None:
        sorted_fixes = sorted(star_records[common_route_key], key=lambda x: x[1])
        for fix, _ in sorted_fixes:
            if fix not in seen_waypoints:
                all_waypoints.append(fix)
                seen_waypoints.add(fix)

    # Then add runway transition waypoints (these contain the final fixes like ARCHI)
    for trans_name, fixes in star_records.items():
        if trans_name.startswith("RW"):
            sorted_fixes = sorted(fixes, key=lambda x: x[1])
            for fix, _ in sorted_fixes:
                if fix not in seen_waypoints:
                    all_waypoints.append(fix)
                    seen_waypoints.add(fix)

    # Filter out airport/runway references (e.g., "RW28L", "KSFO")
    all_waypoints = [w for w in all_waypoints if not w.startswith("RW") and not w.endswith(airport)]

    # Get enroute transition names (excluding common route and runway transitions)
    transitions = [t for t in star_records.keys() if t and t != "ALL" and not t.startswith("RW")]

    return CifpSTAR(
        identifier=star_id_prefix,
        waypoints=all_waypoints,
        transitions=sorted(transitions),
    )


def get_all_stars(airport: str) -> dict[str, CifpSTAR]:
    """Get all STARs for an airport.

    Args:
        airport: Airport code (e.g., "RNO")

    Returns:
        Dict mapping STAR identifier to CifpSTAR
    """
    cifp_path = ensure_cifp_data()
    if not cifp_path:
        return {}

    airport = airport.upper().lstrip("K")
    search_prefix = f"SUSAP K{airport}"

    # First pass: collect all unique STAR identifiers
    star_ids: set[str] = set()

    with open(cifp_path, "r", encoding="latin-1") as f:
        for line in f:
            if not line.startswith(search_prefix):
                continue

            if len(line) > 12 and line[12] == "E":
                # Extract base STAR ID (first 5 chars + digit)
                star_id = line[13:19].strip()
                if star_id:
                    # Normalize to base ID (e.g., "SCOLA14" -> "SCOLA1")
                    match = re.match(r"^([A-Z]+\d)", star_id)
                    if match:
                        star_ids.add(match.group(1))

    # Get full data for each STAR
    stars = {}
    for star_id in star_ids:
        star = get_star_data(airport, star_id)
        if star:
            stars[star_id] = star

    return stars
