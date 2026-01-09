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


@dataclass
class CifpDP:
    """A departure procedure (SID) with waypoints."""

    identifier: str  # e.g., "CNDEL5"
    waypoints: list[str]  # All waypoints in the common route
    transitions: list[str]  # Exit transition names (e.g., "MOD", "SAC")


# --- Enhanced Data Classes with Altitude/Speed Restrictions ---


@dataclass
class AltitudeRestriction:
    """Altitude restriction for a procedure leg."""

    description: str  # "+", "-", "@", "B", "G", "H", "I", "J", "V", or ""
    altitude1: int | None  # First altitude in feet (or None if not specified)
    altitude2: int | None  # Second altitude in feet (for "B" - between)

    def __str__(self) -> str:
        if not self.altitude1:
            return ""
        alt1_str = f"FL{self.altitude1 // 100}" if self.altitude1 >= 18000 else f"{self.altitude1}"
        if self.description == "B" and self.altitude2:
            alt2_str = f"FL{self.altitude2 // 100}" if self.altitude2 >= 18000 else f"{self.altitude2}"
            return f"{alt1_str}-{alt2_str}"
        elif self.description == "+":
            return f"{alt1_str}A"  # At or above
        elif self.description == "-":
            return f"{alt1_str}B"  # At or below
        elif self.description in ("@", ""):
            return alt1_str  # At (mandatory)
        elif self.description == "G":
            return f"{alt1_str}(GS)"
        elif self.description == "H":
            return f"{alt1_str}A"  # At or above alt_1
        else:
            return alt1_str


@dataclass
class SpeedRestriction:
    """Speed restriction for a procedure leg."""

    description: str  # "@", "+", "-", or ""
    speed: int | None  # Speed in knots (or None if not specified)

    def __str__(self) -> str:
        if not self.speed:
            return ""
        if self.description == "+":
            return f"{self.speed}K+"  # At or above
        elif self.description == "-":
            return f"{self.speed}K-"  # At or below
        else:
            return f"{self.speed}K"  # Mandatory


@dataclass
class ProcedureLeg:
    """A single leg/waypoint in a procedure with restrictions."""

    fix_identifier: str  # Waypoint/fix name (e.g., "SCOLA", "FMG")
    path_terminator: str  # e.g., "IF", "TF", "RF", "DF", "CF"
    turn_direction: str  # "L", "R", or ""
    altitude: AltitudeRestriction | None
    speed: SpeedRestriction | None
    transition: str  # Transition name or "" for common route
    sequence: int  # Order in procedure
    fix_type: str  # "IAF", "IF", "FAF", "MAHP", or ""

    @property
    def restrictions_str(self) -> str:
        """Format restrictions as a display string."""
        parts = []
        if self.altitude and self.altitude.altitude1:
            parts.append(str(self.altitude))
        if self.speed and self.speed.speed:
            parts.append(str(self.speed))
        return " ".join(parts)


@dataclass
class CifpProcedureDetail:
    """Detailed procedure data with full leg information."""

    airport: str  # e.g., "RNO"
    identifier: str  # e.g., "SCOLA1", "CNDEL5", "H17LZ"
    procedure_type: str  # "SID", "STAR", "APPROACH"
    approach_type: str | None  # e.g., "RNAV (GPS)", "ILS" (only for approaches)
    runway: str | None  # e.g., "17L", "28R"
    common_legs: list[ProcedureLeg]  # Main route legs
    transitions: dict[str, list[ProcedureLeg]]  # Transition name -> legs
    runway_transitions: dict[str, list[ProcedureLeg]]  # RW* transitions


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


