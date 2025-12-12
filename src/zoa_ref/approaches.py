"""STAR to approach connection lookup.

This module finds approach procedures (IAPs) that connect directly to a given
STAR via shared waypoints. When a STAR's waypoint matches an IAF (Initial
Approach Fix) on an approach, aircraft can fly directly from the STAR to the
approach without requiring radar vectors.

Uses a hybrid approach:
- STAR waypoints: Fetched from navdata API (reliable, structured data)
- Approach IAF/IFs: Extracted via OCR from PDF charts (until API available)
"""

import io
import re
from dataclasses import dataclass

from zoa_ref.charts import ChartInfo, fetch_charts_from_api, download_pdf
from zoa_ref.navdata import get_star_data


# Noise words that appear in airport names or common text, not actual waypoints
NOISE_WORDS = {
    "RNAV", "RADAR", "TURBO", "CLIMB", "CROSS", "BELOW", "ABOVE",
    "SPEED", "CHART", "STARS", "NOTAM", "NIGHT", "SOUTH", "NORTH",
    "WEST", "EAST", "PROPS", "UNTIL", "AFTER", "PRIOR", "DIRECT",
    "DESCEND", "MAINTAIN", "EXCEPT", "ARRIVAL", "EXPECT", "ASSIGN",
    "TOWER", "APPROACH", "CONTACT", "GROUND", "CENTER", "TRANS",
    "VISUAL", "PROC", "MISSED", "HOLDING", "PATTERN", "COURSE",
    "FINAL", "INITI", "INTER", "ALPHA", "BRAVO", "INDIA",
    "TAHOE", "RENO", "INTL", "METRO", "MUNI", "COUNTY", "FIELD",
    "ROUTE",
}


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

    @property
    def entry_fixes(self) -> list[str]:
        """All valid entry fixes (IAFs + IFs)."""
        return list(set(self.iaf_waypoints + self.if_waypoints))


def extract_pdf_text(pdf_data: bytes) -> str:
    """Extract all text from a PDF."""
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(pdf_data))
    text_parts = []
    for page in reader.pages:
        text = page.extract_text() or ""
        text_parts.append(text)
    return "\n".join(text_parts)


def extract_waypoints(text: str) -> list[str]:
    """Extract 5-letter waypoint identifiers from text."""
    waypoint_pattern = r'\b([A-Z]{5})\b'
    potential_waypoints = set(re.findall(waypoint_pattern, text))
    waypoints = sorted(potential_waypoints - NOISE_WORDS)
    return waypoints


def extract_landing_runways(text: str) -> list[str]:
    """Extract landing runway designations from STAR text."""
    runways = []
    ldg_patterns = [
        r"Ldg\s+Rwy[s]?\s+(\d{1,2}[LRC]?(?:[/]\d{0,2}[LRC]?)?)",
        r"Landing\s+Rwy[s]?\s+(\d{1,2}[LRC]?(?:[/]\d{0,2}[LRC]?)?)",
        r"Runways?\s+(\d{1,2}[LRC]?(?:[/]\d{0,2}[LRC]?)?)\s+only",
    ]

    for pattern in ldg_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        for m in matches:
            if m not in runways:
                runways.append(m)

    return runways


def extract_approach_entry_fixes(text: str) -> tuple[list[str], list[str]]:
    """
    Extract entry fix waypoints from approach chart text.

    Returns:
        Tuple of (iaf_waypoints, if_waypoints)
        - IAFs are marked with "(IAF)" - Initial Approach Fix
        - IFs are marked with "(IF)" - Intermediate Fix

    Pilots can begin an approach at an IAF, or at an IF if there's no
    preceding IAF on that segment.
    """
    iaf_waypoints = []
    if_waypoints = []
    lines = text.split('\n')

    for i, line in enumerate(lines):
        # Check for IAF markers
        if '(IAF)' in line or 'IAF' in line.split():
            _extract_nearby_waypoints(lines, i, iaf_waypoints)

        # Check for IF markers (Intermediate Fix)
        if '(IF)' in line or '(IF/IAF)' in line:
            _extract_nearby_waypoints(lines, i, if_waypoints)

    return iaf_waypoints, if_waypoints


def _extract_nearby_waypoints(lines: list[str], index: int, waypoint_list: list[str]) -> None:
    """Extract 5-letter waypoints from lines adjacent to the given index."""
    check_lines = []
    if index > 0:
        check_lines.append(lines[index - 1])
    check_lines.append(lines[index])
    if index < len(lines) - 1:
        check_lines.append(lines[index + 1])

    for check_line in check_lines:
        waypoints_nearby = re.findall(r'\b([A-Z]{5})\b', check_line)
        for wp in waypoints_nearby:
            if wp not in NOISE_WORDS and wp not in waypoint_list:
                waypoint_list.append(wp)


def extract_runway_from_name(chart_name: str) -> str | None:
    """Extract runway designation from an approach chart name."""
    rwy_match = re.search(r"RWY\s+(\d{1,2}[LRC]?)", chart_name)
    if rwy_match:
        return rwy_match.group(1)
    return None


def analyze_star_from_navdata(airport: str, star_name: str) -> StarAnalysis | None:
    """Analyze a STAR using the navdata API.

    This is the preferred method as it provides reliable, structured data.

    Args:
        airport: Airport code (e.g., "RNO")
        star_name: STAR name (e.g., "SCOLA1", "SCOLA ONE")

    Returns:
        StarAnalysis with waypoints, or None if not found in API
    """
    star_data = get_star_data(airport, star_name)
    if not star_data:
        return None

    return StarAnalysis(
        name=star_data.identifier,
        waypoints=star_data.waypoints,
        landing_runways=[],  # Not available from navdata API
    )


