"""STAR to approach connection lookup.

This module finds approach procedures (IAPs) that connect directly to a given
STAR via shared waypoints. When a STAR's waypoint matches an IAF (Initial
Approach Fix) on an approach, aircraft can fly directly from the STAR to the
approach without requiring radar vectors.

Uses FAA CIFP (Coded Instrument Flight Procedures) data for reliable,
structured procedure information.
"""

import re
from dataclasses import dataclass

from zoa_ref.charts import ChartInfo, fetch_charts_from_api


@dataclass
class ApproachConnection:
    """A connection from a STAR to an approach via a shared waypoint."""

    star_name: str
    approach_name: str
    connecting_fix: str
    fix_type: str  # "IAF" or "IF"
    approach_runway: str | None = None


@dataclass
class StarAnalysis:
    """Analysis results for a STAR chart."""

    name: str
    waypoints: list[str]
    landing_runways: list[str]


@dataclass
class ApproachAnalysis:
    """Analysis results for an approach chart."""

    name: str
    runway: str | None
    iaf_waypoints: list[str]
    if_waypoints: list[str]
    feeder_waypoints: list[str] | None = None  # Transition entry fixes (feeder routes)
    feeder_paths: dict[str, str] | None = None  # Feeder fix -> destination IAF/IF

    def __post_init__(self):
        if self.feeder_waypoints is None:
            self.feeder_waypoints = []
        if self.feeder_paths is None:
            self.feeder_paths = {}

    @property
    def entry_fixes(self) -> list[str]:
        """All valid entry fixes (IAFs + IFs)."""
        return list(set(self.iaf_waypoints + self.if_waypoints))


def extract_runway_from_name(chart_name: str) -> str | None:
    """Extract runway designation from an approach chart name."""
    rwy_match = re.search(r"RWY\s+(\d{1,2}[LRC]?)", chart_name)
    if rwy_match:
        return rwy_match.group(1)
    return None


def analyze_star(airport: str, star_name: str) -> StarAnalysis | None:
    """Analyze a STAR using CIFP data.

    Args:
        airport: Airport code (e.g., "RNO")
        star_name: STAR name (e.g., "SCOLA1", "SCOLA ONE")

    Returns:
        StarAnalysis with waypoints, or None if not found
    """
    from zoa_ref.cifp import get_star_data

    star_data = get_star_data(airport, star_name)
    if not star_data:
        return None

    return StarAnalysis(
        name=star_data.identifier,
        waypoints=star_data.waypoints,
        landing_runways=[],  # Not available from CIFP
    )


def analyze_approach(airport: str, chart_name: str) -> ApproachAnalysis | None:
    """Analyze an approach using CIFP data.

    Args:
        airport: Airport code (e.g., "RNO", "OAK")
        chart_name: Chart name (e.g., "ILS OR LOC RWY 28R", "RNAV (GPS) Z RWY 17L")

    Returns:
        ApproachAnalysis with IAF/IF waypoints, or None if not found
    """
    from zoa_ref.cifp import get_approaches_for_airport

    approaches = get_approaches_for_airport(airport)
    if not approaches:
        return None

    # Try to match chart_name to a CIFP approach
    # Chart names: "ILS OR LOC RWY 28R", "RNAV (GPS) Z RWY 17L"
    # CIFP approach_id: "I28R", "H17LZ"

    # Extract runway from chart name
    runway = extract_runway_from_name(chart_name)
    if not runway:
        return None

    chart_name_upper = chart_name.upper()

    # Determine expected approach type prefixes (may have multiple)
    # CIFP uses 'H' for RNAV/GPS and 'R' for RNAV, but charts may be named inconsistently
    type_prefixes: list[str] = []
    if "RNAV" in chart_name_upper or "GPS" in chart_name_upper or "RNP" in chart_name_upper:
        type_prefixes = ["H", "R"]  # Try both RNAV variants
    elif "ILS" in chart_name_upper:
        type_prefixes = ["I"]
    elif "LOC" in chart_name_upper:
        type_prefixes = ["L"]
    elif "VOR/DME" in chart_name_upper:
        type_prefixes = ["D"]
    elif "VOR" in chart_name_upper:
        type_prefixes = ["V"]
    elif "NDB" in chart_name_upper:
        type_prefixes = ["N"]
    elif "TACAN" in chart_name_upper:
        type_prefixes = ["T"]

    # Extract variant letter from chart name (X, Y, Z, W)
    chart_variant = None
    for v in "XYZW":
        if f" {v} " in chart_name_upper or chart_name_upper.endswith(f" {v}"):
            chart_variant = v
            break

    # Find matching approach
    matched_approach = None
    for approach_id, approach in approaches.items():
        # Check runway match
        if approach.runway != runway:
            continue

        # Check type match if we have type prefixes
        if type_prefixes and not any(approach_id.startswith(p) for p in type_prefixes):
            continue

        # Check variant match
        approach_variant = None
        if approach_id[-1] in "XYZW":
            approach_variant = approach_id[-1]

        if chart_variant:
            # Chart has a variant, approach must match
            if approach_variant != chart_variant:
                continue
            # Exact variant match found
            matched_approach = approach
            break
        else:
            # No variant in chart name, any matching approach works
            if matched_approach is None:
                matched_approach = approach

    if not matched_approach:
        return None

    # Extract IAF, IF, and feeder fixes
    iaf_waypoints = list(set(matched_approach.iaf_fixes))
    if_waypoints = list(set(matched_approach.if_fixes))
    feeder_waypoints = list(set(matched_approach.feeder_fixes))
    feeder_paths = matched_approach.feeder_paths

    return ApproachAnalysis(
        name=chart_name,
        runway=runway,
        iaf_waypoints=sorted(iaf_waypoints),
        if_waypoints=sorted(if_waypoints),
        feeder_waypoints=sorted(feeder_waypoints),
        feeder_paths=feeder_paths,
    )


