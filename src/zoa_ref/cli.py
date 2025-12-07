"""CLI interface for ZOA Reference Tool lookups."""

import os
import re
import shlex
import subprocess
import tempfile
import threading
import time
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path

import click

from .atis import fetch_atis, fetch_all_atis, ATIS_AIRPORTS
from .browser import BrowserSession, _calculate_viewport_size
from .charts import (
    ChartInfo, ChartMatch, ChartQuery, lookup_chart, ZOA_AIRPORTS,
    fetch_charts_from_api, find_all_chart_pages,
    lookup_chart_with_pages, download_and_merge_pdfs, download_and_rotate_pdf,
    detect_pdf_view_mode,
)
from .display import (
    display_routes, display_airlines, display_airport_codes,
    display_aircraft, display_atis, display_chart_matches,
    display_procedure_matches,
)
from .icao import (
    search_airline, search_airport_code, search_aircraft,
    open_codes_browser, CodesPage,
)
from .input import create_prompt_session, prompt_with_history, prompt_single_choice
from .procedures import (
    ProcedureQuery, ProcedureInfo, ProcedureMatch,
    fetch_procedures_list, find_procedure_by_name, find_heading_page,
    find_text_in_section, list_all_procedures, _download_pdf as download_procedure_pdf,
)
from .routes import search_routes, open_routes_browser


# Browser process names mapped to their command names
BROWSERS = {
    "chrome.exe": "chrome",
    "msedge.exe": "msedge",
    "firefox.exe": "firefox",
    "brave.exe": "brave",
    "opera.exe": "opera",
}

# Interactive mode command help lines
INTERACTIVE_HELP_COMMANDS = [
    "  <airport> <chart>  - Look up a chart (e.g., OAK CNDEL5)",
    "  chart <query>      - Same as above (e.g., chart OAK CNDEL5)",
    "  charts <query>     - Browse charts in browser (e.g., charts OAK CNDEL5)",
    "  list <airport>     - List charts for an airport",
    "  route <dep> <arr>  - Look up routes (e.g., route SFO LAX)",
    "  atis <airport>     - Look up ATIS (e.g., atis SFO)",
    "  sop <query>        - Look up SOP/procedure (e.g., sop OAK IFR)",
    "  proc <query>       - Same as above (e.g., proc OAK IFR)",
    "  airline <query>    - Look up airline codes (e.g., airline UAL)",
    "  airport <query>    - Look up airport codes (e.g., airport KSFO)",
    "  aircraft <query>   - Look up aircraft types (e.g., aircraft B738)",
]

# Detailed help for individual commands (used by "help <command>")
COMMAND_HELP = {
    "chart": """
chart - Look up a chart and open the PDF directly

Opens the chart PDF in your browser. Chart names are fuzzy-matched,
so "CNDEL5" will find "CNDEL FIVE". Multi-page charts (with CONT.1,
CONT.2 pages) are automatically merged. Charts are auto-rotated
based on text orientation unless --no-rotate is specified.

\b
Examples:
  chart OAK CNDEL5       - CNDEL FIVE departure (auto-rotate)
  OAK ILS 28R            - ILS 28R approach (implicit)
  chart OAK CNDEL5 -r    - Force 90 degree rotation
  chart SFO SERFR2       - SERFR TWO arrival
""",
    "charts": """
charts - Browse charts in the Reference Tool browser

Opens the chart in the Reference Tool interface, allowing you to
browse other charts for the same airport. Use 'chart' instead if
you just want to view a single PDF.

\b
Examples:
  charts OAK CNDEL5      - Open CNDEL FIVE, browse other OAK charts
  charts SFO ILS 28L     - Open ILS 28L, browse other SFO charts
""",
    "list": """
list - List all charts for an airport

Shows all available charts for the specified airport, including
chart type codes (DP, STAR, IAP, etc.).

\b
Examples:
  list OAK               - List all OAK charts
  list SFO               - List all SFO charts
""",
    "route": """
route - Look up routes between two airports

Shows TEC/AAR/ADR routes, LOA rules, and real-world routes between
the specified airports. By default shows top 5 real-world routes.

\b
Examples:
  route SFO LAX          - Routes from SFO to LAX (top 5)
  route SFO LAX -a       - Show all real world routes
  route SFO LAX -f       - Include recent flights
  route SFO LAX -a -f    - Show everything
  route OAK SAN -n 10    - Show top 10 real world routes
  route SFO LAX --browser - Open routes page in browser
""",
    "atis": """
atis - Look up current ATIS for an airport

Fetches the current ATIS (Automatic Terminal Information Service)
for the specified airport. Use "atis all" or "atis -a" to show
ATIS for all supported airports.

Supported airports: SFO, OAK, SJC, SMF, RNO

\b
Examples:
  atis SFO               - ATIS for San Francisco
  atis all               - ATIS for all airports
  atis -a                - ATIS for all airports
""",
    "sop": """
sop - Look up Standard Operating Procedures (SOPs)

Opens procedure PDFs, optionally jumping to a specific section or
searching for text within a section. Multi-step lookups let you
find specific content within large documents.

\b
Examples:
  sop OAK                        - Open Oakland ATCT SOP
  sop OAK 2-2                    - Open OAK SOP at section 2-2
  sop "NORCAL TRACON"            - Open NORCAL TRACON SOP
  sop SJC "IFR Departures" SJCE  - Find SJCE in IFR Departures section
  sop --list                     - List all available procedures

Alias: 'proc' is an alias for 'sop'
""",
    "proc": """
proc - Alias for 'sop' command

See 'sop --help' for full documentation.
""",
    "airline": """
airline - Look up airline codes

Searches for airlines by ICAO identifier (e.g., UAL), telephony
callsign (e.g., UNITED), or airline name. Results are cached for
faster subsequent lookups.

\b
Examples:
  airline UAL            - Search by ICAO code
  airline united         - Search by telephony/name
  airline "Delta Air"    - Multi-word search
  airline UAL --browser  - Open codes page in browser
""",
    "airport": """
airport - Look up airport codes

Searches for airports by ICAO code (e.g., KSFO), FAA/local
identifier (e.g., SFO), or airport name. Results are cached.

\b
Examples:
  airport KSFO           - Search by ICAO code
  airport SFO            - Search by FAA identifier
  airport "San Fran"     - Search by name
  airport SFO --browser  - Open codes page in browser
""",
    "aircraft": """
aircraft - Look up aircraft type codes

Searches for aircraft by ICAO type designator (e.g., B738),
manufacturer (e.g., Boeing), or model name. Shows engine type,
weight class, and other operational data. Results are cached.

\b
Examples:
  aircraft B738          - Search by type designator
  aircraft boeing        - Search by manufacturer
  aircraft "737-800"     - Search by model
  aircraft B738 --browser - Open codes page in browser
""",
}


