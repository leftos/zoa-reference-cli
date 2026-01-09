"""Display and formatting functions for CLI output."""

import click

from .airways import AirwaySearchResult
from .atis import AtisInfo
from .charts import ChartMatch
from .cifp import CifpProcedureDetail, ProcedureLeg
from .descent import DescentResult, DescentMode, FixDescentResult
from .icao import AirlineSearchResult, AirportSearchResult, AircraftSearchResult
from .mea import MeaResult
from .navaids import NavaidSearchResult
from .positions import PositionSearchResult
from .procedures import ProcedureMatch
from .routes import RouteSearchResult
from .scratchpads import ScratchpadResult, ScratchpadFacility


def print_table_header(title: str, header: str) -> None:
    """Print standard table header with title and column headers."""
    click.echo()
    click.echo("=" * 80)
    click.echo(title)
    click.echo("=" * 80)
    click.echo(header)
    click.echo("-" * 80)


def print_table_empty(title: str, message: str) -> None:
    """Print empty table with title and message."""
    click.echo()
    click.echo("=" * 80)
    click.echo(title)
    click.echo("=" * 80)
    click.echo(f"  {message}")
    click.echo()


def display_routes(
    result: RouteSearchResult,
    max_real_world: int | None = 5,
    show_flights: bool = False,
) -> None:
    """Display route search results in formatted CLI output."""
    # Check if all results are empty
    has_any = (
        result.tec_aar_adr
        or result.loa_rules
        or result.real_world
        or (show_flights and result.recent_flights)
    )

    if not has_any:
        click.echo("\nNo routes found.")
        return

    click.echo()

    # TEC/AAR/ADR Routes
    display_tec_aar_adr_table(result.tec_aar_adr)

    # LOA Rules
    display_loa_rules_table(result.loa_rules)

    # Real World Routes
    display_real_world_table(result.real_world, max_routes=max_real_world)

    # Recent Flights (only if requested)
    if show_flights:
        display_recent_flights_table(result.recent_flights)


def display_tec_aar_adr_table(routes: list) -> None:
    """Display TEC/AAR/ADR table with formatting."""
    if not routes:
        return

    click.echo("=" * 80)
    click.echo("TEC/AAR/ADR ROUTES")
    click.echo("=" * 80)

    # Header
    click.echo(f"{'Dep Rwy':<10} {'Arr Rwy':<10} {'Types':<10} Route")
    click.echo("-" * 80)

    for r in routes:
        click.echo(f"{r.dep_runway:<10} {r.arr_runway:<10} {r.types:<10} {r.route}")
    click.echo()


def display_loa_rules_table(rules: list) -> None:
    """Display LOA Rules table with formatting."""
    if not rules:
        return

    click.echo("=" * 80)
    click.echo("LOA RULES")
    click.echo("=" * 80)

    # Header
    click.echo(f"{'Route':<35} {'RNAV?':<8} Notes")
    click.echo("-" * 80)

    for r in rules:
        # Truncate route if too long
        route_display = r.route[:33] + ".." if len(r.route) > 35 else r.route
        click.echo(f"{route_display:<35} {r.rnav:<8} {r.notes}")
    click.echo()


def display_real_world_table(routes: list, max_routes: int | None = None) -> None:
    """Display Real World Routes table with formatting."""
    if not routes:
        return

    click.echo("=" * 80)
    click.echo("REAL WORLD ROUTES")
    click.echo("=" * 80)

    # Limit routes if max_routes is set
    display_routes_list = routes if max_routes is None else routes[:max_routes]
    truncated = max_routes is not None and len(routes) > max_routes

    # Header
    click.echo(f"{'Freq':<10} {'Route':<45} Altitude")
    click.echo("-" * 80)

    for r in display_routes_list:
        # Truncate route if too long
        route_display = r.route[:43] + ".." if len(r.route) > 45 else r.route
        click.echo(f"{r.frequency:<10} {route_display:<45} {r.altitude}")

    if truncated:
        click.echo(
            f"\nShowing top {max_routes} of {len(routes)} routes (use -a for all)"
        )
    click.echo()


