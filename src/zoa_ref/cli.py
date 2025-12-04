"""CLI interface for ZOA Reference Tool lookups."""

import threading
import time

import click
from .browser import BrowserSession, _calculate_viewport_size
from .charts import (
    ChartQuery, lookup_chart, list_charts, ZOA_AIRPORTS,
    lookup_chart_via_api, ChartMatch,
)
from .routes import search_routes, open_routes_browser, RouteSearchResult


def _is_page_alive(page) -> bool:
    """Check if a page is still alive by attempting a simple operation."""
    try:
        page.evaluate("1")
        return True
    except Exception:
        return False


def _wait_for_input_or_close(
    session: BrowserSession,
    prompt: str = "Press Enter to close browser...",
    page=None,
) -> bool:
    """Wait for user input or browser/page close.

    Returns True if browser/page was closed by user, False if Enter was pressed.
    """
    input_received = threading.Event()

    def wait_for_input():
        try:
            input()
            input_received.set()
        except EOFError:
            input_received.set()

    click.echo(prompt)
    input_thread = threading.Thread(target=wait_for_input, daemon=True)
    input_thread.start()

    while True:
        # Check if browser disconnected or page was closed
        if not session.is_connected:
            click.echo("\nBrowser closed.")
            return True
        if page is not None and not _is_page_alive(page):
            click.echo("\nBrowser closed.")
            return True
        if input_received.is_set():
            return False
        time.sleep(0.1)


@click.group(invoke_without_command=True)
@click.pass_context
def main(ctx):
    """ZOA Reference CLI - Quick lookups to ZOA's Reference Tool.

    Run without arguments to enter interactive mode.

    Examples:

        zoa chart OAK CNDEL5     - Open the CNDEL FIVE PDF directly

        zoa charts SFO ILS 28L   - Open ILS 28L, browse other SFO charts

        zoa list OAK             - List all charts available for OAK

        zoa route SFO LAX        - Look up routes from SFO to LAX
    """
    if ctx.invoked_subcommand is None:
        interactive_mode()


@main.command()
@click.argument("query", nargs=-1, required=True)
@click.option("--headless", is_flag=True, help="Run browser in headless mode (outputs PDF URL)")
def chart(query: tuple[str, ...], headless: bool):
    """Look up a chart and open the PDF directly.

    Opens the PDF in the browser for viewing. Use 'charts' command instead
    if you want to stay on the Reference Tool page to browse other charts.

    Examples:

        zoa chart OAK CNDEL5     - CNDEL FIVE departure

        zoa chart OAK ILS 28R    - ILS or LOC RWY 28R approach

        zoa chart SFO RNAV 28L   - RNAV approach to runway 28L
    """
    query_str = " ".join(query)
    _lookup_chart_api(query_str, headless=headless)


@main.command()
@click.argument("query", nargs=-1, required=True)
def charts(query: tuple[str, ...]):
    """Look up a chart and stay on the Reference Tool page.

    Opens the chart in the Reference Tool, allowing you to browse
    other charts for the same airport. Use 'chart' command instead
    if you just want to view a single PDF.

    Examples:

        zoa charts OAK CNDEL5    - Open CNDEL FIVE, browse other OAK charts

        zoa charts SFO ILS 28L   - Open ILS 28L, browse other SFO charts
    """
    query_str = " ".join(query)
    _lookup_chart(query_str, headless=False, browse=True)


@main.command("list")
@click.argument("airport")
def list_cmd(airport: str):
    """List all charts for an airport.

    Example: zoa list OAK
    """
    airport = airport.upper()
    if airport not in ZOA_AIRPORTS:
        click.echo(f"Warning: {airport} is not a known ZOA airport")

    click.echo(f"Fetching charts for {airport}...")

    with BrowserSession(headless=True) as session:
        page = session.new_page()
        charts = list_charts(page, airport)

        if charts:
            click.echo(f"\nAvailable charts for {airport}:")
            click.echo("-" * 40)
            for chart in charts:
                click.echo(f"  {chart}")
            click.echo(f"\nTotal: {len(charts)} charts")
        else:
            click.echo(f"No charts found for {airport}")