def _print_interactive_help(include_help_line: bool = False) -> None:
    """Print interactive mode command help.

    Args:
        include_help_line: If True, include the 'help' command in the output.
    """
    click.echo("Commands:")
    for line in INTERACTIVE_HELP_COMMANDS:
        click.echo(line)
    if include_help_line:
        click.echo("  help [command]     - Show help (e.g., help sop)")
    click.echo("  quit / exit / q    - Exit the program")


def _print_command_help(command: str) -> bool:
    """Print detailed help for a specific command using Click's help formatter.

    Args:
        command: The command name to show help for.

    Returns:
        True if help was found and printed, False otherwise.
    """
    cmd_lower = command.lower().strip()
    # Get the Click command from the main group
    ctx = click.Context(main)
    cmd = main.get_command(ctx, cmd_lower)
    if cmd is not None:
        # Create a context for the command and print its help
        with click.Context(cmd, info_name=cmd_lower, parent=ctx) as cmd_ctx:
            click.echo(cmd.get_help(cmd_ctx))
        return True
    return False


def _get_running_browser() -> str | None:
    """Check if any known browser is running and return its command name."""
    try:
        result = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        processes = result.stdout.lower()
        for process_name, cmd in BROWSERS.items():
            if process_name in processes:
                return cmd
    except Exception:
        pass
    return None


def _open_in_browser(file_path: str, view: str = "FitV", page: int | None = None) -> bool:
    """Open a local file in a running browser, or fall back to default handler.

    Args:
        file_path: Path to the local file to open.
        view: PDF view parameter (e.g., "FitV" for fit to height).
        page: Optional page number to open at.

    Returns:
        True if opened successfully.
    """
    # Convert to proper file:// URI with fragment
    file_uri = Path(file_path).as_uri()
    fragments = []
    if page:
        fragments.append(f"page={page}")
    if view:
        fragments.append(f"view={view}")
    if fragments:
        file_uri = f"{file_uri}#{'&'.join(fragments)}"

    # Check for a running browser
    browser_cmd = _get_running_browser()
    if browser_cmd:
        try:
            # Use 'start' command on Windows to launch browser by name
            subprocess.Popen(f'start "" "{browser_cmd}" "{file_uri}"', shell=True)
            return True
        except Exception:
            pass  # Fall back to default

    # Fall back to default handler
    webbrowser.open(file_uri)
    return True


@dataclass
class InteractiveContext:
    """Context object for interactive mode state.

    Holds browser sessions and settings needed by interactive command handlers.
    """

    headless_session: BrowserSession
    codes_page: CodesPage
    use_playwright: bool
    visible_session: BrowserSession | None = field(default=None)

    def get_or_create_visible_session(self) -> BrowserSession:
        """Get or create the visible browser session.

        Creates a child session from headless_session if needed.
        """
        if self.visible_session is None:
            self.visible_session = self.headless_session.create_child_session(headless=False)
        elif not self.visible_session.is_connected:
            click.echo("Reopening browser...")
            self.visible_session = self.headless_session.create_child_session(headless=False)
        return self.visible_session


@dataclass
class ParsedArgs:
    """Parsed arguments from interactive command input.

    Separates positional arguments from flags and options.
    """

    positional: list[str]
    flags: dict[str, bool]
    options: dict[str, str]
    show_help: bool = False


def _parse_interactive_args(
    args: str,
    flag_defs: dict[str, tuple[str, ...]] | None = None,
    option_defs: dict[str, tuple[str, ...]] | None = None,
) -> ParsedArgs:
    """Parse flags and options from interactive input string.

    Args:
        args: The input string to parse (e.g., "SFO LAX -a -n 10")
        flag_defs: Map of flag_name -> tuple of aliases (e.g., {"all": ("-a", "--all")})
        option_defs: Map of option_name -> tuple of aliases that expect a value

    Returns:
        ParsedArgs with separated positional args, flags, and options.
        The show_help field is True if --help or -h was specified.
    """
    flag_defs = flag_defs or {}
    option_defs = option_defs or {}

    # Build reverse lookup: alias -> (type, name)
    alias_map: dict[str, tuple[str, str]] = {}  # alias -> ("flag"|"option", name)
    for name, aliases in flag_defs.items():
        for alias in aliases:
            alias_map[alias] = ("flag", name)
    for name, aliases in option_defs.items():
        for alias in aliases:
            alias_map[alias] = ("option", name)

    positional: list[str] = []
    flags: dict[str, bool] = {}
    options: dict[str, str] = {}
    show_help = False

    try:
        parts = shlex.split(args)
    except ValueError:
        # Handle unclosed quotes gracefully
        parts = args.strip().split()
    i = 0
    while i < len(parts):
        part = parts[i]
        if part in ("--help", "-h"):
            show_help = True
        elif part in alias_map:
            kind, name = alias_map[part]
            if kind == "flag":
                flags[name] = True
            else:  # option
                if i + 1 < len(parts):
                    options[name] = parts[i + 1]
                    i += 1
                # If no value follows, silently ignore (usage error)
        elif not part.startswith("-"):
            positional.append(part)
        # Unknown flags starting with "-" are ignored
        i += 1

    return ParsedArgs(positional=positional, flags=flags, options=options, show_help=show_help)


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


class ImplicitChartGroup(click.Group):
    """Custom group that treats unknown commands as implicit chart queries."""

    def parse_args(self, ctx, args):
        """Parse args, treating unknown commands as chart queries."""
        # Check if we have args and the first arg isn't a known command or option
        if args and not args[0].startswith('-'):
            cmd_name = args[0]
            if self.get_command(ctx, cmd_name) is None:
                # Not a known command - treat all args as chart query
                # Insert 'chart' command before the args
                args = ['chart'] + list(args)
        return super().parse_args(ctx, args)