def find_star_chart(charts: list[ChartInfo], star_name: str) -> ChartInfo | None:
    """Find a STAR chart by name using the same fuzzy matching as chart lookup.

    This uses ChartQuery.parse to normalize the name (e.g., CCR2 -> CCR TWO)
    and find_chart_by_name for fuzzy matching (e.g., CCR TWO -> CONCORD TWO).
    """
    from zoa_ref.charts import ChartQuery, ChartType, find_chart_by_name

    # Filter to only STAR charts (excluding continuation pages)
    stars = [c for c in charts if c.chart_code == "STAR" and "CONT." not in c.chart_name]

    if not stars:
        return None

    # Create a query with the STAR name - use a dummy airport since we already have charts
    # The ChartQuery.parse normalizes the name (e.g., "CCR2" -> "CCR TWO")
    try:
        query = ChartQuery.parse(f"XXX {star_name}")
        # Force the chart type to STAR for proper matching
        query = ChartQuery(
            airport=query.airport,
            chart_name=query.chart_name,
            chart_type=ChartType.STAR,
        )
    except ValueError:
        return None

    # Use the same fuzzy matching as chart lookup
    matched_star, _ = find_chart_by_name(stars, query)
    return matched_star


def find_connected_approaches(
    airport: str,
    star_name: str,
) -> tuple[StarAnalysis | None, list[ApproachConnection]]:
    """
    Find approaches that connect directly to a given STAR.

    Args:
        airport: Airport code (e.g., "RNO")
        star_name: STAR name or abbreviation (e.g., "SCOLA1", "SCOLA ONE")

    Returns:
        Tuple of (star_analysis, connections).
        star_analysis is None if the STAR wasn't found.
        connections is a list of ApproachConnection objects.
    """
    # Fetch all charts for the airport
    charts = fetch_charts_from_api(airport)
    if not charts:
        return None, []

    # Find the specified STAR chart (for name normalization)
    star_chart = find_star_chart(charts, star_name)
    if not star_chart:
        return None, []

    # Analyze the STAR using CIFP
    star_analysis = analyze_star(airport, star_chart.chart_name)
    if not star_analysis:
        return None, []

    # Get all approach charts
    iap_charts = [c for c in charts if c.chart_code == "IAP" and "CONT." not in c.chart_name]

    # Analyze each approach and find connections
    connections = []
    star_waypoints = set(star_analysis.waypoints)

    for iap_chart in iap_charts:
        iap_analysis = analyze_approach(airport, iap_chart.chart_name)
        if not iap_analysis or not iap_analysis.entry_fixes:
            continue

        # Find shared waypoints that are IAFs
        iaf_set = set(iap_analysis.iaf_waypoints)
        iaf_connections = star_waypoints & iaf_set

        for fix in iaf_connections:
            connections.append(ApproachConnection(
                star_name=star_analysis.name,
                approach_name=iap_analysis.name,
                connecting_fix=fix,
                fix_type="IAF",
                approach_runway=iap_analysis.runway,
            ))

        # Find shared waypoints that are IFs (but not already added as IAFs)
        if_set = set(iap_analysis.if_waypoints)
        if_connections = (star_waypoints & if_set) - iaf_connections

        for fix in if_connections:
            connections.append(ApproachConnection(
                star_name=star_analysis.name,
                approach_name=iap_analysis.name,
                connecting_fix=fix,
                fix_type="IF",
                approach_runway=iap_analysis.runway,
            ))

    # Sort by runway, then by approach name
    connections.sort(key=lambda c: (c.approach_runway or "", c.approach_name))

    return star_analysis, connections