@main.command()
def airports():
    """List all supported ZOA airports."""
    click.echo("Supported ZOA airports:")
    click.echo("-" * 40)

    # Group airports by type
    major = ["SFO", "OAK", "SJC", "SMF", "RNO", "FAT", "MRY", "BAB"]
    minor = [a for a in ZOA_AIRPORTS if a not in major]

    click.echo("Major airports:")
    click.echo(f"  {', '.join(major)}")
    click.echo("\nOther airports:")
    click.echo(f"  {', '.join(minor)}")


@main.command()
@click.argument("departure")
@click.argument("arrival")
@click.option("--browser", is_flag=True, help="Open browser instead of CLI display")
@click.option("--all-routes", "-a", is_flag=True, help="Show all real world routes (default: top 5)")
@click.option("--flights", "-f", is_flag=True, help="Show recent flights (hidden by default)")
@click.option("--top", "-n", type=int, default=5, help="Number of real world routes to show (default: 5)")
def route(departure: str, arrival: str, browser: bool, all_routes: bool, flights: bool, top: int):
    """Look up routes between two airports.

    Examples:

        zoa route SFO LAX           - Show routes (top 5 real world)

        zoa route SFO LAX -a        - Show all real world routes

        zoa route SFO LAX -f        - Include recent flights

        zoa route SFO LAX -a -f     - Show everything

        zoa route SFO LAX -n 10     - Show top 10 real world routes

        zoa route OAK SAN --browser - Open browser to routes page
    """
    departure = departure.upper()
    arrival = arrival.upper()

    click.echo(f"Searching routes: {departure} -> {arrival}...")

    if browser:
        # Browser mode: open and keep open
        with BrowserSession(headless=False) as session:
            page = session.new_page()
            success = open_routes_browser(page, departure, arrival)
            if success:
                _wait_for_input_or_close(session, "Routes page open. Press Enter to close browser...", page)
            else:
                _wait_for_input_or_close(session, "Failed to load routes page. Press Enter to close browser...", page)
    else:
        # CLI mode: scrape and display
        with BrowserSession(headless=True) as session:
            page = session.new_page()
            result = search_routes(page, departure, arrival)
            if result:
                _display_routes(result, max_real_world=None if all_routes else top, show_flights=flights)
            else:
                click.echo("Failed to retrieve routes.", err=True)


def _display_routes(result: RouteSearchResult, max_real_world: int | None = 5, show_flights: bool = False) -> None:
    """Display route search results in formatted CLI output."""
    click.echo()

    # TEC/AAR/ADR Routes
    _display_tec_aar_adr_table(result.tec_aar_adr)

    # LOA Rules
    _display_loa_rules_table(result.loa_rules)

    # Real World Routes
    _display_real_world_table(result.real_world, max_routes=max_real_world)

    # Recent Flights (only if requested)
    if show_flights:
        _display_recent_flights_table(result.recent_flights)


def _display_tec_aar_adr_table(routes: list) -> None:
    """Display TEC/AAR/ADR table with formatting."""
    click.echo("=" * 80)
    click.echo("TEC/AAR/ADR ROUTES")
    click.echo("=" * 80)

    if not routes:
        click.echo("  No TEC/AAR/ADR routes found.")
        click.echo()
        return

    # Header
    click.echo(f"{'Dep Rwy':<10} {'Arr Rwy':<10} {'Types':<10} Route")
    click.echo("-" * 80)

    for r in routes:
        click.echo(f"{r.dep_runway:<10} {r.arr_runway:<10} {r.types:<10} {r.route}")

    click.echo(f"\nTotal: {len(routes)} route(s)")
    click.echo()


def _display_loa_rules_table(rules: list) -> None:
    """Display LOA Rules table with formatting."""
    click.echo("=" * 80)
    click.echo("LOA RULES")
    click.echo("=" * 80)

    if not rules:
        click.echo("  No LOA rules found.")
        click.echo()
        return

    # Header
    click.echo(f"{'Route':<35} {'RNAV?':<8} Notes")
    click.echo("-" * 80)

    for r in rules:
        # Truncate route if too long
        route_display = r.route[:33] + ".." if len(r.route) > 35 else r.route
        click.echo(f"{route_display:<35} {r.rnav:<8} {r.notes}")

    click.echo(f"\nTotal: {len(rules)} rule(s)")
    click.echo()