@click.group(cls=ImplicitChartGroup, invoke_without_command=True)
@click.option("--playwright", is_flag=True, help="Use Playwright browser with tab management instead of system browser")
@click.pass_context
def main(ctx, playwright: bool):
    """ZOA Reference CLI - Quick lookups to ZOA's Reference Tool.

    Run without arguments to enter interactive mode.

    Examples:

        zoa OAK CNDEL5           - Open the CNDEL FIVE PDF directly

        zoa chart OAK CNDEL5     - Same as above (explicit command)

        zoa charts SFO ILS 28L   - Open ILS 28L, browse other SFO charts

        zoa list OAK             - List all charts available for OAK

        zoa route SFO LAX        - Look up routes from SFO to LAX

        zoa --playwright         - Interactive mode with managed browser
    """
    # Store in context for subcommands that might need it
    ctx.ensure_object(dict)
    ctx.obj['playwright'] = playwright

    if ctx.invoked_subcommand is None:
        interactive_mode(use_playwright=playwright)


@main.command(help=COMMAND_HELP["chart"].strip())
@click.argument("query", nargs=-1, required=True)
@click.option("--headless", is_flag=True, help="Run browser in headless mode (outputs PDF URL)")
@click.option("-r", "rotate_flag", is_flag=True, help="Rotate chart 90°")
@click.option("--rotate", type=click.Choice(["90", "180", "270"]), default=None,
              help="Rotate chart by specific degrees")
@click.option("--no-rotate", is_flag=True, help="Disable auto-rotation")
def chart(
    query: tuple[str, ...],
    headless: bool,
    rotate_flag: bool,
    rotate: str | None,
    no_rotate: bool,
):
    if rotate:
        rotation: int | None = int(rotate)
    elif rotate_flag:
        rotation = 90
    elif no_rotate:
        rotation = 0
    else:
        rotation = None  # Auto-detect
    _do_chart_lookup(" ".join(query), headless=headless, rotation=rotation)


@main.command(help=COMMAND_HELP["charts"].strip())
@click.argument("query", nargs=-1, required=True)
def charts(query: tuple[str, ...]):
    _do_charts_browse(" ".join(query))


@main.command("list", help=COMMAND_HELP["list"].strip())
@click.argument("airport")
def list_cmd(airport: str):
    airport = airport.upper()
    if airport not in ZOA_AIRPORTS:
        click.echo(f"Warning: {airport} is not a known ZOA airport")

    click.echo(f"Fetching charts for {airport}...")

    charts = fetch_charts_from_api(airport)

    if charts:
        click.echo(f"\nAvailable charts for {airport}:")
        click.echo("-" * 40)
        for chart in charts:
            type_str = chart.chart_code if chart.chart_code else "?"
            click.echo(f"  [{type_str:<4}] {chart.chart_name}")
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


@main.command(help=COMMAND_HELP["route"].strip())
@click.argument("departure")
@click.argument("arrival")
@click.option("--browser", is_flag=True, help="Open browser instead of CLI display")
@click.option("--all-routes", "-a", is_flag=True, help="Show all real world routes (default: top 5)")
@click.option("--flights", "-f", is_flag=True, help="Show recent flights (hidden by default)")
@click.option("--top", "-n", type=int, default=5, help="Number of real world routes to show (default: 5)")
def route(departure: str, arrival: str, browser: bool, all_routes: bool, flights: bool, top: int):
    _do_route_lookup(
        departure, arrival,
        browser=browser,
        show_all=all_routes,
        show_flights=flights,
        top_n=top,
    )


@main.command(help=COMMAND_HELP["airline"].strip())
@click.argument("query", nargs=-1, required=True)
@click.option("--browser", is_flag=True, help="Open browser instead of CLI display")
@click.option("--no-cache", is_flag=True, help="Bypass cache and fetch fresh data")
def airline(query: tuple[str, ...], browser: bool, no_cache: bool):
    _do_icao_lookup("airline", " ".join(query), browser=browser, no_cache=no_cache)


@main.command(help=COMMAND_HELP["airport"].strip())
@click.argument("query", nargs=-1, required=True)
@click.option("--browser", is_flag=True, help="Open browser instead of CLI display")
@click.option("--no-cache", is_flag=True, help="Bypass cache and fetch fresh data")
def airport(query: tuple[str, ...], browser: bool, no_cache: bool):
    _do_icao_lookup("airport", " ".join(query), browser=browser, no_cache=no_cache)


@main.command(help=COMMAND_HELP["aircraft"].strip())
@click.argument("query", nargs=-1, required=True)
@click.option("--browser", is_flag=True, help="Open browser instead of CLI display")
@click.option("--no-cache", is_flag=True, help="Bypass cache and fetch fresh data")
def aircraft(query: tuple[str, ...], browser: bool, no_cache: bool):
    _do_icao_lookup("aircraft", " ".join(query), browser=browser, no_cache=no_cache)


# --- Procedure/SOP Commands ---

def _prompt_procedure_choice(matches: list[ProcedureMatch]) -> ProcedureInfo | None:
    """Prompt user to select from numbered matches."""
    idx = prompt_single_choice(len(matches))
    if idx is not None:
        return matches[idx - 1].procedure
    return None


def _prompt_chart_choice(matches: list[ChartMatch]) -> ChartInfo | None:
    """Prompt user to select from numbered chart matches."""
    idx = prompt_single_choice(len(matches))
    if idx is not None:
        return matches[idx - 1].chart
    return None


def _open_procedure_pdf(procedure: ProcedureInfo, page_num: int = 1) -> None:
    """Open a procedure PDF at a specific page."""
    click.echo(f"Opening: {procedure.name}")
    if page_num > 1:
        click.echo(f"  Page: {page_num}")

    # Download PDF to temp file with descriptive name
    pdf_data = download_procedure_pdf(procedure.full_url)
    if pdf_data:
        filename = _sanitize_procedure_filename(procedure.name)
        temp_path = os.path.join(tempfile.gettempdir(), filename)
        with open(temp_path, "wb") as f:
            f.write(pdf_data)

        # Open with page fragment
        if page_num > 1:
            _open_in_browser(temp_path, page=page_num, view="FitV")
        else:
            _open_in_browser(temp_path, view="FitV")
    else:
        # Fall back to opening URL directly
        click.echo("Failed to download, opening URL directly...", err=True)
        pdf_url = procedure.full_url
        if page_num > 1:
            url_with_page = f"{pdf_url}#page={page_num}&view=FitV"
        else:
            url_with_page = f"{pdf_url}#view=FitV"
        webbrowser.open(url_with_page)