def display_recent_flights_table(flights: list) -> None:
    """Display Recent Flights table with formatting."""
    if not flights:
        return

    click.echo("=" * 80)
    click.echo("RECENT FLIGHTS")
    click.echo("=" * 80)

    # Header
    click.echo(f"{'Callsign':<12} {'Type':<8} {'Route':<40} Altitude")
    click.echo("-" * 80)

    for f in flights:
        # Truncate route if too long
        route_display = f.route[:38] + ".." if len(f.route) > 40 else f.route
        click.echo(
            f"{f.callsign:<12} {f.aircraft_type:<8} {route_display:<40} {f.altitude}"
        )
    click.echo()


def display_airlines(result: AirlineSearchResult) -> None:
    """Display airline search results in formatted CLI output."""
    if not result.results:
        print_table_empty("AIRLINE CODES", f"No airlines found for '{result.query}'.")
        return

    print_table_header(
        "AIRLINE CODES",
        f"{'ICAO':<8} {'Telephony':<15} {'Name':<35} Country",
    )

    for airline in result.results:
        name_display = (
            airline.name[:33] + ".." if len(airline.name) > 35 else airline.name
        )
        click.echo(
            f"{airline.icao_id:<8} {airline.telephony:<15} {name_display:<35} {airline.country}"
        )


def display_airport_codes(result: AirportSearchResult) -> None:
    """Display airport code search results in formatted CLI output."""
    if not result.results:
        print_table_empty("AIRPORT CODES", f"No airports found for '{result.query}'.")
        return

    print_table_header(
        "AIRPORT CODES",
        f"{'ICAO':<8} {'Local':<8} Name",
    )

    for airport in result.results:
        click.echo(f"{airport.icao_id:<8} {airport.local_id:<8} {airport.name}")


def display_aircraft(result: AircraftSearchResult) -> None:
    """Display aircraft search results in formatted CLI output."""
    if not result.results:
        print_table_empty("AIRCRAFT TYPES", f"No aircraft found for '{result.query}'.")
        return

    print_table_header(
        "AIRCRAFT TYPES",
        f"{'Type':<8} {'Manufacturer/Model':<30} {'Eng':<5} {'Wt':<4} {'CWT':<5} {'SRS':<5} LAHSO",
    )

    for ac in result.results:
        mfr_model = f"{ac.manufacturer} {ac.model}"
        mfr_display = mfr_model[:28] + ".." if len(mfr_model) > 30 else mfr_model
        click.echo(
            f"{ac.type_designator:<8} {mfr_display:<30} {ac.engine:<5} "
            f"{ac.faa_weight:<4} {ac.cwt:<5} {ac.srs:<5} {ac.lahso}"
        )


def display_atis(atis_list: list[AtisInfo]) -> None:
    """Display ATIS information in formatted CLI output."""
    for atis in atis_list:
        click.echo()
        click.echo("=" * 80)
        click.echo(f"ATIS - {atis.airport}")
        click.echo("=" * 80)
        click.echo(atis.raw_text)
    click.echo()


def display_chart_matches(matches: list[ChartMatch]) -> None:
    """Display numbered list of matching charts."""
    click.echo("\nMultiple charts found:")
    click.echo("-" * 60)
    for i, match in enumerate(matches, start=1):
        chart = match.chart
        type_str = chart.chart_code if chart.chart_code else "?"
        click.echo(
            f"  [{i}] [{type_str:<4}] {chart.chart_name} (score: {match.score:.2f})"
        )
    click.echo()


def display_procedure_matches(matches: list[ProcedureMatch]) -> None:
    """Display numbered list of matching procedures."""
    click.echo("\nMultiple procedures found:")
    click.echo("-" * 60)
    for i, match in enumerate(matches, start=1):
        click.echo(f"  [{i}] {match.procedure.name} (score: {match.score:.2f})")
    click.echo()


def display_positions(result: PositionSearchResult) -> None:
    """Display position search results in formatted CLI output."""
    if not result.results:
        print_table_empty("POSITIONS", f"No positions found for '{result.query}'.")
        return

    print_table_header(
        "POSITIONS",
        f"{'Name':<25} {'TCP':<6} {'Callsign':<15} {'Radio Name':<18} Freq",
    )

    for pos in result.results:
        name_display = pos.name[:23] + ".." if len(pos.name) > 25 else pos.name
        callsign_display = (
            pos.callsign[:13] + ".." if len(pos.callsign) > 15 else pos.callsign
        )
        radio_display = (
            pos.radio_name[:16] + ".." if len(pos.radio_name) > 18 else pos.radio_name
        )
        click.echo(
            f"{name_display:<25} {pos.tcp:<6} {callsign_display:<15} {radio_display:<18} {pos.frequency}"
        )


