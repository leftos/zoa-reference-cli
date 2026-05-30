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
USER_AGENT = "ZOA-Reference-CLI/1.0"


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


@dataclass
class FixProcedureUse:
    """A procedure that contains a given fix."""

    airport: str  # e.g., "OAK" (without K prefix)
    procedure_id: str  # Base ID e.g., "EMZOH4", "CNDEL5", "I28R"
    procedure_type: str  # "SID", "STAR", or "APPROACH"
    approach_type: str  # Human-readable approach type (e.g., "ILS"), empty for SID/STAR
    runway: str  # Runway (e.g., "28R"), empty if N/A


@dataclass
class FixUsesResult:
    """Result of searching for all procedures that use a fix."""

    fix: str  # The queried fix name
    procedures: list[FixProcedureUse]


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
        alt1_str = (
            f"FL{self.altitude1 // 100}"
            if self.altitude1 >= 18000
            else f"{self.altitude1}"
        )
        if self.description == "B" and self.altitude2:
            alt2_str = (
                f"FL{self.altitude2 // 100}"
                if self.altitude2 >= 18000
                else f"{self.altitude2}"
            )
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


HOLD_PATH_TERMINATORS = frozenset({"HA", "HF", "HM"})
"""Hold path terminators (hold-at-altitude / -to-fix / -to-manual-termination)."""

PROCEDURE_TURN_TERMINATORS = frozenset({"PI"})
"""Classical procedure-turn (45/180) leg."""


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
    is_fly_over: bool = False  # True if char 40 of desc_code is 'Y'
    rec_navaid: str = ""  # Recommended navaid identifier (cols 50-54)
    theta: float | None = None  # Magnetic bearing from rec_navaid (degrees)
    rho: float | None = None  # Distance from rec_navaid (NM)
    outbound_course: float | None = None  # Outbound course / heading (magnetic degrees)
    leg_distance_nm: float | None = None  # Leg distance (NM) or holding time
    vertical_angle: float | None = None  # Vertical path angle (degrees, signed)
    arc_radius_nm: float | None = None  # RF-arc radius (cols 56-62, thousandths of NM)
    center_fix: str = ""  # RF-arc center fix ident (cols 106-111)
    center_fix_lat: float | None = None  # Resolved from terminal waypoint table
    center_fix_lon: float | None = None  # Resolved from terminal waypoint table

    @property
    def is_hold(self) -> bool:
        """True for HA/HF/HM legs — hold pattern of any kind."""
        return self.path_terminator in HOLD_PATH_TERMINATORS

    @property
    def is_procedure_turn(self) -> bool:
        """True for PI legs — classical procedure turn."""
        return self.path_terminator in PROCEDURE_TURN_TERMINATORS

    @property
    def restrictions_str(self) -> str:
        """Format restrictions as a display string."""
        parts = []
        if self.altitude and self.altitude.altitude1:
            parts.append(str(self.altitude))
        if self.speed and self.speed.speed:
            parts.append(str(self.speed))
        return " ".join(parts)


@dataclass(frozen=True)
class Navaid:
    """A VHF (VOR/DME) or NDB navaid with coordinates.

    Both record types live in CIFP section D and share lat/lon column
    positions, so the same parser handles them; navaid_type differentiates.
    """

    ident: str  # e.g., "OSI", "SFO", "RNO" — 1-4 chars
    navaid_type: str  # "VHF" or "NDB"
    lat: float  # decimal degrees, signed
    lon: float  # decimal degrees, signed (negative = west)
    airport_id: str = ""  # Terminal navaids: parent ICAO; enroute: ""
    frequency_mhz: float | None = None  # Decoded frequency (VHF: MHz; NDB: kHz/1000)