def _list_procedures(
    no_cache: bool = False,
    headless_session: "BrowserSession | None" = None,
) -> None:
    """List all available procedures grouped by category.

    Args:
        no_cache: If True, bypass cache
        headless_session: Shared headless session (interactive mode)
    """
    click.echo("Fetching procedures list...")

    own_session = headless_session is None
    if own_session:
        session = BrowserSession(headless=True)
        session.start()
    else:
        session = headless_session

    try:
        page = session.new_page()
        by_category = list_all_procedures(page, use_cache=not no_cache)
        if headless_session is not None:
            page.close()
    finally:
        if own_session:
            session.stop()

    if not by_category:
        click.echo("Failed to fetch procedures list.", err=True)
        return

    # Category display names
    category_names = {
        "policy": "Central Policy Statements",
        "enroute": "Enroute (Oakland Center)",
        "tracon": "TRACON",
        "atct": "Airport Traffic Control Tower",
        "loa_internal": "Internal Letters of Agreement",
        "loa_external": "External Letters of Agreement",
        "loa_military": "Military Letters of Agreement",
        "zak": "ZAK Documents",
        "quick_ref": "Quick Reference",
        "other": "Other",
    }

    # Display order
    display_order = [
        "policy", "enroute", "tracon", "atct",
        "loa_internal", "loa_external", "loa_military",
        "zak", "quick_ref", "other"
    ]

    for cat in display_order:
        if cat in by_category:
            procs = by_category[cat]
            display_name = category_names.get(cat, cat.title())
            click.echo(f"\n{display_name}:")
            click.echo("-" * 40)
            for proc in procs:
                click.echo(f"  {proc.name}")


def _handle_sop_command(
    query: tuple[str, ...],
    list_procs: bool = False,
    no_cache: bool = False,
    headless_session: "BrowserSession | None" = None,
) -> None:
    """Handle sop/proc command logic.

    Args:
        query: Query tuple (procedure name, optional section, optional search text)
        list_procs: If True, list all available procedures
        no_cache: If True, bypass cache
        headless_session: Shared headless session (interactive mode)
    """
    # List mode
    if list_procs:
        _list_procedures(no_cache, headless_session=headless_session)
        return

    # Parse query - pass tuple directly to preserve quoted strings
    if not query:
        click.echo("Usage: sop <query>  (e.g., sop OAK 2-2)")
        click.echo("       sop SJC \"IFR Departures\" SJCE  (multi-step lookup)")
        click.echo("       sop --list   (list all procedures)")
        return

    try:
        parsed = ProcedureQuery.parse(query)
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        return

    click.echo(f"Looking up: {parsed.procedure_term}")
    if parsed.section_term:
        click.echo(f"  Section: {parsed.section_term}")
    if parsed.search_term:
        click.echo(f"  Search for: {parsed.search_term}")

    # Fetch procedures (cached)
    own_session = headless_session is None
    if own_session:
        session = BrowserSession(headless=True)
        session.start()
    else:
        session = headless_session

    try:
        page = session.new_page()
        procedures = fetch_procedures_list(page, use_cache=not no_cache)
        if headless_session is not None:
            page.close()
    finally:
        if own_session:
            session.stop()

    if not procedures:
        click.echo("Failed to fetch procedures list.", err=True)
        return

    # Find matching procedure
    procedure, matches = find_procedure_by_name(procedures, parsed)

    if not procedure:
        if matches:
            # Ambiguous - show numbered disambiguation prompt
            display_procedure_matches(matches)
            choice = _prompt_procedure_choice(matches)
            if choice:
                procedure = choice
            else:
                return
        else:
            click.echo(f"No procedure found matching '{parsed.procedure_term}'")
            return

    # Determine page number
    page_num = 1
    if parsed.section_term and parsed.search_term:
        # Multi-step lookup: find text within section
        click.echo(f"Searching for '{parsed.search_term}' in section '{parsed.section_term}'...")
        found_page = find_text_in_section(
            procedure, parsed.section_term, parsed.search_term,
            use_cache=not no_cache
        )
        if found_page:
            page_num = found_page
            click.echo(f"Found '{parsed.search_term}' at page {page_num}")
        else:
            # Fall back to just the section
            click.echo(f"'{parsed.search_term}' not found in section, trying section only...")
            found_page = find_heading_page(procedure, parsed.section_term, use_cache=not no_cache)
            if found_page:
                page_num = found_page
                click.echo(f"Found section at page {page_num}")
            else:
                click.echo(f"Section '{parsed.section_term}' not found, opening first page")
    elif parsed.section_term:
        # Single section lookup
        click.echo(f"Searching for section '{parsed.section_term}'...")
        found_page = find_heading_page(procedure, parsed.section_term, use_cache=not no_cache)
        if found_page:
            page_num = found_page
            click.echo(f"Found section at page {page_num}")
        else:
            click.echo(f"Section '{parsed.section_term}' not found, opening first page")

    # Open PDF at page
    _open_procedure_pdf(procedure, page_num)


@main.command(help=COMMAND_HELP["sop"].strip())
@click.argument("query", nargs=-1, required=False)
@click.option("--list", "list_procs", is_flag=True, help="List available procedures")
@click.option("--no-cache", is_flag=True, help="Bypass cache and fetch fresh data")
def sop(query: tuple[str, ...], list_procs: bool, no_cache: bool):
    _handle_sop_command(query or (), list_procs, no_cache)


@main.command("proc", help=COMMAND_HELP["proc"].strip())
@click.argument("query", nargs=-1, required=False)
@click.option("--list", "list_procs", is_flag=True, help="List available procedures")
@click.option("--no-cache", is_flag=True, help="Bypass cache and fetch fresh data")
def proc(query: tuple[str, ...], list_procs: bool, no_cache: bool):
    _handle_sop_command(query or (), list_procs, no_cache)


@main.command(help=COMMAND_HELP["atis"].strip())
@click.argument("airport", required=False)
@click.option("--all", "-a", "show_all", is_flag=True, help="Show ATIS for all airports")
def atis(airport: str | None, show_all: bool):
    _do_atis_lookup(airport, show_all=show_all)


# =============================================================================
# Unified command implementations (shared between CLI and interactive modes)
# =============================================================================