def display_scratchpads(result: ScratchpadResult) -> None:
    """Display scratchpad results in formatted CLI output."""
    if not result.scratchpads:
        print_table_empty(
            "SCRATCHPADS", f"No scratchpads found for '{result.facility}'."
        )
        return

    print_table_header(
        f"SCRATCHPADS - {result.facility}",
        f"{'Code':<12} Meaning",
    )

    for sp in result.scratchpads:
        click.echo(f"{sp.code:<12} {sp.meaning}")


def display_scratchpad_facilities(facilities: list[ScratchpadFacility]) -> None:
    """Display available scratchpad facilities."""
    if not facilities:
        click.echo("\nNo facilities found.")
        return

    click.echo("\nAvailable facilities:")
    click.echo("-" * 40)
    # Display as comma-separated list
    values = [fac.value for fac in facilities]
    click.echo(f"  {', '.join(values)}")


def display_navaids(result: NavaidSearchResult) -> None:
    """Display navaid search results in compact CLI output."""
    if not result.results:
        click.echo(f"\nNo navaids found for '{result.query}'.")
        return

    for navaid in result.results:
        # Format: FMG - MUSTANG VORTAC (Las Vegas, NV) [36.0228, -115.0033]
        location_parts = []
        if navaid.city:
            location_parts.append(navaid.city)
        if navaid.state:
            location_parts.append(navaid.state)
        location = ", ".join(location_parts) if location_parts else "Unknown"

        click.echo(
            f"{navaid.ident} - {navaid.name} {navaid.navaid_type} "
            f"({location}) [{navaid.latitude:.4f}, {navaid.longitude:.4f}]"
        )


def display_descent(result: DescentResult) -> None:
    """Display descent calculation results."""
    if result.mode == DescentMode.DISTANCE_NEEDED:
        assert result.target_alt is not None and result.distance_needed is not None
        alt_change = result.current_alt - result.target_alt
        click.echo(
            f"\n{alt_change:,} ft descent requires {result.distance_needed:.1f} nm"
        )
    else:
        assert result.distance_nm is not None and result.altitude_at is not None
        assert result.altitude_lost is not None
        click.echo(
            f"\nAt {result.distance_nm:.1f} nm: {result.altitude_at:,} ft "
            f"({result.altitude_lost:,} ft descended)"
        )


def display_fix_descent(result: FixDescentResult) -> None:
    """Display fix-to-fix descent calculation results."""
    click.echo(
        f"\n{result.from_point} -> {result.to_point}: "
        f"{result.distance_nm:.1f} nm, {result.altitude_available:,} ft descent available"
    )


def display_airway(result: AirwaySearchResult) -> None:
    """Display airway information with fixes.

    Shows the airway identifier, direction, and list of fixes.
    Navaids show their full name in parentheses.
    If a highlight fix is specified, it's marked with brackets.
    """
    from .navaids import get_navaid_name

    if not result.airway:
        click.echo(f"\nAirway '{result.query}' not found.")
        return

    airway = result.airway

    # Header with direction
    direction_str = f" ({airway.direction})" if airway.direction else ""
    click.echo()
    click.echo(f"AIRWAY {airway.identifier}{direction_str} - {len(airway.fixes)} fixes")
    click.echo()

    # Build fix strings
    fix_parts = []
    for fix in airway.fixes:
        # Look up navaid name if it's a navaid
        if fix.is_navaid:
            name = get_navaid_name(fix.identifier)
            fix_str = f"{fix.identifier} ({name})" if name else fix.identifier
        else:
            fix_str = fix.identifier

        # Highlight the specified fixes in yellow
        if result.highlight_fixes and fix.identifier in result.highlight_fixes:
            fix_str = click.style(f"[{fix_str}]", fg="yellow", bold=True)

        fix_parts.append(fix_str)

    # Join with ".." and wrap to reasonable line length
    # Use click.unstyle to get visible length (without ANSI codes)
    max_width = 75
    lines = []
    current_line = ""
    current_visible_len = 0

    for part in fix_parts:
        separator = ".." if current_line else ""
        part_visible_len = len(click.unstyle(part))
        test_visible_len = current_visible_len + len(separator) + part_visible_len

        if test_visible_len > max_width and current_line:
            lines.append(current_line + "..")
            current_line = part
            current_visible_len = part_visible_len
        else:
            current_line = current_line + separator + part
            current_visible_len = test_visible_len

    if current_line:
        lines.append(current_line)

    for line in lines:
        click.echo(line)
    click.echo()