def analyze_star_from_chart(chart: ChartInfo) -> StarAnalysis | None:
    """Analyze a STAR chart via OCR to extract waypoints and landing runways.

    This is the fallback method when navdata API doesn't have the STAR.
    Results are cached per AIRAC cycle for fast repeated lookups.

    Args:
        chart: ChartInfo for the STAR chart

    Returns:
        StarAnalysis with waypoints and landing runways, or None if failed
    """
    from zoa_ref import cache

    airac = cache.extract_airac_from_url(chart.pdf_path)

    # Try cache first
    if airac:
        cached = cache.get_cached_analysis(
            chart.faa_ident, chart.chart_name, "star", airac
        )
        if cached:
            return StarAnalysis(
                name=cached["name"],
                waypoints=cached["waypoints"],
                landing_runways=cached["landing_runways"],
            )

    # Download and analyze via OCR
    pdf_data = download_pdf(chart.pdf_path)
    if not pdf_data:
        return None

    text = extract_pdf_text(pdf_data)
    waypoints = extract_waypoints(text)
    landing_runways = extract_landing_runways(text)

    result = StarAnalysis(
        name=chart.chart_name,
        waypoints=waypoints,
        landing_runways=landing_runways,
    )

    # Cache result
    if airac:
        cache.cache_analysis(
            chart.faa_ident,
            chart.chart_name,
            "star",
            {
                "name": result.name,
                "waypoints": result.waypoints,
                "landing_runways": result.landing_runways,
            },
            airac,
        )

    return result


def analyze_star(chart: ChartInfo, airport: str | None = None) -> StarAnalysis | None:
    """Analyze a STAR to extract waypoints.

    Uses a hybrid approach:
    1. Try navdata API first (reliable, structured data)
    2. Fall back to OCR from PDF chart if API doesn't have the data

    Args:
        chart: ChartInfo for the STAR chart
        airport: Airport code (required for navdata API lookup)

    Returns:
        StarAnalysis with waypoints, or None if analysis failed
    """
    # Try navdata API first if we have the airport code
    if airport:
        navdata_result = analyze_star_from_navdata(airport, chart.chart_name)
        if navdata_result:
            return navdata_result

    # Fall back to OCR
    return analyze_star_from_chart(chart)


def analyze_approach(chart: ChartInfo) -> ApproachAnalysis | None:
    """Analyze an approach chart to extract entry fix waypoints (IAFs, IFs).

    Results are cached per AIRAC cycle for fast repeated lookups.
    """
    from zoa_ref import cache

    airac = cache.extract_airac_from_url(chart.pdf_path)

    # Try cache first
    if airac:
        cached = cache.get_cached_analysis(
            chart.faa_ident, chart.chart_name, "iap", airac
        )
        if cached:
            return ApproachAnalysis(
                name=cached["name"],
                runway=cached.get("runway"),
                iaf_waypoints=cached["iaf_waypoints"],
                if_waypoints=cached["if_waypoints"],
            )

    # Download and analyze
    pdf_data = download_pdf(chart.pdf_path)
    if not pdf_data:
        return None

    text = extract_pdf_text(pdf_data)
    iaf_waypoints, if_waypoints = extract_approach_entry_fixes(text)
    runway = extract_runway_from_name(chart.chart_name)

    result = ApproachAnalysis(
        name=chart.chart_name,
        runway=runway,
        iaf_waypoints=iaf_waypoints,
        if_waypoints=if_waypoints,
    )

    # Cache result
    if airac:
        cache.cache_analysis(
            chart.faa_ident,
            chart.chart_name,
            "iap",
            {
                "name": result.name,
                "runway": result.runway,
                "iaf_waypoints": result.iaf_waypoints,
                "if_waypoints": result.if_waypoints,
            },
            airac,
        )

    return result


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

    Uses a hybrid approach for STAR analysis:
    - Primary: navdata API (reliable, structured data)
    - Fallback: OCR from PDF chart

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

    # Find the specified STAR chart (needed for fallback OCR)
    star_chart = find_star_chart(charts, star_name)
    if not star_chart:
        return None, []

    # Analyze the STAR (tries navdata API first, falls back to OCR)
    star_analysis = analyze_star(star_chart, airport=airport)
    if not star_analysis:
        return None, []

    # Get all approach charts
    iap_charts = [c for c in charts if c.chart_code == "IAP" and "CONT." not in c.chart_name]

    # Analyze each approach and find connections
    connections = []
    star_waypoints = set(star_analysis.waypoints)

    for iap_chart in iap_charts:
        iap_analysis = analyze_approach(iap_chart)
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
    approaches: list[tuple[str, str]]  # List of (approach_name, fix_type)


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
        iap_analysis = analyze_approach(iap_chart)
        if not iap_analysis:
            continue

        # Check if fix is an IAF
        if fix_upper in iap_analysis.iaf_waypoints:
            approaches.append((iap_analysis.name, "IAF"))
        # Check if fix is an IF (but not already added as IAF)
        elif fix_upper in iap_analysis.if_waypoints:
            approaches.append((iap_analysis.name, "IF"))

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
        iafs = [(name, ft) for name, ft in result.approaches if ft == "IAF"]
        ifs = [(name, ft) for name, ft in result.approaches if ft == "IF"]

        if iafs:
            lines.append(f"As IAF ({len(iafs)}):")
            for name, _ in iafs:
                lines.append(f"  - {name}")

        if ifs:
            if iafs:
                lines.append("")
            lines.append(f"As IF ({len(ifs)}):")
            for name, _ in ifs:
                lines.append(f"  - {name}")

    return "\n".join(lines)