def _do_icao_lookup(
    search_type: str,
    query: str,
    browser: bool = False,
    no_cache: bool = False,
    codes_page: "CodesPage | None" = None,
    headless_session: "BrowserSession | None" = None,
) -> None:
    """Shared ICAO lookup for airline/airport/aircraft.

    Args:
        search_type: One of "airline", "airport", or "aircraft"
        query: Search query string
        browser: If True, open codes page in visible browser
        no_cache: If True, bypass cache
        codes_page: Persistent CodesPage for fast lookups (interactive mode)
        headless_session: Shared headless session (interactive mode)
    """
    # Map search type to functions and display
    search_funcs = {
        "airline": (search_airline, display_airlines, "airlines"),
        "airport": (search_airport_code, display_airport_codes, "airports"),
        "aircraft": (search_aircraft, display_aircraft, "aircraft"),
    }
    search_func, display_func, search_label = search_funcs[search_type]

    # Map codes_page methods
    codes_page_methods = {
        "airline": "search_airline",
        "airport": "search_airport",
        "aircraft": "search_aircraft",
    }

    # Try cache first (if not no_cache and not browser)
    if not no_cache and not browser:
        if codes_page is not None:
            # Use CodesPage method for cache lookup
            method = getattr(codes_page, codes_page_methods[search_type])
            result = method(query, use_cache=True)
        else:
            # Direct cache lookup
            result = search_func(None, query, use_cache=True)
        if result:
            display_func(result)
            return

    click.echo(f"Searching {search_label}: {query}...")

    if browser:
        # Browser mode: open codes page in visible browser
        own_session = headless_session is None
        if own_session:
            session = BrowserSession(headless=False)
            session.start()
        else:
            # Create visible child session from headless
            assert headless_session is not None
            session = headless_session.create_child_session(headless=False)

        try:
            page = session.new_page()
            success = open_codes_browser(page)
            if success:
                _wait_for_input_or_close(session, "Codes page open. Press Enter to close browser...", page)
            else:
                _wait_for_input_or_close(session, "Failed to load codes page. Press Enter to close browser...", page)
        finally:
            if own_session:
                session.stop()
    else:
        # CLI mode: search and display
        if codes_page is not None:
            # Use persistent CodesPage
            if codes_page.ensure_ready():
                method = getattr(codes_page, codes_page_methods[search_type])
                result = method(query, use_cache=not no_cache)
                if result:
                    display_func(result)
                else:
                    click.echo(f"Failed to retrieve {search_label} codes.", err=True)
            else:
                click.echo(f"Failed to retrieve {search_label} codes.", err=True)
        elif headless_session is not None:
            # Use provided headless session
            page = headless_session.new_page()
            result = search_func(page, query, use_cache=not no_cache)
            page.close()
            if result:
                display_func(result)
            else:
                click.echo(f"Failed to retrieve {search_label} codes.", err=True)
        else:
            # Create own session
            with BrowserSession(headless=True) as session:
                page = session.new_page()
                result = search_func(page, query, use_cache=not no_cache)
                if result:
                    display_func(result)
                else:
                    click.echo(f"Failed to retrieve {search_label} codes.", err=True)


def _do_route_lookup(
    departure: str,
    arrival: str,
    browser: bool = False,
    show_all: bool = False,
    show_flights: bool = False,
    top_n: int = 5,
    headless_session: "BrowserSession | None" = None,
) -> None:
    """Shared route lookup.

    Args:
        departure: Departure airport code
        arrival: Arrival airport code
        browser: If True, open routes page in visible browser
        show_all: If True, show all real world routes (otherwise top N)
        show_flights: If True, include recent flights
        top_n: Number of real world routes to show (if not show_all)
        headless_session: Shared headless session (interactive mode)
    """
    departure = departure.upper()
    arrival = arrival.upper()

    click.echo(f"Searching routes: {departure} -> {arrival}...")

    if browser:
        # Browser mode: open routes page in visible browser
        own_session = headless_session is None
        if own_session:
            session = BrowserSession(headless=False)
            session.start()
        else:
            # Create visible child session from headless
            assert headless_session is not None
            session = headless_session.create_child_session(headless=False)

        try:
            page = session.new_page()
            success = open_routes_browser(page, departure, arrival)
            if success:
                _wait_for_input_or_close(session, "Routes page open. Press Enter to close browser...", page)
            else:
                _wait_for_input_or_close(session, "Failed to load routes page. Press Enter to close browser...", page)
        finally:
            if own_session:
                session.stop()
    else:
        # CLI mode: scrape and display
        own_session = headless_session is None
        if own_session:
            with BrowserSession(headless=True) as session:
                page = session.new_page()
                result = search_routes(page, departure, arrival)
                if result:
                    display_routes(result, max_real_world=None if show_all else top_n, show_flights=show_flights)
                else:
                    click.echo("Failed to retrieve routes.", err=True)
        else:
            assert headless_session is not None
            page = headless_session.new_page()
            result = search_routes(page, departure, arrival)
            page.close()
            if result:
                display_routes(result, max_real_world=None if show_all else top_n, show_flights=show_flights)
            else:
                click.echo("Failed to retrieve routes.", err=True)


def _do_atis_lookup(
    airport: str | None,
    show_all: bool = False,
    headless_session: "BrowserSession | None" = None,
) -> None:
    """Shared ATIS lookup.

    Args:
        airport: Airport code (or None if show_all is True)
        show_all: If True, fetch ATIS for all airports
        headless_session: Shared headless session (interactive mode)
    """
    if not airport and not show_all:
        click.echo(f"Available airports: {', '.join(ATIS_AIRPORTS)}")
        click.echo("Error: Please specify an airport or use --all/-a", err=True)
        return

    click.echo("Fetching ATIS...")

    own_session = headless_session is None
    if own_session:
        session = BrowserSession(headless=True)
        session.start()
    else:
        session = headless_session

    try:
        page = session.new_page()

        if show_all:
            result = fetch_all_atis(page)
            if result and result.atis_list:
                display_atis(result.atis_list)
            else:
                click.echo("Failed to retrieve ATIS.", err=True)
        elif airport:
            airport = airport.upper()
            if airport not in ATIS_AIRPORTS:
                click.echo(f"Warning: {airport} is not a known ATIS airport")
                click.echo(f"Available airports: {', '.join(ATIS_AIRPORTS)}")
                return

            atis_info = fetch_atis(page, airport)
            if atis_info:
                display_atis([atis_info])
            else:
                click.echo(f"Failed to retrieve ATIS for {airport}.", err=True)

        if headless_session is not None:
            page.close()
    finally:
        if own_session:
            session.stop()