def display_mea(result: MeaResult) -> None:
    """Display MEA analysis results."""
    click.echo()

    if result.max_mea is None:
        click.echo("No airways found in route (or no MEA data available).")
        return

    # Show safety status if altitude was provided
    if result.altitude is not None:
        if result.is_safe:
            click.echo(
                click.style(
                    f"SAFE: {result.altitude:,} ft meets MEA requirement of {result.max_mea:,} ft",
                    fg="green",
                )
            )
        else:
            click.echo(
                click.style(
                    f"WARNING: {result.altitude:,} ft is BELOW required MEA of {result.max_mea:,} ft",
                    fg="yellow",
                    bold=True,
                )
            )
        click.echo()
    else:
        click.echo(f"Maximum MEA: {result.max_mea:,} ft")
        click.echo()

    # Show segments with MEA data
    if result.segments:
        if result.altitude is not None:
            click.echo(f"Segments exceeding {result.altitude:,} ft:")
        else:
            click.echo("Segments with MEA restrictions:")
        click.echo("-" * 60)

        # Sort segments by MEA (highest first)
        sorted_segments = sorted(result.segments, key=lambda s: s.mea, reverse=True)

        for seg in sorted_segments:
            moca_str = f" (MOCA: {seg.moca:,})" if seg.moca else ""
            click.echo(
                f"  {seg.airway} {seg.segment_start} -> {seg.segment_end}: "
                f"MEA {seg.mea:,} ft{moca_str}"
            )
    elif result.altitude is not None and result.is_safe:
        click.echo("All segments meet the specified altitude requirement.")


def _format_restriction(leg: ProcedureLeg) -> tuple[str, str]:
    """Format altitude and speed restrictions for display below a fix.

    Returns tuple of (altitude_str, speed_str) for separate display lines.
    """
    alt_str = str(leg.altitude) if leg.altitude and leg.altitude.altitude1 else ""
    speed_str = str(leg.speed) if leg.speed and leg.speed.speed else ""
    return alt_str, speed_str


def _get_unique_fixes(legs: list[ProcedureLeg]) -> list[ProcedureLeg]:
    """Get unique fixes from a leg list, keeping first occurrence."""
    seen = set()
    result = []
    for leg in legs:
        fix_id = leg.fix_identifier
        # Skip runway/airport references
        if fix_id.startswith("RW") or fix_id.startswith("K") and len(fix_id) == 4:
            continue
        if fix_id not in seen:
            seen.add(fix_id)
            result.append(leg)
    return result


def _route_signature(fixes: list[ProcedureLeg]) -> str:
    """Create a signature string for a route to detect identical routes.

    Combines fix names with their altitude and speed restrictions.
    """
    parts = []
    for leg in fixes:
        alt, spd = _format_restriction(leg)
        parts.append(f"{leg.fix_identifier}|{alt}|{spd}")
    return ";".join(parts)


def _format_runway_label(rwy_name: str) -> str:
    """Format CIFP runway name to readable label.

    CIFP uses special suffixes:
    - B = both (L and R)
    - A = all runways
    - L/C/R = standard left/center/right

    Examples:
        RW28B -> RWY 28s
        RW28L -> RWY 28L
        RW10 -> RWY 10
    """
    # Strip "RW" prefix
    rwy = rwy_name[2:] if rwy_name.startswith("RW") else rwy_name

    # Handle special CIFP suffixes
    if rwy.endswith("B"):
        # "Both" - 28B means 28L and 28R
        return f"RWY {rwy[:-1]}L/{rwy[:-1]}R"
    elif rwy.endswith("A"):
        # "All" runways with this heading
        return f"RWY {rwy[:-1]} (all)"

    return f"RWY {rwy}"