def _display_real_world_table(routes: list, max_routes: int | None = None) -> None:
    """Display Real World Routes table with formatting."""
    click.echo("=" * 80)
    click.echo("REAL WORLD ROUTES")
    click.echo("=" * 80)

    if not routes:
        click.echo("  No real world routes found.")
        click.echo()
        return

    # Limit routes if max_routes is set
    display_routes = routes if max_routes is None else routes[:max_routes]
    truncated = max_routes is not None and len(routes) > max_routes

    # Header
    click.echo(f"{'Freq':<10} {'Route':<45} Altitude")
    click.echo("-" * 80)

    for r in display_routes:
        # Truncate route if too long
        route_display = r.route[:43] + ".." if len(r.route) > 45 else r.route
        click.echo(f"{r.frequency:<10} {route_display:<45} {r.altitude}")

    if truncated:
        click.echo(f"\nShowing top {max_routes} of {len(routes)} routes (use -a for all)")
    else:
        click.echo(f"\nTotal: {len(routes)} route(s)")
    click.echo()


def _display_recent_flights_table(flights: list) -> None:
    """Display Recent Flights table with formatting."""
    click.echo("=" * 80)
    click.echo("RECENT FLIGHTS")
    click.echo("=" * 80)

    if not flights:
        click.echo("  No recent flights found.")
        click.echo()
        return

    # Header
    click.echo(f"{'Callsign':<12} {'Type':<8} {'Route':<40} Altitude")
    click.echo("-" * 80)

    for f in flights:
        # Truncate route if too long
        route_display = f.route[:38] + ".." if len(f.route) > 40 else f.route
        click.echo(f"{f.callsign:<12} {f.aircraft_type:<8} {route_display:<40} {f.altitude}")

    click.echo(f"\nTotal: {len(flights)} flight(s)")
    click.echo()


def _display_chart_matches(matches: list[ChartMatch], max_display: int = 10) -> None:
    """Display a list of matching charts."""
    click.echo("\nMatching charts:")
    click.echo("-" * 60)
    for i, match in enumerate(matches[:max_display]):
        chart = match.chart
        type_str = chart.chart_code if chart.chart_code else "?"
        click.echo(f"  [{type_str:<4}] {chart.chart_name} (score: {match.score:.2f})")
    if len(matches) > max_display:
        click.echo(f"  ... and {len(matches) - max_display} more")


def _lookup_chart_api(query_str: str, headless: bool = False) -> str | None:
    """Look up a chart using the API.

    Args:
        query_str: The chart query string (e.g., "OAK CNDEL5")
        headless: If True, just output the PDF URL; otherwise open in browser

    Returns the PDF URL if found, None otherwise.
    """
    try:
        parsed = ChartQuery.parse(query_str)
        click.echo(f"Looking up: {parsed.airport} - {parsed.chart_name}")
        if parsed.chart_type.value != "unknown":
            click.echo(f"  Detected type: {parsed.chart_type.value.upper()}")
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        return None

    pdf_url, matches = lookup_chart_via_api(parsed)

    if pdf_url:
        if headless:
            click.echo(pdf_url)
        else:
            # Open in browser
            import webbrowser
            click.echo(f"Opening chart: {matches[0].chart.chart_name if matches else 'chart'}")
            webbrowser.open(f"{pdf_url}#view=FitV")
        return pdf_url

    # No unambiguous match found
    if matches:
        # Ambiguous match - show candidates
        click.echo(f"Ambiguous match for '{parsed.chart_name}':")
        _display_chart_matches(matches)
        click.echo("\nTry a more specific query.")
    else:
        click.echo(f"No charts found for {parsed.airport}", err=True)

    return None


def _lookup_chart(
    query_str: str,
    headless: bool = False,
    session: BrowserSession | None = None,
    browse: bool = False,
) -> str | None:
    """Internal function to look up a chart.

    Args:
        query_str: The chart query string (e.g., "OAK CNDEL5")
        headless: Run browser in headless mode
        session: Existing browser session to use
        browse: If True, stay on Reference Tool page; if False, navigate to PDF URL

    Returns the PDF URL if found, None otherwise.
    """
    try:
        parsed = ChartQuery.parse(query_str)
        click.echo(f"Looking up: {parsed.airport} - {parsed.chart_name}")
        if parsed.chart_type.value != "unknown":
            click.echo(f"  Detected type: {parsed.chart_type.value.upper()}")
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        return None

    own_session = session is None
    if own_session:
        # Use larger window for browse mode (charts command)
        window_size = _calculate_viewport_size() if browse and not headless else None
        session = BrowserSession(headless=headless, window_size=window_size)
        session.start()

    try:
        page = session.new_page()
        pdf_url = lookup_chart(page, parsed)

        if pdf_url:
            if headless:
                click.echo(pdf_url)
            else:
                # Navigate directly to PDF unless in browse mode
                if not browse:
                    page.goto(f"{pdf_url}#view=FitV")
                else:
                    # For browse mode, modify the embedded PDF to fit to height
                    page.evaluate("""() => {
                        const obj = document.querySelector('object[data*=".PDF"]');
                        if (obj && obj.data && !obj.data.includes('#')) {
                            obj.data = obj.data + '#view=FitV';
                        }
                    }""")
                click.echo("Chart found! Browser will remain open.")
        else:
            if not headless:
                click.echo("Could not find chart. Browser will remain open for manual navigation.")
            else:
                click.echo("Could not find chart.", err=True)

        if own_session and not headless:
            _wait_for_input_or_close(session, page=page)

        return pdf_url
    finally:
        if own_session:
            session.stop()