def _do_chart_lookup(
    query_str: str,
    headless: bool = False,
    rotation: int | None = None,
    visible_session: "BrowserSession | None" = None,
) -> str | None:
    """Shared chart lookup using API.

    Args:
        query_str: The chart query string (e.g., "OAK CNDEL5")
        headless: If True, just output the PDF URL; otherwise open in browser
        rotation: Rotation angle in degrees (0, 90, 180, 270).
                  If None, auto-detects from text orientation.
        visible_session: Playwright session for tab management (interactive mode)

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

    pdf_urls, matched_chart, matches = lookup_chart_with_pages(parsed)

    if pdf_urls and matched_chart:
        chart_name = matched_chart.chart_name

        if headless:
            # In headless mode, just output URL(s)
            for url in pdf_urls:
                click.echo(url)
            return pdf_urls[0]

        # Open the chart in browser
        return _open_chart_pdf(
            pdf_urls=pdf_urls,
            airport=parsed.airport,
            chart_name=chart_name,
            rotation=rotation,
            session=visible_session,
        )

    # No unambiguous match found
    if matches:
        # Ambiguous match - show numbered disambiguation prompt
        display_chart_matches(matches)
        choice = _prompt_chart_choice(matches)
        if choice:
            # Get all pages for the selected chart
            charts = fetch_charts_from_api(parsed.airport)
            all_pages = find_all_chart_pages(charts, choice)
            pdf_urls = [page.pdf_path for page in all_pages]

            if headless:
                for url in pdf_urls:
                    click.echo(url)
                return pdf_urls[0]

            return _open_chart_pdf(
                pdf_urls=pdf_urls,
                airport=parsed.airport,
                chart_name=choice.chart_name,
                rotation=rotation,
                session=visible_session,
            )
    else:
        click.echo(f"No charts found for {parsed.airport}", err=True)

    return None


def _do_charts_browse(
    query_str: str,
    visible_session: "BrowserSession | None" = None,
) -> str | None:
    """Browse charts on Reference Tool page.

    Args:
        query_str: The chart query string (e.g., "OAK CNDEL5")
        visible_session: Playwright session for browsing (interactive mode)

    Returns the PDF URL if found, None otherwise.
    """
    try:
        parsed = ChartQuery.parse(query_str)
        click.echo(f"Opening charts browser: {parsed.airport} - {parsed.chart_name}")
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        return None

    own_session = visible_session is None
    if own_session:
        window_size = _calculate_viewport_size()
        session = BrowserSession(headless=False, window_size=window_size)
        session.start()
    else:
        session = visible_session

    try:
        page = session.new_page()
        pdf_url = lookup_chart(page, parsed)

        if pdf_url:
            # Modify the embedded PDF to fit to height
            page.evaluate("""() => {
                const obj = document.querySelector('object[data*=".PDF"]');
                if (obj && obj.data && !obj.data.includes('#')) {
                    obj.data = obj.data + '#view=FitV';
                }
            }""")
            click.echo("Chart found! Browse other charts in the browser window.")
        else:
            click.echo("Could not find chart. Browse manually in the browser window.")

        if own_session:
            _wait_for_input_or_close(session, page=page)

        return pdf_url
    finally:
        if own_session:
            session.stop()


def _sanitize_chart_filename(airport: str, chart_name: str) -> str:
    """Convert chart name to a clean, descriptive filename.

    Rules:
    - Keep CAT designations from parentheses (e.g., SA CAT I, CAT II - III)
    - Remove all other parenthesized content (RNAV, RNP, GPS, etc.)
    - Remove the word RWY
    - Strip standalone hyphens
    - Replace spaces with underscores
    """
    name = chart_name
    # Extract CAT designations from parentheses before removal
    cat_matches = re.findall(r'\(([^)]*CAT[^)]*)\)', name)
    cat_suffix = ''
    if cat_matches:
        cat_text = cat_matches[0]
        cat_text = re.sub(r'\s+-\s+', '_', cat_text)  # Strip standalone hyphens
        cat_text = re.sub(r'\s+', '_', cat_text)
        cat_suffix = '_' + cat_text
    # Remove anything in parentheses
    name = re.sub(r'\s*\([^)]*\)', '', name)
    # Remove 'RWY' word
    name = re.sub(r'\bRWY\b', '', name)
    # Remove special chars (keep alphanumeric, spaces, hyphens)
    name = re.sub(r'[^\w\s-]', '', name)
    # Strip standalone hyphens (surrounded by spaces)
    name = re.sub(r'\s+-\s+', ' ', name)
    # Collapse multiple spaces and convert to underscores
    name = re.sub(r'\s+', '_', name.strip())
    # Remove any trailing/leading underscores
    name = name.strip('_')
    return f'ZOA_{airport}_{name}{cat_suffix}.pdf'


def _sanitize_procedure_filename(procedure_name: str) -> str:
    """Convert procedure name to a clean, descriptive filename.

    Example: "Oakland ATCT SOP" -> "ZOA_SOP_Oakland_ATCT.pdf"
    """
    name = procedure_name
    # Remove special chars (keep alphanumeric, spaces, hyphens)
    name = re.sub(r'[^\w\s-]', '', name)
    # Replace spaces with underscores
    name = re.sub(r'\s+', '_', name.strip())
    return f'ZOA_SOP_{name}.pdf'


def _open_chart_pdf(
    pdf_urls: list[str],
    airport: str,
    chart_name: str,
    rotation: int | None = None,
    session: "BrowserSession | None" = None,
) -> str | None:
    """Open chart PDF(s) in browser.

    Handles single and multi-page charts, optional rotation, and both
    system browser and Playwright browser modes.

    Args:
        pdf_urls: List of PDF URLs (1 for single-page, multiple for continuation pages)
        airport: Airport code for temp file naming
        chart_name: Chart name for display
        rotation: Rotation angle in degrees (0, 90, 180, 270).
                  If None, auto-detects from text orientation.
        session: If provided, use Playwright browser session; otherwise use system browser

    Returns:
        Path to opened file/URL, or None on failure.
    """
    num_pages = len(pdf_urls)

    if num_pages == 1:
        pdf_url = pdf_urls[0]

        if session is not None:
            # Playwright mode: check if already open (tab reuse)
            page, was_existing = session.get_or_create_page(pdf_url)
            if was_existing:
                click.echo(f"Chart already open: {chart_name}")
            else:
                page.goto(f"{pdf_url}#view=FitV")
                click.echo(f"Chart found: {chart_name}")
            return pdf_url

        # System browser mode: download, optionally rotate, and open
        filename = _sanitize_chart_filename(airport, chart_name)
        temp_path = os.path.join(tempfile.gettempdir(), filename)

        if download_and_rotate_pdf(pdf_url, temp_path, rotation):
            view_mode = detect_pdf_view_mode(temp_path)
            click.echo(f"Opening chart: {chart_name}")
            _open_in_browser(temp_path, view=view_mode)
            return temp_path
        else:
            click.echo("Failed to download chart", err=True)
            # Fall back to opening URL directly (no rotation)
            webbrowser.open(f"{pdf_url}#view=FitV")
            return pdf_url
    else:
        # Multi-page chart - merge pages
        click.echo(f"Chart has {num_pages} pages, merging...")

        filename = _sanitize_chart_filename(airport, chart_name)
        temp_path = os.path.join(tempfile.gettempdir(), filename)

        if download_and_merge_pdfs(pdf_urls, temp_path, rotation):
            view_mode = detect_pdf_view_mode(temp_path)
            if session is not None:
                # Playwright mode
                page = session.new_page()
                page.goto(f"{Path(temp_path).as_uri()}#view={view_mode}")
            else:
                # System browser mode
                _open_in_browser(temp_path, view=view_mode)
            click.echo(f"Chart found: {chart_name} ({num_pages} pages)")
            return temp_path
        else:
            click.echo("Failed to merge PDF pages, opening first page only")
            pdf_url = pdf_urls[0]
            if session is not None:
                page, was_existing = session.get_or_create_page(pdf_url)
                if not was_existing:
                    page.goto(f"{pdf_url}#view=FitV")
            else:
                webbrowser.open(f"{pdf_url}#view=FitV")
            return pdf_url


# =============================================================================
# Interactive mode command handlers
# =============================================================================


def _handle_list_interactive(args: str) -> None:
    """Handle 'list <airport>' command in interactive mode."""
    parsed = _parse_interactive_args(args)
    if parsed.show_help or not parsed.positional:
        _print_command_help("list")
        return
    airport = parsed.positional[0].upper()

    click.echo(f"Fetching charts for {airport}...")
    charts = fetch_charts_from_api(airport)

    if charts:
        click.echo(f"\nAvailable charts for {airport}:")
        click.echo("-" * 40)
        for chart in charts:
            type_str = chart.chart_code if chart.chart_code else "?"
            click.echo(f"  [{type_str:<4}] {chart.chart_name}")
        click.echo(f"\nTotal: {len(charts)} charts")
    else:
        click.echo(f"No charts found for {airport}")


def _handle_charts_interactive(args: str, ctx: InteractiveContext) -> None:
    """Handle 'charts <query>' command in interactive mode."""
    parsed = _parse_interactive_args(args)
    if parsed.show_help or not parsed.positional:
        _print_command_help("charts")
        return
    query_str = " ".join(parsed.positional)

    # Get or create visible browser session for charts browsing
    visible_session = ctx.get_or_create_visible_session()
    _do_charts_browse(query_str, visible_session=visible_session)


def _handle_route_interactive(args: str, ctx: InteractiveContext) -> None:
    """Handle 'route <departure> <arrival> [options]' command in interactive mode."""
    parsed = _parse_interactive_args(
        args,
        flag_defs={
            "all": ("-a", "--all"),
            "flights": ("-f", "--flights"),
            "browser": ("--browser",),
        },
        option_defs={"top": ("-n", "--top")},
    )

    if parsed.show_help or len(parsed.positional) < 2:
        _print_command_help("route")
        return

    try:
        top_n = int(parsed.options.get("top", 5))
    except ValueError:
        top_n = 5

    _do_route_lookup(
        parsed.positional[0],
        parsed.positional[1],
        browser=parsed.flags.get("browser", False),
        show_all=parsed.flags.get("all", False),
        show_flights=parsed.flags.get("flights", False),
        top_n=top_n,
        headless_session=ctx.headless_session,
    )


def _handle_atis_interactive(args: str, ctx: InteractiveContext) -> None:
    """Handle 'atis [airport|all|-a]' command in interactive mode."""
    parsed = _parse_interactive_args(
        args,
        flag_defs={"all": ("-a", "--all")},
    )

    if parsed.show_help:
        _print_command_help("atis")
        return

    # "atis all" or "atis -a" means show all
    show_all = parsed.flags.get("all", False)
    if parsed.positional and parsed.positional[0].upper() == "ALL":
        show_all = True
        parsed.positional.pop(0)

    airport = parsed.positional[0] if parsed.positional else None

    _do_atis_lookup(
        airport,
        show_all=show_all,
        headless_session=ctx.headless_session,
    )


def _handle_airline_interactive(args: str, ctx: InteractiveContext) -> None:
    """Handle 'airline <query> [--browser] [--no-cache]' command in interactive mode."""
    parsed = _parse_interactive_args(
        args,
        flag_defs={"browser": ("--browser",), "no_cache": ("--no-cache",)},
    )
    if parsed.show_help or not parsed.positional:
        _print_command_help("airline")
        return

    _do_icao_lookup(
        "airline",
        " ".join(parsed.positional),
        browser=parsed.flags.get("browser", False),
        no_cache=parsed.flags.get("no_cache", False),
        codes_page=ctx.codes_page,
        headless_session=ctx.headless_session,
    )


def _handle_airport_interactive(args: str, ctx: InteractiveContext) -> None:
    """Handle 'airport <query> [--browser] [--no-cache]' command in interactive mode."""
    parsed = _parse_interactive_args(
        args,
        flag_defs={"browser": ("--browser",), "no_cache": ("--no-cache",)},
    )
    if parsed.show_help or not parsed.positional:
        _print_command_help("airport")
        return

    _do_icao_lookup(
        "airport",
        " ".join(parsed.positional),
        browser=parsed.flags.get("browser", False),
        no_cache=parsed.flags.get("no_cache", False),
        codes_page=ctx.codes_page,
        headless_session=ctx.headless_session,
    )


def _handle_aircraft_interactive(args: str, ctx: InteractiveContext) -> None:
    """Handle 'aircraft <query> [--browser] [--no-cache]' command in interactive mode."""
    parsed = _parse_interactive_args(
        args,
        flag_defs={"browser": ("--browser",), "no_cache": ("--no-cache",)},
    )
    if parsed.show_help or not parsed.positional:
        _print_command_help("aircraft")
        return

    _do_icao_lookup(
        "aircraft",
        " ".join(parsed.positional),
        browser=parsed.flags.get("browser", False),
        no_cache=parsed.flags.get("no_cache", False),
        codes_page=ctx.codes_page,
        headless_session=ctx.headless_session,
    )


def _handle_chart_interactive(query: str, ctx: InteractiveContext) -> None:
    """Handle implicit chart lookup in interactive mode.

    Supports flags: -r (rotate 90°), --rotate 90/180/270, --no-rotate
    """
    parsed = _parse_interactive_args(
        query,
        flag_defs={"rotate_flag": ("-r",), "no_rotate": ("--no-rotate",)},
        option_defs={"rotate": ("--rotate",)},
    )

    if parsed.show_help or not parsed.positional:
        _print_command_help("chart")
        return

    # Determine rotation
    if parsed.options.get("rotate"):
        rotation: int | None = int(parsed.options["rotate"])
    elif parsed.flags.get("rotate_flag"):
        rotation = 90
    elif parsed.flags.get("no_rotate"):
        rotation = 0
    else:
        rotation = None  # Auto-detect

    # Get session if in playwright mode
    visible_session = ctx.get_or_create_visible_session() if ctx.use_playwright else None

    _do_chart_lookup(
        " ".join(parsed.positional),
        rotation=rotation,
        visible_session=visible_session,
    )


def _handle_sop_interactive(args: str, ctx: InteractiveContext) -> None:
    """Handle 'sop <query> [--list] [--no-cache]' command in interactive mode."""
    parsed = _parse_interactive_args(
        args,
        flag_defs={"list": ("--list",), "no_cache": ("--no-cache",)},
    )

    if parsed.show_help:
        _print_command_help("sop")
        return

    # Convert positional args to tuple for _handle_sop_command
    # This preserves the ability to handle quoted strings from the original input
    query_tuple = tuple(parsed.positional)

    _handle_sop_command(
        query_tuple,
        list_procs=parsed.flags.get("list", False),
        no_cache=parsed.flags.get("no_cache", False),
        headless_session=ctx.headless_session,
    )


# Command registry: maps command prefix to (handler, prefix_length, needs_context)
# needs_context indicates whether the handler requires InteractiveContext
INTERACTIVE_COMMANDS: dict[str, tuple] = {
    "list ": (_handle_list_interactive, 5, False),
    "charts ": (_handle_charts_interactive, 7, True),
    "route ": (_handle_route_interactive, 6, True),
    "atis": (_handle_atis_interactive, 4, True),
    "sop ": (_handle_sop_interactive, 4, True),
    "proc ": (_handle_sop_interactive, 5, True),
    "airline ": (_handle_airline_interactive, 8, True),
    "airport ": (_handle_airport_interactive, 8, True),
    "aircraft ": (_handle_aircraft_interactive, 9, True),
}


def interactive_mode(use_playwright: bool = False):
    """Run in interactive mode for continuous lookups.

    Args:
        use_playwright: If True, use Playwright browser with tab management.
                       If False (default), use system browser via webbrowser.open().
    """
    click.echo("ZOA Reference CLI - Interactive Mode")
    if use_playwright:
        click.echo("(Using Playwright browser with tab management)")
    click.echo("=" * 50)
    _print_interactive_help(include_help_line=True)
    click.echo("=" * 50)
    click.echo()

    # Initialize browser sessions and context
    headless_session = BrowserSession(headless=True)
    headless_session.start()
    codes_page = CodesPage(headless_session)
    codes_page.ensure_ready()  # Pre-navigate so first lookup is fast

    # Create context with optional visible session for playwright mode
    ctx = InteractiveContext(
        headless_session=headless_session,
        codes_page=codes_page,
        use_playwright=use_playwright,
        visible_session=(
            headless_session.create_child_session(headless=False)
            if use_playwright
            else None
        ),
    )

    # Create prompt session with history
    prompt_session = create_prompt_session()

    ctrl_c_exit = False
    try:
        while True:
            try:
                query = prompt_with_history(prompt_session)
            except KeyboardInterrupt:
                query = None
            if query is None:
                click.echo("\nGoodbye!")
                ctrl_c_exit = True
                break

            query = query.strip()
            if not query:
                continue

            lower_query = query.lower()

            if lower_query in ("quit", "exit", "q"):
                click.echo("Goodbye!")
                break

            if lower_query == "help":
                _print_interactive_help()
                click.echo()
                continue

            if lower_query.startswith("help "):
                cmd_name = query[5:].strip()
                if cmd_name:
                    if not _print_command_help(cmd_name):
                        click.echo(f"Unknown command: {cmd_name}")
                        click.echo("Available commands: chart, charts, list, route, atis, sop, proc, airline, airport, aircraft")
                else:
                    _print_interactive_help()
                click.echo()
                continue

            # Check command registry
            handled = False
            for prefix, (handler, prefix_len, needs_ctx) in INTERACTIVE_COMMANDS.items():
                if lower_query.startswith(prefix):
                    args = query[prefix_len:]
                    if needs_ctx:
                        handler(args, ctx)
                    else:
                        handler(args)
                    click.echo()
                    handled = True
                    break

            if handled:
                continue

            # Handle explicit "chart" command prefix (alias for implicit chart lookup)
            if lower_query.startswith("chart "):
                query = query[6:].strip()
                if not query:
                    click.echo("Usage: chart <airport> <chart>  (e.g., chart OAK CNDEL5)")
                    click.echo()
                    continue
                # Fall through to chart lookup below

            # Treat as chart lookup (default command)
            _handle_chart_interactive(query, ctx)
            click.echo()

    finally:
        ctx.codes_page.close()
        # Stop child session first (visible browser), then parent (headless)
        # Parent owns the Playwright instance, so it must be stopped last
        if ctx.visible_session is not None:
            ctx.visible_session.stop()
        ctx.headless_session.stop()

        # Suppress asyncio "Task exception was never retrieved" on Ctrl+C exit
        if ctrl_c_exit:
            import sys
            import os
            sys.stderr = open(os.devnull, "w")


if __name__ == "__main__":
    main()