def _draw_horizontal_route(fixes: list[ProcedureLeg], indent: str = "  ") -> None:
    """Draw fixes horizontally with restrictions below.

    Layout:
      SCOLA--->TEXSS--->HLDMM--->CHIME--->KLOCK
      FL280-FL240       16000A   13000-12000
                        280K-    250K

    Each fix is only padded as much as needed for its restriction text.
    """
    if not fixes:
        return

    arrow = "--->"

    # Calculate per-fix column widths (just enough to fit fix name and restrictions)
    col_widths = []
    for leg in fixes:
        fix_name = leg.fix_identifier
        alt, spd = _format_restriction(leg)
        width = max(len(fix_name), len(alt), len(spd))
        col_widths.append(width)

    # Build the three lines: fixes, altitudes, speeds
    fix_line = indent
    alt_line = indent
    spd_line = indent

    for i, leg in enumerate(fixes):
        fix_name = leg.fix_identifier
        alt, spd = _format_restriction(leg)
        width = col_widths[i]

        if i > 0:
            fix_line += arrow
            alt_line += " " * len(arrow)
            spd_line += " " * len(arrow)

        fix_line += fix_name.ljust(width)
        alt_line += alt.ljust(width)
        spd_line += spd.ljust(width)

    click.echo(fix_line)
    # Only print restriction lines if there's content
    if alt_line.strip():
        click.echo(alt_line)
    if spd_line.strip():
        click.echo(spd_line)


def display_procedure_detail(proc: CifpProcedureDetail) -> None:
    """Display procedure as horizontal ASCII art diagram.

    Shows the procedure with:
    - Fix names in brackets laid out horizontally
    - Altitude restrictions on line below
    - Speed restrictions on line below that
    - Transitions shown as separate routes
    """
    click.echo()

    # Header
    proc_type_display = proc.procedure_type
    if proc.approach_type:
        proc_type_display = f"{proc.approach_type} APPROACH"
    if proc.runway:
        proc_type_display += f" RWY {proc.runway}"

    click.echo("=" * 70)
    click.echo(f"  {proc.airport} - {proc.identifier} ({proc_type_display})")
    click.echo("=" * 70)

    # Get common route fixes
    common_fixes = _get_unique_fixes(proc.common_legs)

    if proc.procedure_type == "STAR":
        _display_star_horizontal(proc, common_fixes)
    elif proc.procedure_type == "SID":
        _display_sid_horizontal(proc, common_fixes)
    else:  # APPROACH
        _display_approach_horizontal(proc, common_fixes)

    click.echo()