@dataclass
class CifpProcedureDetail:
    """Detailed procedure data with full leg information."""

    airport: str  # e.g., "RNO"
    identifier: str  # e.g., "SCOLA1", "CNDEL5", "H17LZ"
    procedure_type: str  # "SID", "STAR", "APPROACH"
    approach_type: str | None  # e.g., "RNAV (GPS)", "ILS" (only for approaches)
    runway: str | None  # e.g., "17L", "28R"
    common_legs: list[ProcedureLeg]  # Inbound legs up to and including MAP
    transitions: dict[str, list[ProcedureLeg]]  # Transition name -> legs
    runway_transitions: dict[str, list[ProcedureLeg]]  # RW* transitions
    missed_approach_legs: list[ProcedureLeg] = field(default_factory=list)
    """Legs after the MAP (climb-out + hold). Empty for SID/STAR."""
    is_sbas_authorized: bool = False
    """True if the procedure has at least one SBAS continuation record (W).

    Applies only to approaches. Indicates the FAA published SBAS / LPV
    minima authorization for this procedure; the actual minima dataset is
    not parsed (FAS data block parsing is a separate enhancement).
    """

    def _all_legs(self) -> list[ProcedureLeg]:
        legs: list[ProcedureLeg] = list(self.common_legs)
        legs.extend(self.missed_approach_legs)
        for trans_legs in self.transitions.values():
            legs.extend(trans_legs)
        for trans_legs in self.runway_transitions.values():
            legs.extend(trans_legs)
        return legs

    @property
    def has_hold(self) -> bool:
        """True if any leg is a hold (HILPT or missed-approach hold)."""
        return any(leg.is_hold for leg in self._all_legs())

    @property
    def has_procedure_turn(self) -> bool:
        """True if any leg is a classical procedure turn (PI)."""
        return any(leg.is_procedure_turn for leg in self._all_legs())


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
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=CIFP_TIMEOUT) as response:
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