# Waypoint Description Code 1 (position 39, 0-indexed) meanings
# Code meanings vary by procedure type; these are primarily for approaches
WAYPOINT_DESC_CODES = {
    "A": "IAF",  # Initial Approach Fix
    "B": "IF",  # Intermediate Fix
    "C": "IAF/IF",  # IAF and IF combined
    "D": "IAF/FAF",  # IAF and FAF combined
    "E": "",  # Essential waypoint (basic SID/STAR waypoint)
    "F": "",  # Off-airway/flyover waypoint
    "G": "",  # Runway or glide slope intercept
    "H": "",  # Heliport as fix
    "K": "FAF",  # Final Approach Fix
    "M": "MAHP",  # Missed Approach Holding Fix
    "P": "",  # Published waypoint
    "V": "",  # VOR/VORTAC/DME
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
    star_match = re.match(
        r"^([A-Z]+)\s*(\d|ONE|TWO|THREE|FOUR|FIVE|SIX|SEVEN|EIGHT|NINE)$", star_name
    )
    if star_match:
        base_name = star_match.group(1)
        num_part = star_match.group(2)
        # Convert word to digit if needed
        word_to_digit = {
            "ONE": "1",
            "TWO": "2",
            "THREE": "3",
            "FOUR": "4",
            "FIVE": "5",
            "SIX": "6",
            "SEVEN": "7",
            "EIGHT": "8",
            "NINE": "9",
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
    star_records: dict[
        str, list[tuple[str, int]]
    ] = {}  # transition -> [(fix, sequence)]

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
    common_route_key = (
        "ALL" if "ALL" in star_records else "" if "" in star_records else None
    )
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
    all_waypoints = [
        w for w in all_waypoints if not w.startswith("RW") and not w.endswith(airport)
    ]

    # Get enroute transition names (excluding common route and runway transitions)
    transitions = [
        t for t in star_records.keys() if t and t != "ALL" and not t.startswith("RW")
    ]

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


def parse_dp_record(line: str) -> tuple[str, str, str, int] | None:
    """Parse a single CIFP DP (departure procedure) record.

    ARINC 424 DP records (subsection D):
    - Position 7-10: Airport ICAO
    - Position 13: Subsection (D = SID/DP)
    - Position 14-19: DP identifier (e.g., "CNDEL5")
    - Position 20: Route variant
    - Position 21-25: Transition name (or "ALL" for common route)
    - Position 27-29: Sequence number
    - Position 30-34: Fix identifier

    Args:
        line: Raw CIFP record line

    Returns:
        Tuple of (dp_id, transition, fix_identifier, sequence) or None
    """
    if len(line) < 35:
        return None

    # Check record type and subsection
    if not line.startswith("SUSAP"):
        return None

    # Position 13 (0-indexed: 12) = Subsection
    if len(line) < 13 or line[12] != "D":
        return None

    # Extract fields
    dp_id = line[13:19].strip()  # Position 14-19 (includes variant digit)
    transition = line[20:25].strip()  # Position 21-25
    sequence_str = line[26:29].strip()  # Position 27-29
    fix_identifier = line[29:34].strip()  # Position 30-34

    try:
        sequence = int(sequence_str)
    except ValueError:
        sequence = 0

    if not fix_identifier or not dp_id:
        return None

    return (dp_id, transition, fix_identifier, sequence)


def get_dp_data(airport: str, dp_name: str) -> CifpDP | None:
    """Get DP (departure procedure) data from CIFP.

    Args:
        airport: Airport code (e.g., "OAK")
        dp_name: DP name (e.g., "CNDEL5", "CNDEL FIVE")

    Returns:
        CifpDP with waypoints and transitions, or None if not found
    """
    cifp_path = ensure_cifp_data()
    if not cifp_path:
        return None

    # Normalize inputs
    airport = airport.upper().lstrip("K")
    dp_name = dp_name.upper().strip()

    # Strip off common suffixes like "(RNAV)" from chart names
    dp_name = re.sub(r"\s*\(RNAV\)$", "", dp_name)

    # Normalize DP name - extract base name and number
    # "CNDEL5" -> base="CNDEL", num="5"
    # "CNDEL FIVE" -> base="CNDEL", num="5"
    dp_match = re.match(
        r"^([A-Z]+)\s*(\d|ONE|TWO|THREE|FOUR|FIVE|SIX|SEVEN|EIGHT|NINE)$", dp_name
    )
    if dp_match:
        base_name = dp_match.group(1)
        num_part = dp_match.group(2)
        # Convert word to digit if needed
        word_to_digit = {
            "ONE": "1",
            "TWO": "2",
            "THREE": "3",
            "FOUR": "4",
            "FIVE": "5",
            "SIX": "6",
            "SEVEN": "7",
            "EIGHT": "8",
            "NINE": "9",
        }
        if num_part in word_to_digit:
            num_part = word_to_digit[num_part]
        dp_id_prefix = f"{base_name}{num_part}"

        # Also try navaid identifiers if base_name is a navaid name
        from zoa_ref.navaids import get_all_navaid_identifiers

        navaid_idents = get_all_navaid_identifiers(base_name)
        dp_id_prefixes = [dp_id_prefix]
        for navaid_ident in navaid_idents:
            if navaid_ident != base_name:
                dp_id_prefixes.append(f"{navaid_ident}{num_part}")
    else:
        dp_id_prefix = dp_name
        dp_id_prefixes = [dp_id_prefix]

    search_prefix = f"SUSAP K{airport}"

    # Collect all records for this DP
    dp_records: dict[str, list[tuple[str, int]]] = {}  # transition -> [(fix, sequence)]

    with open(cifp_path, "r", encoding="latin-1") as f:
        for line in f:
            if not line.startswith(search_prefix):
                continue

            result = parse_dp_record(line)
            if not result:
                continue

            dp_id, transition, fix_id, sequence = result

            # Check if this matches our DP (e.g., "CNDEL54" or "CNDEL55" for CNDEL5)
            if not any(dp_id.startswith(prefix) for prefix in dp_id_prefixes):
                continue

            if transition not in dp_records:
                dp_records[transition] = []
            dp_records[transition].append((fix_id, sequence))

    if not dp_records:
        return None

    # Extract waypoints from common route and enroute transitions
    # Common route may be named "ALL" or have empty transition name ""
    # Runway transitions start with "RW" (e.g., "RW28B", "RW28L")
    all_waypoints = []
    seen_waypoints = set()

    # First add runway transition waypoints (these are the initial fixes)
    for trans_name, fixes in dp_records.items():
        if trans_name.startswith("RW"):
            sorted_fixes = sorted(fixes, key=lambda x: x[1])
            for fix, _ in sorted_fixes:
                if fix not in seen_waypoints:
                    all_waypoints.append(fix)
                    seen_waypoints.add(fix)

    # Then add common route waypoints (may be "ALL" or "")
    common_route_key = (
        "ALL" if "ALL" in dp_records else "" if "" in dp_records else None
    )
    if common_route_key is not None:
        sorted_fixes = sorted(dp_records[common_route_key], key=lambda x: x[1])
        for fix, _ in sorted_fixes:
            if fix not in seen_waypoints:
                all_waypoints.append(fix)
                seen_waypoints.add(fix)

    # Then add enroute transition waypoints (exit points)
    for trans_name, fixes in dp_records.items():
        if trans_name and trans_name != "ALL" and not trans_name.startswith("RW"):
            sorted_fixes = sorted(fixes, key=lambda x: x[1])
            for fix, _ in sorted_fixes:
                if fix not in seen_waypoints:
                    all_waypoints.append(fix)
                    seen_waypoints.add(fix)

    # Filter out airport/runway references (e.g., "RW28L", "KOAK")
    all_waypoints = [
        w for w in all_waypoints if not w.startswith("RW") and not w.endswith(airport)
    ]

    # Get enroute transition names (excluding common route and runway transitions)
    transitions = [
        t for t in dp_records.keys() if t and t != "ALL" and not t.startswith("RW")
    ]

    return CifpDP(
        identifier=dp_id_prefix,
        waypoints=all_waypoints,
        transitions=sorted(transitions),
    )


def get_all_dps(airport: str) -> dict[str, CifpDP]:
    """Get all DPs (departure procedures) for an airport.

    Args:
        airport: Airport code (e.g., "OAK")

    Returns:
        Dict mapping DP identifier to CifpDP
    """
    cifp_path = ensure_cifp_data()
    if not cifp_path:
        return {}

    airport = airport.upper().lstrip("K")
    search_prefix = f"SUSAP K{airport}"

    # First pass: collect all unique DP identifiers
    dp_ids: set[str] = set()

    with open(cifp_path, "r", encoding="latin-1") as f:
        for line in f:
            if not line.startswith(search_prefix):
                continue

            if len(line) > 12 and line[12] == "D":
                # Extract base DP ID (first 5 chars + digit)
                dp_id = line[13:19].strip()
                if dp_id:
                    # Normalize to base ID (e.g., "CNDEL54" -> "CNDEL5")
                    match = re.match(r"^([A-Z]+\d)", dp_id)
                    if match:
                        dp_ids.add(match.group(1))

    # Get full data for each DP
    dps = {}
    for dp_id in dp_ids:
        dp = get_dp_data(airport, dp_id)
        if dp:
            dps[dp_id] = dp

    return dps


# --- Enhanced Parsing with Altitude/Speed Restrictions ---


def _parse_altitude(alt_str: str) -> int | None:
    """Parse altitude from ARINC 424 format.

    ARINC 424 uses a 5-character altitude field with different encodings:
    - Flight level: "FL280" or " FL28" -> FL280 = 28,000 ft (FL number × 1000)
    - Feet: " 1700" -> 17,000 ft (value × 10)
    - Empty: "     " -> None

    The FL encoding stores FL/10 (e.g., FL280 stored as "FL28" or "FL280").
    Non-FL values are stored in tens of feet (e.g., 17000 stored as "1700").

    Args:
        alt_str: 5-character altitude string

    Returns:
        Altitude in feet, or None if not specified
    """
    alt_str = alt_str.strip()
    if not alt_str:
        return None

    # Remove any leading zeros (but not from FL numbers)
    if not alt_str.startswith("FL"):
        alt_str = alt_str.lstrip("0")
    if not alt_str:
        return None

    try:
        # Check for FL prefix
        if alt_str.startswith("FL"):
            # Extract the number after FL
            fl_num_str = alt_str[2:].strip()
            if fl_num_str:
                fl_num = int(fl_num_str)
                # If 2-digit FL (e.g., "FL28" = FL280), multiply by 1000
                # If 3-digit FL (e.g., "FL280"), multiply by 100
                if fl_num < 100:
                    return fl_num * 1000
                else:
                    return fl_num * 100
            return None

        # Pure numeric - value is in tens of feet
        val = int(alt_str)
        return val * 10
    except ValueError:
        return None


def _parse_speed(speed_str: str) -> int | None:
    """Parse speed from ARINC 424 format.

    Args:
        speed_str: 3-character speed string

    Returns:
        Speed in knots, or None if not specified
    """
    speed_str = speed_str.strip()
    if not speed_str:
        return None
    try:
        return int(speed_str)
    except ValueError:
        return None


def parse_procedure_leg(line: str, subsection: str) -> ProcedureLeg | None:
    """Parse a procedure record into a ProcedureLeg with full restrictions.

    ARINC 424 column positions (0-indexed):
    - 13-19: Procedure identifier
    - 19-20: Route type (procedure type)
    - 20-25: Transition identifier
    - 26-29: Sequence number
    - 29-34: Fix identifier
    - 39-43: Waypoint description (4 chars)
    - 43-44: Turn direction
    - 47-49: Path terminator
    - 82-83: Altitude description
    - 83-88: Altitude 1
    - 88-93: Altitude 2
    - 99-102: Speed limit
    - 117-118: Speed limit description

    Args:
        line: Raw CIFP record line
        subsection: Subsection code ("D" for SID, "E" for STAR, "F" for approach)

    Returns:
        ProcedureLeg object or None if parsing fails
    """
    if len(line) < 102:
        return None

    # Check record type
    if not line.startswith("SUSAP"):
        return None

    # Check subsection
    if len(line) < 13 or line[12] != subsection:
        return None

    # Extract fields
    route_type = line[19] if len(line) > 19 else ""
    transition = line[20:25].strip()
    sequence_str = line[26:29].strip()
    fix_identifier = line[29:34].strip()
    waypoint_desc = line[39:43] if len(line) > 42 else "    "
    turn_direction = line[43] if len(line) > 43 else " "
    path_terminator = line[47:49].strip() if len(line) > 48 else ""

    # Altitude fields
    alt_desc = line[82] if len(line) > 82 else " "
    alt_1_str = line[83:88] if len(line) > 87 else ""
    alt_2_str = line[88:93] if len(line) > 92 else ""

    # Speed fields
    speed_str = line[99:102] if len(line) > 101 else ""
    speed_desc = line[117] if len(line) > 117 else " "

    # Parse values
    try:
        sequence = int(sequence_str)
    except ValueError:
        sequence = 0

    if not fix_identifier:
        return None

    # Skip records with empty path terminators (continuation/special records)
    if not path_terminator:
        return None

    # Determine fix type from waypoint description code (first char)
    fix_type = WAYPOINT_DESC_CODES.get(waypoint_desc[0], "") if waypoint_desc else ""

    # Parse altitude restriction
    alt_1 = _parse_altitude(alt_1_str)
    alt_2 = _parse_altitude(alt_2_str)
    altitude = None
    if alt_1 is not None or alt_desc.strip():
        altitude = AltitudeRestriction(
            description=alt_desc.strip(),
            altitude1=alt_1,
            altitude2=alt_2,
        )

    # Parse speed restriction
    speed_val = _parse_speed(speed_str)
    speed = None
    if speed_val is not None:
        speed = SpeedRestriction(
            description=speed_desc.strip(),
            speed=speed_val,
        )

    # For transition records (route_type in certain codes), use transition name
    # For main route records, transition is empty
    if route_type not in ("1", "2", "3", "4", "5", "6", "A"):
        transition = ""

    return ProcedureLeg(
        fix_identifier=fix_identifier,
        path_terminator=path_terminator,
        turn_direction=turn_direction.strip(),
        altitude=altitude,
        speed=speed,
        transition=transition,
        sequence=sequence,
        fix_type=fix_type,
    )


def get_procedure_detail(
    airport: str, procedure_name: str, transition: str | None = None
) -> CifpProcedureDetail | None:
    """Get detailed procedure data with altitude/speed restrictions.

    Automatically detects procedure type (SID, STAR, or Approach) based on
    the procedure name format.

    Args:
        airport: Airport code (e.g., "RNO", "OAK")
        procedure_name: Procedure identifier (e.g., "SCOLA1", "CNDEL5", "ILS 17L")
        transition: Optional transition name to filter (e.g., "LEGGS" for LEGGS.BDEGA4)

    Returns:
        CifpProcedureDetail with full leg information, or None if not found
    """
    cifp_path = ensure_cifp_data()
    if not cifp_path:
        return None

    airport = airport.upper().lstrip("K")
    procedure_name = procedure_name.upper().strip()

    # Strip off common suffixes like "(RNAV)" from chart names
    procedure_name = re.sub(r"\s*\(RNAV\)$", "", procedure_name)

    # Determine procedure type and normalize the identifier
    procedure_type: str
    subsection: str
    proc_id_prefixes: list[str]
    approach_type: str | None = None
    runway: str | None = None

    # Check if it's an approach (starts with approach type identifier)
    # Supports formats: "ILS 17L", "ILS17L", "RNAV 17L Z", "RNAV17LZ", "ILS Y 17R"
    approach_pattern = re.match(
        r"^(ILS|LOC|VOR|RNAV|RNP|GPS|NDB|LDA|SDF|TACAN)\s*"
        r"(?:(?:Y|Z|X|W)\s+)?(?:OR\s+\w+\s+)?(?:RWY\s*)?"
        r"(\d{1,2}[LRC]?)\s*([XYZWABCDEFGH])?$",
        procedure_name,
    )
    if approach_pattern:
        procedure_type = "APPROACH"
        subsection = "F"
        app_type_name = approach_pattern.group(1)
        runway = approach_pattern.group(2)
        variant = approach_pattern.group(3) or ""

        # Map approach type to ARINC code
        type_map = {
            "ILS": "I",
            "LOC": "L",
            "VOR": "V",
            "RNAV": "H",
            "RNP": "R",  # RNP approaches have their own code
            "GPS": "P",
            "NDB": "N",
            "LDA": "X",
            "SDF": "U",
            "TACAN": "T",
        }
        type_code = type_map.get(app_type_name, "H")

        # Build approach ID (e.g., "I17R" for ILS 17R, "H17LZ" for RNAV Z 17L)
        # Try multiple prefixes to catch different encoding variations
        proc_id_prefixes = []
        if variant:
            proc_id_prefixes.append(f"{type_code}{runway}{variant}")
        proc_id_prefixes.append(f"{type_code}{runway}")

        approach_type = APPROACH_TYPE_CODES.get(type_code, app_type_name)
    else:
        # Check for SID/STAR pattern (name + number)
        proc_match = re.match(
            r"^([A-Z]+)\s*(\d|ONE|TWO|THREE|FOUR|FIVE|SIX|SEVEN|EIGHT|NINE)$",
            procedure_name,
        )
        if proc_match:
            base_name = proc_match.group(1)
            num_part = proc_match.group(2)
            # Convert word to digit if needed
            word_to_digit = {
                "ONE": "1",
                "TWO": "2",
                "THREE": "3",
                "FOUR": "4",
                "FIVE": "5",
                "SIX": "6",
                "SEVEN": "7",
                "EIGHT": "8",
                "NINE": "9",
            }
            if num_part in word_to_digit:
                num_part = word_to_digit[num_part]
            proc_id_prefix = f"{base_name}{num_part}"

            # Try navaid identifiers too
            from zoa_ref.navaids import get_all_navaid_identifiers

            navaid_idents = get_all_navaid_identifiers(base_name)
            proc_id_prefixes = [proc_id_prefix]
            for navaid_ident in navaid_idents:
                if navaid_ident != base_name:
                    proc_id_prefixes.append(f"{navaid_ident}{num_part}")
        else:
            # Just use the name as-is
            proc_id_prefixes = [procedure_name]

        # Try both SID and STAR subsections
        procedure_type = "SID"  # Will be updated if found in STAR
        subsection = "D"  # Try SID first

    search_prefix = f"SUSAP K{airport}"

    # Collect all legs
    all_legs: list[ProcedureLeg] = []
    found_subsection = subsection

    # First try the initial subsection
    with open(cifp_path, "r", encoding="latin-1") as f:
        for line in f:
            if not line.startswith(search_prefix):
                continue

            # Check subsection
            if len(line) <= 12:
                continue

            line_subsection = line[12]
            if line_subsection not in ("D", "E", "F"):
                continue

            proc_id = line[13:19].strip()

            # Check if this matches our procedure
            # For approaches with variants, require exact match on the variant
            # For SIDs/STARs, use prefix matching
            matched = False
            for prefix in proc_id_prefixes:
                if subsection == "F":  # Approach - more precise matching
                    if proc_id == prefix or proc_id.startswith(prefix + " "):
                        matched = True
                        break
                else:  # SID/STAR - prefix matching
                    if proc_id.startswith(prefix):
                        matched = True
                        break
            if not matched:
                continue

            # Parse the leg
            leg = parse_procedure_leg(line, line_subsection)
            if leg:
                all_legs.append(leg)
                found_subsection = line_subsection

    if not all_legs:
        return None

    # Update procedure type based on what we found
    if found_subsection == "D":
        procedure_type = "SID"
    elif found_subsection == "E":
        procedure_type = "STAR"
    elif found_subsection == "F":
        procedure_type = "APPROACH"
        # Extract runway from first leg's procedure ID if not already set
        if not runway and all_legs:
            first_proc = all_legs[0]
            # The procedure ID is in the original line, but we can infer from context

    # Organize legs by transition type
    common_legs: list[ProcedureLeg] = []
    transitions: dict[str, list[ProcedureLeg]] = {}
    runway_transitions: dict[str, list[ProcedureLeg]] = {}

    for leg in all_legs:
        if leg.transition.startswith("RW"):
            if leg.transition not in runway_transitions:
                runway_transitions[leg.transition] = []
            runway_transitions[leg.transition].append(leg)
        elif leg.transition and leg.transition != "ALL":
            if leg.transition not in transitions:
                transitions[leg.transition] = []
            transitions[leg.transition].append(leg)
        else:
            common_legs.append(leg)

    # Sort legs within each group
    common_legs.sort(key=lambda x: x.sequence)
    for trans_legs in transitions.values():
        trans_legs.sort(key=lambda x: x.sequence)
    for trans_legs in runway_transitions.values():
        trans_legs.sort(key=lambda x: x.sequence)

    # Filter to specific transition if requested
    if transition:
        transition = transition.upper()
        if transition in transitions:
            transitions = {transition: transitions[transition]}
        else:
            # Transition not found - return None or empty transitions
            transitions = {}

    # Determine identifier
    identifier = proc_id_prefixes[0] if proc_id_prefixes else procedure_name

    return CifpProcedureDetail(
        airport=airport,
        identifier=identifier,
        procedure_type=procedure_type,
        approach_type=approach_type,
        runway=runway,
        common_legs=common_legs,
        transitions=transitions,
        runway_transitions=runway_transitions,
    )