def _display_star_horizontal(proc: CifpProcedureDetail, common_fixes: list[ProcedureLeg]) -> None:
    """Display STAR procedure horizontally."""

    common_fix_names = {f.fix_identifier for f in common_fixes}

    # Prepare transition data
    meaningful_transitions: dict[str, list[ProcedureLeg]] = {}
    for name, legs in proc.transitions.items():
        trans_fixes = _get_unique_fixes(legs)
        trans_only = [l for l in trans_fixes if l.fix_identifier not in common_fix_names]
        # Skip if only fix is the transition name itself (redundant)
        if trans_only and not (len(trans_only) == 1 and trans_only[0].fix_identifier == name):
            meaningful_transitions[name] = trans_only

    # Prepare runway transition data (grouped by identical routes)
    rwy_groups: dict[str, list[str]] = {}  # route_signature -> [rwy_names]
    rwy_fixes_map: dict[str, list[ProcedureLeg]] = {}  # route_signature -> fixes

    for rwy_name, legs in proc.runway_transitions.items():
        rwy_fixes = _get_unique_fixes(legs)
        rwy_only = [l for l in rwy_fixes if l.fix_identifier not in common_fix_names]
        if rwy_only:
            sig = _route_signature(rwy_only)
            if sig not in rwy_groups:
                rwy_groups[sig] = []
                rwy_fixes_map[sig] = rwy_only
            rwy_groups[sig].append(rwy_name)

    # If single transition + single runway group, show everything as one continuous route
    if len(meaningful_transitions) == 1 and len(rwy_groups) == 1:
        trans_name, trans_fixes = next(iter(meaningful_transitions.items()))

        # Build fully merged route: transition -> common -> runway
        continuous_route: list[ProcedureLeg] = list(trans_fixes)

        for fix in common_fixes:
            if not continuous_route or fix.fix_identifier != continuous_route[-1].fix_identifier:
                continuous_route.append(fix)

        rwy_fixes = next(iter(rwy_fixes_map.values()))
        for fix in rwy_fixes:
            if not continuous_route or fix.fix_identifier != continuous_route[-1].fix_identifier:
                continuous_route.append(fix)

        rwy_names = next(iter(rwy_groups.values()))
        rwy_labels = [_format_runway_label(n) for n in sorted(rwy_names)]
        combined_rwy = rwy_labels[0]
        for label in rwy_labels[1:]:
            rwy_num = label.replace("RWY ", "")
            combined_rwy += f"/{rwy_num}"

        click.echo()
        click.echo(f"  {combined_rwy}:")
        click.echo()
        _draw_horizontal_route(continuous_route, "    ")
        return

    # Entry transitions (show separately if multiple)
    if meaningful_transitions:
        click.echo()
        click.secho("  TRANSITIONS:", fg="green", bold=True)
        for name, trans_only in sorted(meaningful_transitions.items()):
            click.echo()
            click.echo(f"  {name}:")
            _draw_horizontal_route(trans_only, "    ")

    # Merge common route + runway transition when there's only one runway group
    if len(rwy_groups) == 1:
        # Build merged route: common -> runway
        merged_route: list[ProcedureLeg] = list(common_fixes)

        # Add runway transition (skip duplicate first fix)
        rwy_fixes = next(iter(rwy_fixes_map.values()))
        for fix in rwy_fixes:
            if not merged_route or fix.fix_identifier != merged_route[-1].fix_identifier:
                merged_route.append(fix)

        # Get runway label
        rwy_names = next(iter(rwy_groups.values()))
        rwy_labels = [_format_runway_label(n) for n in sorted(rwy_names)]
        combined_rwy = rwy_labels[0]
        for label in rwy_labels[1:]:
            rwy_num = label.replace("RWY ", "")
            combined_rwy += f"/{rwy_num}"

        # Add header if there were transitions shown above
        if meaningful_transitions:
            click.echo()
            click.secho("  COMMON ROUTE:", fg="yellow", bold=True)

        click.echo()
        click.echo(f"  {combined_rwy}:")
        click.echo()
        _draw_horizontal_route(merged_route, "    ")
    else:
        # Multiple runway transitions - show common route and transitions separately
        if common_fixes:
            click.echo()
            click.secho("  COMMON ROUTE:", fg="yellow", bold=True)
            click.echo()
            _draw_horizontal_route(common_fixes, "    ")

        if rwy_groups:
            click.echo()
            click.secho("  RUNWAY TRANSITIONS:", fg="cyan", bold=True)

            for sig, rwy_names in sorted(rwy_groups.items(), key=lambda x: x[1][0]):
                rwy_labels = [_format_runway_label(n) for n in sorted(rwy_names)]
                if not rwy_labels:
                    continue
                combined_label = rwy_labels[0]
                for label in rwy_labels[1:]:
                    rwy_num = label.replace("RWY ", "")
                    combined_label += f"/{rwy_num}"
                click.echo()
                click.echo(f"  {combined_label}:")
                _draw_horizontal_route(rwy_fixes_map[sig], "    ")