# Waypoint Description Code 4 (position 43, 1-indexed; 42 0-indexed) meanings
# This is the 4th character of the waypoint description field, indicating fix role
WAYPOINT_DESC_CODES = {
    "A": "IAF",  # Initial Approach Fix
    "B": "IF",  # Intermediate Fix
    "C": "",  # Calculated course to fix
    "D": "FAF",  # FAF with calculated course
    "E": "",  # FAF with straight-in minimums (not common)
    "F": "FAF",  # Final Approach Fix
    "I": "IAF",  # Initial Approach Fix (alternate code)
    "M": "MAHP",  # Missed Approach Point
    "P": "",  # Procedure turn fix
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


def find_matching_procedures(airport: str, procedure_name: str) -> list[str]:
    """Find all procedure names that match a query.

    Used for disambiguation when multiple procedures match (e.g., ILS 17R
    matches I17RX, I17RY, I17RZ).

    Args:
        airport: Airport code (e.g., "RNO")
        procedure_name: Procedure query (e.g., "ILS 17R", "SCOLA1")

    Returns:
        List of matching procedure identifiers
    """
    cifp_path = ensure_cifp_data()
    if not cifp_path:
        return []

    airport = airport.upper().lstrip("K")
    procedure_name = procedure_name.upper().strip()
    procedure_name = re.sub(r"\s*\(RNAV\)$", "", procedure_name)

    # Determine what we're looking for
    search_prefix = f"SUSAP K{airport}"
    proc_id_prefix: str | None = None
    subsection_filter: str | None = None

    # Check if it's an approach
    approach_pattern = re.match(
        r"^(ILS|LOC|VOR|RNAV|RNP|GPS|NDB|LDA|SDF|TACAN)\s*"
        r"(?:(?:Y|Z|X|W)\s+)?(?:OR\s+\w+\s+)?(?:RWY\s*)?"
        r"(\d{1,2}[LRC]?)\s*([XYZWABCDEFGH])?$",
        procedure_name,
    )
    if approach_pattern:
        subsection_filter = "F"
        app_type_name = approach_pattern.group(1)
        runway = approach_pattern.group(2)
        variant = approach_pattern.group(3) or ""

        type_map = {
            "ILS": "I",
            "LOC": "L",
            "VOR": "V",
            "RNAV": "H",
            "RNP": "R",
            "GPS": "P",
            "NDB": "N",
            "LDA": "X",
            "SDF": "U",
            "TACAN": "T",
        }
        type_code = type_map.get(app_type_name, "H")

        if variant:
            # Specific variant requested - look for exact match
            proc_id_prefix = f"{type_code}{runway}{variant}"
        else:
            # No variant - look for all variants
            proc_id_prefix = f"{type_code}{runway}"
    else:
        # SID/STAR - check for pattern
        proc_match = re.match(
            r"^([A-Z]+)\s*(\d|ONE|TWO|THREE|FOUR|FIVE|SIX|SEVEN|EIGHT|NINE)$",
            procedure_name,
        )
        if proc_match:
            base_name = proc_match.group(1)
            num_part = proc_match.group(2)
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
        else:
            proc_id_prefix = procedure_name

    if not proc_id_prefix:
        return []

    # Find all matching procedure IDs
    matching_ids: set[str] = set()

    with open(cifp_path, "r", encoding="latin-1") as f:
        for line in f:
            if not line.startswith(search_prefix):
                continue

            if len(line) <= 12:
                continue

            line_subsection = line[12]
            if subsection_filter and line_subsection != subsection_filter:
                continue
            if line_subsection not in ("D", "E", "F"):
                continue

            proc_id = line[13:19].strip()
            if not proc_id:
                continue

            # Check for match
            if proc_id.startswith(proc_id_prefix):
                if line_subsection in ("D", "E"):
                    # SID/STAR - normalize to base ID
                    match = re.match(r"^([A-Z]+\d)", proc_id)
                    if match:
                        matching_ids.add(match.group(1))
                else:
                    # Approach - keep full ID
                    matching_ids.add(proc_id)

    return sorted(matching_ids)


def list_all_procedures(airport: str) -> list[str]:
    """Get all procedure names (SIDs, STARs, approaches) for an airport.

    Returns a list of procedure identifiers suitable for fuzzy matching.

    Args:
        airport: Airport code (e.g., "OAK", "RNO")

    Returns:
        List of procedure names (e.g., ["CNDEL5", "OAK6", "SCOLA1", "ILS17L"])
    """
    cifp_path = ensure_cifp_data()
    if not cifp_path:
        return []

    airport = airport.upper().lstrip("K")
    search_prefix = f"SUSAP K{airport}"

    procedure_ids: set[str] = set()

    with open(cifp_path, "r", encoding="latin-1") as f:
        for line in f:
            if not line.startswith(search_prefix):
                continue

            if len(line) <= 12:
                continue

            subsection = line[12]
            if subsection not in ("D", "E", "F"):
                continue

            # Extract procedure ID
            proc_id = line[13:19].strip()
            if not proc_id:
                continue

            if subsection in ("D", "E"):  # SID or STAR
                # Normalize to base ID (e.g., "CNDEL54" -> "CNDEL5")
                match = re.match(r"^([A-Z]+\d)", proc_id)
                if match:
                    procedure_ids.add(match.group(1))
            else:  # Approach (F)
                # Keep full ID for approaches (e.g., "I17L", "H17LZ")
                # Also add a readable version (e.g., "ILS17L", "RNAV17LZ")
                procedure_ids.add(proc_id)

    return sorted(procedure_ids)


# --- Enhanced Parsing with Altitude/Speed Restrictions ---


def _parse_altitude(alt_str: str) -> int | None:
    """Parse altitude from ARINC 424 format.

    ARINC 424 uses a 5-character altitude field with two encodings:
    - Flight level: "FL280" -> 28,000 ft (FL number × 100)
    - Feet: "01700" -> 1,700 ft (value in feet, zero-padded)

    Matches cifparse 2.0 semantics where altitude is stored as actual feet,
    not tens of feet. See cifparse/records/procedure/widths.py PrimaryIndices
    alt_1 = (84, 89).

    Args:
        alt_str: 5-character altitude string

    Returns:
        Altitude in feet, or None if not specified
    """
    alt_str = alt_str.strip()
    if not alt_str:
        return None

    try:
        if alt_str.startswith("FL"):
            fl_num_str = alt_str[2:].strip().lstrip("0")
            if not fl_num_str:
                return None
            return int(fl_num_str) * 100

        return int(alt_str.lstrip("0") or "0")
    except ValueError:
        return None


def _parse_tenths(raw: str) -> float | None:
    """Decode a 4-char tenths-of-units field (course/distance/bearing/distance).

    ARINC 424 stores these fields as zero-padded integers where the value
    is in tenths of the displayed unit (e.g. course '0900' = 090.0°,
    dist_time '0048' = 4.8 NM). A blank field is None.
    """
    raw = raw.strip()
    if not raw:
        return None
    try:
        return int(raw) / 10.0
    except ValueError:
        return None


def _parse_hundredths_signed(raw: str) -> float | None:
    """Decode a 4-char signed hundredths field (vertical angle).

    Format is sign + 3 digits, e.g. '-285' = -2.85°, ' 305' = 3.05°.
    """
    raw = raw.strip()
    if not raw:
        return None
    sign = -1 if raw.startswith("-") else 1
    digits = raw.lstrip("+-").strip()
    if not digits:
        return None
    try:
        return sign * int(digits) / 100.0
    except ValueError:
        return None


def _parse_arinc_lat(raw: str) -> float | None:
    """Decode a 9-char ARINC 424 latitude field.

    Format: hemisphere ('N'/'S') + DD + MM + SSSS, where SSSS is hundredths
    of seconds. Returns signed decimal degrees. Blank field is None.
    """
    raw = raw.strip()
    if not raw or len(raw) < 9:
        return None
    hemisphere = raw[0]
    try:
        degrees = int(raw[1:3])
        minutes = int(raw[3:5])
        seconds = int(raw[5:9]) / 100.0
    except ValueError:
        return None
    value = degrees + minutes / 60.0 + seconds / 3600.0
    return -value if hemisphere == "S" else value


def _parse_arinc_lon(raw: str) -> float | None:
    """Decode a 10-char ARINC 424 longitude field.

    Format: hemisphere ('E'/'W') + DDD + MM + SSSS. Returns signed decimal
    degrees (negative for west). Blank field is None.
    """
    raw = raw.strip()
    if not raw or len(raw) < 10:
        return None
    hemisphere = raw[0]
    try:
        degrees = int(raw[1:4])
        minutes = int(raw[4:6])
        seconds = int(raw[6:10]) / 100.0
    except ValueError:
        return None
    value = degrees + minutes / 60.0 + seconds / 3600.0
    return -value if hemisphere == "W" else value


@lru_cache(maxsize=1)
def get_navaids() -> dict[str, Navaid]:
    """Return all CIFP section-D navaids (VHF + NDB) keyed by ident.

    VHF and NDB navaids share the lat/lon/ident column layout in their
    primary record (cont_rec_no '0' or '1'). Continuation, simulation, and
    limitation records are skipped.

    Returns:
        Dict mapping ident -> Navaid. Idents are unique within VHF and
        within NDB; on collision the VHF record wins (covers OSI/SFO etc.).
    """
    cifp_path = ensure_cifp_data()
    if not cifp_path:
        return {}

    result: dict[str, Navaid] = {}
    ndb_pending: dict[str, Navaid] = {}
    with open(cifp_path, "r", encoding="latin-1") as f:
        for line in f:
            if len(line) < 51:
                continue
            if line[0] != "S" or line[4] != "D":
                continue
            subsection = line[5]
            if subsection == " ":
                navaid_type = "VHF"
            elif subsection == "B":
                navaid_type = "NDB"
            else:
                continue
            # Skip continuation / simulation / planning records.
            cont_rec_no = line[21] if len(line) > 21 else "0"
            if cont_rec_no not in ("0", "1"):
                continue
            ident = line[13:17].strip()
            if not ident:
                continue
            lat = _parse_arinc_lat(line[32:41])
            lon = _parse_arinc_lon(line[41:51])
            if lat is None or lon is None:
                continue
            airport_id = line[6:10].strip()
            freq_raw = line[22:27].strip() if len(line) > 26 else ""
            frequency_mhz: float | None = None
            if freq_raw.isdigit():
                # VHF stores frequency * 100 (e.g. 11390 = 113.90 MHz).
                # NDB stores frequency * 10 in kHz (e.g. 4000 = 400.0 kHz),
                # which we normalize to MHz so a single field works for both.
                divisor = 100.0 if navaid_type == "VHF" else 10000.0
                frequency_mhz = int(freq_raw) / divisor
            navaid = Navaid(
                ident=ident,
                navaid_type=navaid_type,
                lat=lat,
                lon=lon,
                airport_id=airport_id,
                frequency_mhz=frequency_mhz,
            )
            if navaid_type == "VHF":
                result[ident] = navaid
            else:
                ndb_pending[ident] = navaid
    # NDB doesn't overwrite a VHF with the same ident.
    for ident, navaid in ndb_pending.items():
        result.setdefault(ident, navaid)
    return result


@lru_cache(maxsize=32)
def get_terminal_waypoints(airport: str) -> dict[str, tuple[float, float]]:
    """Return all terminal waypoints (subsection C) for an airport.

    Args:
        airport: ICAO airport code (e.g., "KSFO") or FAA code ("SFO").

    Returns:
        Dict mapping waypoint ident -> (lat, lon) in decimal degrees.
        Empty dict if CIFP data is unavailable or no waypoints match.
    """
    cifp_path = ensure_cifp_data()
    if not cifp_path:
        return {}

    apt = airport.upper().strip()
    if len(apt) == 3:
        apt = f"K{apt}"

    result: dict[str, tuple[float, float]] = {}
    with open(cifp_path, "r", encoding="latin-1") as f:
        for line in f:
            if not line.startswith("SUSAP"):
                continue
            if len(line) < 51:
                continue
            if line[6:10] != apt:
                continue
            if line[12] != "C":
                continue
            ident = line[13:18].strip()
            if not ident:
                continue
            lat = _parse_arinc_lat(line[32:41])
            lon = _parse_arinc_lon(line[41:51])
            if lat is None or lon is None:
                continue
            result[ident] = (lat, lon)
    return result


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

    ARINC 424 column positions (0-indexed half-open ranges, match
    cifparse PrimaryIndices in cifparse/records/procedure/widths.py):
    - 13-19: Procedure identifier
    - 19-20: Route type (procedure type)
    - 20-25: Transition identifier
    - 26-29: Sequence number
    - 29-34: Fix identifier
    - 39-43: Waypoint description (4 chars)
    - 43-44: Turn direction
    - 47-49: Path terminator
    - 82-83: Altitude description
    - 83-84: ATC indicator
    - 84-89: Altitude 1
    - 89-94: Altitude 2
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

    # Skip non-primary records. cont_rec_no (col 38) marks continuation when
    # it isn't '0' or '1'; continuations use a different field layout and are
    # parsed by separate helpers (see is_sbas_authorized on the detail).
    cont_rec_no = line[38] if len(line) > 38 else "0"
    if cont_rec_no not in ("0", "1"):
        return None

    # Extract fields
    route_type = line[19] if len(line) > 19 else ""
    transition = line[20:25].strip()
    sequence_str = line[26:29].strip()
    fix_identifier = line[29:34].strip()
    waypoint_desc = line[39:43] if len(line) > 42 else "    "
    turn_direction = line[43] if len(line) > 43 else " "
    path_terminator = line[47:49].strip() if len(line) > 48 else ""

    # Geometry / navigation fields (cifparse cols 50..78, 102..111)
    rec_navaid = line[50:54].strip() if len(line) > 53 else ""
    arc_radius_str = line[56:62] if len(line) > 61 else ""
    theta_str = line[62:66] if len(line) > 65 else ""
    rho_str = line[66:70] if len(line) > 69 else ""
    course_str = line[70:74] if len(line) > 73 else ""
    dist_time_str = line[74:78] if len(line) > 77 else ""
    vert_angle_str = line[102:106] if len(line) > 105 else ""
    center_fix_str = line[106:111].strip() if len(line) > 110 else ""

    # Altitude fields (cifparse alt_1 = (84, 89), alt_2 = (89, 94))
    alt_desc = line[82] if len(line) > 82 else " "
    alt_1_str = line[84:89] if len(line) > 88 else ""
    alt_2_str = line[89:94] if len(line) > 93 else ""

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

    # A primary record with no path terminator is malformed; drop it. Real
    # continuations have already been filtered by cont_rec_no above, so
    # this no longer accidentally rejects 'W'-application SBAS records.
    if not path_terminator:
        return None

    # Determine fix type from waypoint description code position 4 (char 42).
    # The 4-char field is Type / Performance / Phase / Fix-role; pos 0 is the
    # route-description code, NOT the fix role. parse_approach_record reads
    # line[42] directly; this parser must agree.
    fix_type = (
        WAYPOINT_DESC_CODES.get(waypoint_desc[3], "") if len(waypoint_desc) > 3 else ""
    )

    # Position 2 of desc_code (char 40) = 'Y' marks a fly-over waypoint.
    is_fly_over = len(waypoint_desc) > 1 and waypoint_desc[1] == "Y"

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

    # Route-type codes are subsection-specific (ARINC 424 §5.7):
    #   F (approach): only 'A' is a transition; everything else is main route
    #     (parse_approach_record uses the same rule)
    #   D (SID):    1-6 + T (RNAV departure transition) + V (vector)
    #   E (STAR):   1-6
    # For main-route legs, drop the transition name so the caller can group
    # by transition or treat the empty string as common.
    if subsection == "F":
        transition_codes = {"A"}
    elif subsection == "D":
        transition_codes = {"1", "2", "3", "4", "5", "6", "T", "V"}
    else:  # subsection == "E"
        transition_codes = {"1", "2", "3", "4", "5", "6"}
    if route_type not in transition_codes:
        transition = ""

    arc_radius_nm: float | None = None
    arc_raw = arc_radius_str.strip()
    if arc_raw:
        try:
            arc_radius_nm = int(arc_raw) / 1000.0
        except ValueError:
            arc_radius_nm = None

    return ProcedureLeg(
        fix_identifier=fix_identifier,
        path_terminator=path_terminator,
        turn_direction=turn_direction.strip(),
        altitude=altitude,
        speed=speed,
        transition=transition,
        sequence=sequence,
        fix_type=fix_type,
        is_fly_over=is_fly_over,
        rec_navaid=rec_navaid,
        theta=_parse_tenths(theta_str),
        rho=_parse_tenths(rho_str),
        outbound_course=_parse_tenths(course_str),
        leg_distance_nm=_parse_tenths(dist_time_str),
        vertical_angle=_parse_hundredths_signed(vert_angle_str),
        arc_radius_nm=arc_radius_nm,
        center_fix=center_fix_str,
    )


def _resolve_center_fix_coords(airport: str, legs: list[ProcedureLeg]) -> None:
    """Resolve center_fix idents to (lat, lon) using terminal waypoints.

    Skips legs without a center_fix. The lookup is cheap (single dict
    lookup per RF leg) once the waypoints dict is built, and
    get_terminal_waypoints is lru_cached.
    """
    if not any(leg.center_fix for leg in legs):
        return
    waypoints = get_terminal_waypoints(airport)
    if not waypoints:
        return
    for leg in legs:
        if not leg.center_fix:
            continue
        coords = waypoints.get(leg.center_fix)
        if coords is None:
            continue
        leg.center_fix_lat, leg.center_fix_lon = coords


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
    is_sbas_authorized = False

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
            # For approaches: if variant specified, require exact match; otherwise prefix match
            # For SIDs/STARs: use prefix matching
            matched = False
            for prefix in proc_id_prefixes:
                if subsection == "F":  # Approach
                    # If searching with variant (e.g., I17RZ), require exact match
                    # If no variant (e.g., I17R), use prefix matching to find any variant
                    if len(prefix) > 3 and prefix[-1] in "XYZWABCDEFGH":
                        # Has variant - require exact match
                        if proc_id == prefix:
                            matched = True
                            break
                    else:
                        # No variant - use prefix matching
                        if proc_id.startswith(prefix):
                            matched = True
                            break
                else:  # SID/STAR - prefix matching
                    if proc_id.startswith(prefix):
                        matched = True
                        break
            if not matched:
                continue

            # Detect SBAS authorization continuations on approaches before
            # parse_procedure_leg filters them out as continuation records.
            if (
                line_subsection == "F"
                and len(line) > 39
                and line[38] not in ("0", "1")
                and line[39] == "W"
            ):
                is_sbas_authorized = True
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

    # Resolve RF-arc center fix coordinates from the airport's terminal
    # waypoint table. Lookup happens once per get_procedure_detail call.
    _resolve_center_fix_coords(airport, all_legs)

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

    # Split missed-approach legs off the tail of common_legs for approaches.
    # The MAP fix (WAYPOINT_DESC_CODES "M" — labeled MAHP in the existing
    # mapping) is the boundary: it stays as the last inbound leg, and every
    # leg after it belongs to the climb-out / hold.
    missed_approach_legs: list[ProcedureLeg] = []
    if procedure_type == "APPROACH":
        map_idx: int | None = None
        for i, leg in enumerate(common_legs):
            if leg.fix_type == "MAHP":
                map_idx = i
                break
        if map_idx is not None and map_idx + 1 < len(common_legs):
            missed_approach_legs = common_legs[map_idx + 1 :]
            common_legs = common_legs[: map_idx + 1]

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
        missed_approach_legs=missed_approach_legs,
        is_sbas_authorized=is_sbas_authorized,
    )


