"""Display and formatting functions for CLI output."""

import click

from .atis import AtisInfo
from .charts import ChartMatch
from .icao import AirlineSearchResult, AirportSearchResult, AircraftSearchResult
from .procedures import ProcedureMatch
from .routes import RouteSearchResult


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


def print_table_footer(count: int, item_name: str) -> None:
    """Print standard table footer with count."""
    click.echo(f"\nTotal: {count} {item_name}")
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

    print_table_footer(len(result.results), "airline(s)")


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

    print_table_footer(len(result.results), "airport(s)")


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

    print_table_footer(len(result.results), "aircraft type(s)")


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