def format_connections(
    star_analysis: StarAnalysis,
    connections: list[ApproachConnection],
) -> str:
    """Format connection results for display."""
    lines = []

    lines.append(f"{star_analysis.name}")
    lines.append("-" * len(star_analysis.name))

    if star_analysis.landing_runways:
        runways = ", ".join(star_analysis.landing_runways)
        lines.append(f"Landing runways: {runways}")

    lines.append(f"Waypoints: {', '.join(star_analysis.waypoints)}")
    lines.append("")

    if not connections:
        lines.append("No direct approach connections found.")
        lines.append("(Vectors to final approach course may be required)")
    else:
        lines.append("Connected approaches (no vectors required):")
        lines.append("")

        # Group by connecting fix and type for cleaner output
        by_fix: dict[tuple[str, str], list[ApproachConnection]] = {}
        for conn in connections:
            key = (conn.connecting_fix, conn.fix_type)
            if key not in by_fix:
                by_fix[key] = []
            by_fix[key].append(conn)

        for (fix, fix_type), conns in sorted(by_fix.items()):
            lines.append(f"  Via {fix} ({fix_type}):")
            for conn in conns:
                lines.append(f"    - {conn.approach_name}")

    return "\n".join(lines)


def is_star_name(name: str) -> bool:
    """
    Check if a name looks like a STAR name (ends with single digit).

    Examples:
        SCOLA1 -> True
        EMZOH4 -> True
        FMG -> False
        KLOCK -> False
        LIBGE -> False
    """
    return bool(re.match(r"^[A-Z]+\d$", name.upper()))


@dataclass
class FixApproachResult:
    """Result of looking up approaches by fix/waypoint."""

    fix_name: str
    approaches: list[tuple[str, str, str | None]]  # List of (approach_name, fix_type, dest_fix)


def find_approaches_by_fix(
    airport: str,
    fix_name: str,
) -> FixApproachResult | None:
    """
    Find approaches that use a given fix as an entry point (IAF, IF, or feeder).

    Args:
        airport: Airport code (e.g., "RNO")
        fix_name: Fix/waypoint name (e.g., "FMG", "KLOCK")

    Returns:
        FixApproachResult with list of approaches, or None if no charts found.
    """
    # Fetch all charts for the airport
    charts = fetch_charts_from_api(airport)
    if not charts:
        return None

    fix_upper = fix_name.upper()

    # Get all approach charts
    iap_charts = [c for c in charts if c.chart_code == "IAP" and "CONT." not in c.chart_name]

    approaches = []

    for iap_chart in iap_charts:
        iap_analysis = analyze_approach(airport, iap_chart.chart_name)
        if not iap_analysis:
            continue

        # Check if fix is an IAF
        if fix_upper in iap_analysis.iaf_waypoints:
            approaches.append((iap_analysis.name, "IAF", None))
        # Check if fix is an IF (but not already added as IAF)
        elif fix_upper in iap_analysis.if_waypoints:
            approaches.append((iap_analysis.name, "IF", None))
        # Check if fix is a feeder (transition entry point)
        elif iap_analysis.feeder_waypoints and fix_upper in iap_analysis.feeder_waypoints:
            dest_fix = iap_analysis.feeder_paths.get(fix_upper) if iap_analysis.feeder_paths else None
            approaches.append((iap_analysis.name, "Feeder", dest_fix))

    # Sort by approach name
    approaches.sort(key=lambda x: x[0])

    return FixApproachResult(fix_name=fix_upper, approaches=approaches)


def format_fix_approaches(result: FixApproachResult) -> str:
    """Format fix approach results for display."""
    lines = []

    lines.append(f"Approaches via {result.fix_name}")
    lines.append("-" * len(f"Approaches via {result.fix_name}"))
    lines.append("")

    if not result.approaches:
        lines.append(f"No approaches found using {result.fix_name} as an entry fix.")
    else:
        # Group by fix type
        iafs = [(name, ft, dest) for name, ft, dest in result.approaches if ft == "IAF"]
        ifs = [(name, ft, dest) for name, ft, dest in result.approaches if ft == "IF"]
        feeders = [(name, ft, dest) for name, ft, dest in result.approaches if ft == "Feeder"]

        if iafs:
            lines.append(f"As IAF ({len(iafs)}):")
            for name, _, _ in iafs:
                lines.append(f"  - {name}")

        if ifs:
            if iafs:
                lines.append("")
            lines.append(f"As IF ({len(ifs)}):")
            for name, _, _ in ifs:
                lines.append(f"  - {name}")

        if feeders:
            if iafs or ifs:
                lines.append("")
            lines.append(f"As Feeder ({len(feeders)}):")
            for name, _, dest in feeders:
                if dest:
                    lines.append(f"  - {name} (to {dest})")
                else:
                    lines.append(f"  - {name}")

    return "\n".join(lines)