def interactive_mode():
    """Run in interactive mode for continuous lookups."""
    click.echo("ZOA Reference CLI - Interactive Mode")
    click.echo("=" * 50)
    click.echo("Commands:")
    click.echo("  <airport> <chart>  - Look up a chart (e.g., OAK CNDEL5)")
    click.echo("  route <dep> <arr>  - Look up routes (e.g., route SFO LAX)")
    click.echo("  list <airport>     - List charts for an airport")
    click.echo("  airports           - List all supported airports")
    click.echo("  help               - Show this help")
    click.echo("  quit / exit / q    - Exit the program")
    click.echo("=" * 50)
    click.echo()

    session = BrowserSession(headless=False)
    session.start()

    try:
        while True:
            if not session.is_connected:
                click.echo("\nBrowser closed. Exiting.")
                break

            try:
                query = click.prompt("zoa", prompt_suffix="> ").strip()
            except (EOFError, KeyboardInterrupt):
                click.echo("\nGoodbye!")
                break

            if not query:
                continue

            lower_query = query.lower()

            if lower_query in ("quit", "exit", "q"):
                click.echo("Goodbye!")
                break

            if lower_query == "help":
                click.echo("Commands:")
                click.echo("  <airport> <chart>  - Look up a chart (e.g., OAK CNDEL5)")
                click.echo("  route <dep> <arr>  - Look up routes (e.g., route SFO LAX)")
                click.echo("  list <airport>     - List charts for an airport")
                click.echo("  airports           - List all supported airports")
                click.echo("  quit / exit / q    - Exit the program")
                click.echo()
                continue

            if lower_query == "airports":
                click.echo("Supported airports:")
                click.echo(f"  {', '.join(ZOA_AIRPORTS)}")
                click.echo()
                continue

            if lower_query.startswith("list "):
                airport = query[5:].strip().upper()
                click.echo(f"Fetching charts for {airport}...")
                page = session.new_page()
                charts = list_charts(page, airport)
                page.close()

                if charts:
                    click.echo(f"Charts for {airport}:")
                    for chart in charts:
                        click.echo(f"  {chart}")
                else:
                    click.echo(f"No charts found for {airport}")
                click.echo()
                continue

            if lower_query.startswith("route "):
                parts = query[6:].strip().upper().split()
                if len(parts) >= 2:
                    departure, arrival = parts[0], parts[1]
                    click.echo(f"Searching routes: {departure} -> {arrival}...")
                    page = session.new_page()
                    result = search_routes(page, departure, arrival)
                    page.close()

                    if result:
                        _display_routes(result)
                    else:
                        click.echo("Failed to retrieve routes.")
                else:
                    click.echo("Usage: route <departure> <arrival>  (e.g., route SFO LAX)")
                click.echo()
                continue

            # Treat as chart lookup
            try:
                parsed = ChartQuery.parse(query)
                click.echo(f"Looking up: {parsed.airport} - {parsed.chart_name}")

                page = session.new_page()
                pdf_url = lookup_chart(page, parsed)

                if pdf_url:
                    click.echo("Chart found!")
                else:
                    click.echo("Could not find chart automatically. Check the browser.")
                click.echo()

            except ValueError as e:
                click.echo(f"Error: {e}")
                click.echo("Format: <airport> <chart_name>  (e.g., OAK CNDEL5)")
                click.echo()

    finally:
        session.stop()


if __name__ == "__main__":
    main()