def _display_sid_horizontal(proc: CifpProcedureDetail, common_fixes: list[ProcedureLeg]) -> None:
    """Display SID procedure horizontally."""

    common_fix_names = {f.fix_identifier for f in common_fixes}

    # Prepare runway transition data (grouped by identical routes)
    rwy_groups: dict[str, list[str]] = {}
    rwy_fixes_map: dict[str, list[ProcedureLeg]] = {}

    for rwy_name, legs in proc.runway_transitions.items():
        rwy_fixes = _get_unique_fixes(legs)
        rwy_only = [l for l in rwy_fixes if l.fix_identifier not in common_fix_names]
        if rwy_only:
            sig = _route_signature(rwy_only)
            if sig not in rwy_groups:
                rwy_groups[sig] = []
                rwy_fixes_map[sig] = rwy_only
            rwy_groups[sig].append(rwy_name)

    # Prepare exit transition data
    meaningful_transitions: dict[str, list[ProcedureLeg]] = {}
    for name, legs in proc.transitions.items():
        trans_fixes = _get_unique_fixes(legs)
        trans_only = [l for l in trans_fixes if l.fix_identifier not in common_fix_names]
        if trans_only:
            meaningful_transitions[name] = trans_only

    # Check if we can display as a single continuous route:
    # - Exactly one runway transition group
    # - At most one exit transition (or none)
    can_merge = len(rwy_groups) == 1 and len(meaningful_transitions) <= 1

    if can_merge:
        # Build single continuous route: runway -> common -> exit
        continuous_route: list[ProcedureLeg] = []

        # Add runway transition
        rwy_fixes = next(iter(rwy_fixes_map.values()))
        continuous_route.extend(rwy_fixes)

        # Add common route (skip if first fix duplicates last of previous)
        for fix in common_fixes:
            if not continuous_route or fix.fix_identifier != continuous_route[-1].fix_identifier:
                continuous_route.append(fix)

        # Add exit transition (if any), skip duplicate first fix
        exit_name = ""
        if meaningful_transitions:
            exit_name, exit_fixes = next(iter(meaningful_transitions.items()))
            for fix in exit_fixes:
                if not continuous_route or fix.fix_identifier != continuous_route[-1].fix_identifier:
                    continuous_route.append(fix)

        # Get runway label
        rwy_names = next(iter(rwy_groups.values()))
        rwy_labels = [_format_runway_label(n) for n in sorted(rwy_names)]
        combined_rwy = rwy_labels[0]
        for label in rwy_labels[1:]:
            rwy_num = label.replace("RWY ", "")
            combined_rwy += f"/{rwy_num}"

        # Display as single route
        label = combined_rwy
        if exit_name:
            label += f" -> {exit_name}"
        click.echo()
        click.echo(f"  {label}:")
        click.echo()
        _draw_horizontal_route(continuous_route, "    ")
        return

    # Otherwise, display sections separately

    # Runway transitions
    if rwy_groups:
        click.echo()
        click.secho("  RUNWAY TRANSITIONS:", fg="cyan", bold=True)

        for sig, rwy_names in sorted(rwy_groups.items(), key=lambda x: x[1][0]):
            rwy_labels = [_format_runway_label(n) for n in sorted(rwy_names)]
            if not rwy_labels:
                continue
            combined_label = rwy_labels[0]
            for label in rwy_labels[1:]:
                rwy_num = label.replace("RWY ", "")
                combined_label += f"/{rwy_num}"
            click.echo()
            click.echo(f"  {combined_label}:")
            _draw_horizontal_route(rwy_fixes_map[sig], "    ")

    # Common route
    if common_fixes:
        click.echo()
        click.secho("  COMMON ROUTE:", fg="yellow", bold=True)
        click.echo()
        _draw_horizontal_route(common_fixes, "    ")

    # Exit transitions
    if meaningful_transitions:
        click.echo()
        click.secho("  EXIT TRANSITIONS:", fg="green", bold=True)

        for name, trans_only in sorted(meaningful_transitions.items()):
            click.echo()
            click.echo(f"  {name}:")
            _draw_horizontal_route(trans_only, "    ")


def _display_approach_horizontal(proc: CifpProcedureDetail, common_fixes: list[ProcedureLeg]) -> None:
    """Display approach procedure horizontally."""

    common_fix_names = {f.fix_identifier for f in common_fixes}

    # Transitions
    if proc.transitions:
        click.echo()
        click.secho("  TRANSITIONS:", fg="green", bold=True)

        for name, legs in sorted(proc.transitions.items()):
            trans_fixes = _get_unique_fixes(legs)
            # Filter out common route fixes
            trans_only = [l for l in trans_fixes if l.fix_identifier not in common_fix_names]
            if trans_only:
                click.echo()
                click.echo(f"  {name}:")
                _draw_horizontal_route(trans_only, "    ")

    # Final approach
    if common_fixes:
        click.echo()
        click.secho("  FINAL APPROACH:", fg="yellow", bold=True)
        click.echo()
        _draw_horizontal_route(common_fixes, "    ")