_TYPE_KEYWORDS: dict[str, str] = {
    "SID": "SID",
    "STAR": "STAR",
    "APP": "APPROACH",
    "IAP": "APPROACH",
}


def find_fix_uses(
    fix_name: str,
    airport_filter: str | None = None,
    type_filter: str | None = None,
) -> FixUsesResult:
    """Find all procedures (SIDs, STARs, approaches) that contain a fix.

    Scans the entire CIFP file in a single pass. Deduplicates by
    (airport, base_procedure_id, subsection) so each procedure appears once.

    Args:
        fix_name: Fix/waypoint identifier (e.g., "MYJAW", "KLOCK")
        airport_filter: If set, only return procedures at this airport.
        type_filter: If set, only return this procedure type
            ("SID", "STAR", or "APPROACH").

    Returns:
        FixUsesResult with all matching procedures.
    """
    cifp_path = ensure_cifp_data()
    if not cifp_path:
        return FixUsesResult(fix=fix_name, procedures=[])

    fix_name = fix_name.upper().strip()

    # Build airport search prefix if filtering by airport
    airport_prefix: str | None = None
    if airport_filter:
        apt = airport_filter.upper().lstrip("K")
        airport_prefix = f"SUSAP K{apt}"

    # Map type_filter to allowed subsection codes
    allowed_subsections: set[str] | None = None
    if type_filter:
        subsection_for_type = {"SID": {"D"}, "STAR": {"E"}, "APPROACH": {"F"}}
        allowed_subsections = subsection_for_type.get(type_filter)

    # Track unique (airport, base_proc_id, subsection) to deduplicate
    seen: set[tuple[str, str, str]] = set()
    procedures: list[FixProcedureUse] = []

    subsection_type_map = {"D": "SID", "E": "STAR", "F": "APPROACH"}

    with open(cifp_path, "r", encoding="latin-1") as f:
        for line in f:
            if len(line) < 35:
                continue
            if not line.startswith("SUSAP"):
                continue

            # Airport filter: skip lines not matching the target airport
            if airport_prefix and not line.startswith(airport_prefix):
                continue

            subsection = line[12] if len(line) > 12 else ""
            if subsection not in ("D", "E", "F"):
                continue

            # Type filter: skip non-matching subsections
            if allowed_subsections and subsection not in allowed_subsections:
                continue

            # Check if this line's fix matches (position 30-34)
            line_fix = line[29:34].strip()
            if line_fix != fix_name:
                continue

            # Extract airport (position 7-10, strip K prefix)
            airport = line[6:10].strip().lstrip("K")

            # Extract procedure ID and normalize to base ID
            proc_id_raw = line[13:19].strip()
            if not proc_id_raw:
                continue

            if subsection in ("D", "E"):
                # SID/STAR: normalize "CNDEL54" -> "CNDEL5"
                match = re.match(r"^([A-Z]+\d)", proc_id_raw)
                base_id = match.group(1) if match else proc_id_raw
            else:
                # Approach: keep full ID (e.g., "I28R", "H17LZ")
                base_id = proc_id_raw

            key = (airport, base_id, subsection)
            if key in seen:
                continue
            seen.add(key)

            proc_type = subsection_type_map[subsection]
            approach_type = ""
            runway = ""
            if subsection == "F":
                approach_type = _parse_approach_type(base_id)
                runway = _parse_runway_from_approach_id(base_id) or ""

            procedures.append(
                FixProcedureUse(
                    airport=airport,
                    procedure_id=base_id,
                    procedure_type=proc_type,
                    approach_type=approach_type,
                    runway=runway,
                )
            )

    # Sort by airport, then type (STAR, SID, APPROACH), then ID
    type_order = {"STAR": 0, "SID": 1, "APPROACH": 2}
    procedures.sort(
        key=lambda p: (p.airport, type_order.get(p.procedure_type, 9), p.procedure_id)
    )

    return FixUsesResult(fix=fix_name, procedures=procedures)


def parse_uses_filters(
    args: list[str],
) -> tuple[str | None, str | None]:
    """Parse optional airport and type filters from extra arguments.

    Recognizes type keywords (SID, STAR, APP, IAP) and treats anything
    else as an airport filter. A 4-letter ICAO code starting with K
    (e.g., "KAPP") is always treated as an airport, even if the 3-letter
    suffix matches a type keyword.

    Args:
        args: Extra arguments after the fix name.

    Returns:
        Tuple of (airport_filter, type_filter). Either may be None.
    """
    airport_filter: str | None = None
    type_filter: str | None = None

    for arg in args:
        upper = arg.upper()
        # 4-letter K-prefixed codes are always airports (e.g., KAPP, KSFO)
        is_icao = len(upper) == 4 and upper.startswith("K")
        if upper in _TYPE_KEYWORDS and not is_icao:
            type_filter = _TYPE_KEYWORDS[upper]
        else:
            airport_filter = upper

    return airport_filter, type_filter
