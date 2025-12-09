"""CLI utility functions, constants, and data classes."""

import shlex
import subprocess
import threading
import time
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path

import click

from .browser import BrowserSession
from .icao import CodesPage


# Browser process names mapped to their command names
BROWSERS = {
    "chrome.exe": "chrome",
    "msedge.exe": "msedge",
    "firefox.exe": "firefox",
    "brave.exe": "brave",
    "opera.exe": "opera",
}

# Interactive mode command help lines (ordered like website nav bar)
INTERACTIVE_HELP_COMMANDS = [
    "ATIS:",
    "  atis <airport>            - Look up ATIS (e.g., atis SFO)",
    "Routes:",
    "  route <dep> <arr>         - Look up routes (e.g., route SFO LAX)",
    "Charts:",
    "  <airport> <chart>         - Look up a chart (e.g., OAK CNDEL5)",
    "  chart <query>             - Same as above (explicit)",
    "  charts <query>            - Browse charts in browser",
    "  list <airport>            - List charts for an airport",
    "ICAO Codes:",
    "  airline <query>           - Look up airline codes (e.g., airline UAL)",
    "  airport <query>           - Look up airport codes (e.g., airport KSFO)",
    "  aircraft <query>          - Look up aircraft types (e.g., aircraft B738)",
    "Positions:",
    "  position|pos <query>      - Look up ATC positions (e.g., pos NCT)",
    "Procedures:",
    "  sop|proc <query>          - Look up SOP/procedure (e.g., sop OAK)",
    "Scratchpads:",
    "  scratchpad|scratch <fac>  - Look up scratchpads (e.g., scratch OAK)",
    "External Tools:",
    "  vis                       - Open ZOA airspace visualizer",
    "  tdls [airport]            - Open TDLS (Pre-Departure Clearances)",
    "  strips                    - Open flight strips",
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
list - List charts for an airport

Shows available charts for the specified airport. Optionally filter
by chart type. Type aliases: SID=DP, APP=IAP, TAXI=APD.

\b
Examples:
  list OAK               - List all OAK charts
  list SFO DP            - List SFO departure procedures
  list SFO SID           - Same as above (SID is alias for DP)
  list OAK STAR          - List OAK arrival procedures
  list SJC IAP           - List SJC instrument approaches
  list SJC APP           - Same as above (APP is alias for IAP)
  list RNO APD           - List RNO airport diagrams
  list RNO TAXI          - Same as above (TAXI is alias for APD)
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
    "vis": """
vis - Open ZOA airspace visualizer

Opens the ZOA airspace visualization tool in your browser.
Shows sector boundaries, airspace structure, and related info.

\b
URL: https://airspace.oakartcc.org/
""",
    "tdls": """
tdls [airport] - Open TDLS (Tower Data Link Services)

Opens the TDLS tool for sending Pre-Departure Clearances (PDCs)
to pilots. Optionally specify an airport code to go directly to
that airport's page.

\b
Examples:
  tdls          - Open TDLS home page
  tdls rno      - Open TDLS for RNO

\b
URL: https://tdls.virtualnas.net/
""",
    "strips": """
strips - Open flight strips

Opens the flight strips tool in your browser.
Used for managing flight progress strips.

\b
URL: https://strips.virtualnas.net/
""",
    "position": """
position - Look up ATC position frequencies

Searches for ATC positions by name, TCP code, callsign, or frequency.
Results are cached for faster subsequent lookups.

\b
Examples:
  position NCT           - Search by TCP code
  position 125.35        - Search by frequency
  position "NorCal"      - Search by callsign/name
  position OAK           - Search for Oakland positions
  position --browser     - Open positions page in browser
  position NCT --no-cache - Force fresh data fetch

Alias: 'pos' is an alias for 'position'
""",
    "pos": """
pos - Alias for 'position' command

See 'position --help' for full documentation.
""",
    "scratchpad": """
scratchpad - Look up STARS scratchpad codes

Shows scratchpad codes used for a specific facility/airport.
Use --list to see available facilities. Results are cached.

\b
Examples:
  scratchpad OAK         - Show OAK scratchpads
  scratchpad NCT         - Show NorCal TRACON scratchpads
  scratchpad --list      - List available facilities
  scratchpad OAK --no-cache - Force fresh data fetch

Alias: 'scratch' is an alias for 'scratchpad'
""",
    "scratch": """
scratch - Alias for 'scratchpad' command

See 'scratchpad --help' for full documentation.
""",
}


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
            self.visible_session = self.headless_session.create_child_session(
                headless=False
            )
        elif not self.visible_session.is_connected:
            click.echo("Reopening browser...")
            self.visible_session = self.headless_session.create_child_session(
                headless=False
            )
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


def print_interactive_help(include_misc: bool = True) -> None:
    """Print interactive mode command help.

    Args:
        include_misc: If True, include the misc section (help, quit).
    """
    for line in INTERACTIVE_HELP_COMMANDS:
        click.echo(line)
    if include_misc:
        click.echo("Misc:")
        click.echo("  help [command]            - Show help (e.g., help sop)")
        click.echo("  quit|exit|q               - Exit the program")


def print_command_help(command: str, main_group: click.Group) -> bool:
    """Print detailed help for a specific command using Click's help formatter.

    Args:
        command: The command name to show help for.
        main_group: The main Click group to look up commands from.

    Returns:
        True if help was found and printed, False otherwise.
    """
    cmd_lower = command.lower().strip()
    # Get the Click command from the main group
    ctx = click.Context(main_group)
    cmd = main_group.get_command(ctx, cmd_lower)
    if cmd is not None:
        # Create a context for the command and print its help
        with click.Context(cmd, info_name=cmd_lower, parent=ctx) as cmd_ctx:
            click.echo(cmd.get_help(cmd_ctx))
        return True
    return False


def get_running_browser() -> str | None:
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


def open_in_browser(
    file_path: str, view: str = "FitV", page: int | None = None
) -> bool:
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
    browser_cmd = get_running_browser()
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


def parse_interactive_args(
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

    return ParsedArgs(
        positional=positional, flags=flags, options=options, show_help=show_help
    )


def is_page_alive(page) -> bool:
    """Check if a page is still alive by attempting a simple operation."""
    try:
        page.evaluate("1")
        return True
    except Exception:
        return False


def wait_for_input_or_close(
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
        if page is not None and not is_page_alive(page):
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
        if args and not args[0].startswith("-"):
            cmd_name = args[0]
            if self.get_command(ctx, cmd_name) is None:
                # Not a known command - treat all args as chart query
                # Insert 'chart' command before the args
                args = ["chart"] + list(args)
        return super().parse_args(ctx, args)

    def format_help(self, ctx, formatter):
        """Write the same help as interactive mode."""
        click.echo("ZOA Reference CLI - Quick lookups to ZOA's Reference Tool.")
        click.echo("Usage: zoa [--playwright] [command] [args...]\n")
        print_interactive_help(include_misc=False)
        click.echo("\nRun 'zoa <command> --help' for detailed command help.")


def set_console_title(title: str) -> None:
    """Set the console window title using ANSI escape codes."""
    import sys

    sys.stdout.write(f"\033]0;{title}\007")
    sys.stdout.flush()
