"""CLI interface for ZOA Reference Tool lookups."""

import webbrowser

import click

from .charts import ZOA_AIRPORTS
from .cli_utils import (
    COMMAND_HELP,
    ImplicitChartGroup,
    set_console_title,
    print_interactive_help,
)
from .completers import (
    complete_airport,
    complete_atis_airport,
    complete_chart_query,
    complete_chart_type,
    complete_facility,
    complete_navaid,
    complete_sop_query,
)
from .config import AIRSPACE_URL, TDLS_URL, STRIPS_URL
from .commands import (
    do_icao_lookup,
    do_navaid_lookup,
    do_airway_lookup,
    do_descent_calc,
    do_fix_descent,
    do_mea_lookup,
    do_route_lookup,
    do_atis_lookup,
    do_chart_lookup,
    do_charts_browse,
    do_list_charts,
    handle_sop_command,
    do_position_lookup,
    do_scratchpad_lookup,
    do_approaches_lookup,
    do_setbrowser,
)
from .descent import is_fix_identifier
from .interactive import interactive_mode


@click.group(cls=ImplicitChartGroup, invoke_without_command=True)
@click.option(
    "--playwright",
    is_flag=True,
    help="Use Playwright browser with tab management instead of system browser",
)
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
    # Set console title
    set_console_title("ZOA Ref CLI")

    # Store in context for subcommands that might need it
    ctx.ensure_object(dict)
    ctx.obj["playwright"] = playwright

    if ctx.invoked_subcommand is None:
        interactive_mode(use_playwright=playwright)


@main.command(help=COMMAND_HELP["chart"].strip())
@click.argument("query", nargs=-1, required=True, shell_complete=complete_chart_query)
@click.option(
    "--link", "-l", "link_only", is_flag=True, help="Output PDF URL only (don't open)"
)
@click.option("-r", "rotate_flag", is_flag=True, help="Rotate chart 90")
@click.option(
    "--rotate",
    type=click.Choice(["90", "180", "270"]),
    default=None,
    help="Rotate chart by specific degrees",
)
@click.option("--no-rotate", is_flag=True, help="Disable auto-rotation")
def chart(
    query: tuple[str, ...],
    link_only: bool,
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
    do_chart_lookup(" ".join(query), link_only=link_only, rotation=rotation)


@main.command(help=COMMAND_HELP["charts"].strip())
@click.argument("query", nargs=-1, required=True, shell_complete=complete_chart_query)
def charts(query: tuple[str, ...]):
    do_charts_browse(" ".join(query))


@main.command("list", help=COMMAND_HELP["list"].strip())
@click.argument("airport", shell_complete=complete_airport)
@click.argument(
    "chart_type", required=False, default=None, shell_complete=complete_chart_type
)
@click.argument("search_term", required=False, default=None)
def list_cmd(airport: str, chart_type: str | None, search_term: str | None):
    do_list_charts(airport, chart_type, search_term)


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
@click.argument("departure", shell_complete=complete_airport)
@click.argument("arrival", shell_complete=complete_airport)
@click.option("--browser", is_flag=True, help="Open browser instead of CLI display")
@click.option(
    "--all-routes",
    "-a",
    is_flag=True,
    help="Show all real world routes (default: top 5)",
)
@click.option(
    "--flights", "-f", is_flag=True, help="Show recent flights (hidden by default)"
)
@click.option(
    "--top",
    "-n",
    type=int,
    default=5,
    help="Number of real world routes to show (default: 5)",
)
@click.option(
    "--export-lc",
    is_flag=True,
    help="Export routes to LCTrainer cache format",
)
def route(
    departure: str,
    arrival: str,
    browser: bool,
    all_routes: bool,
    flights: bool,
    top: int,
    export_lc: bool,
):
    do_route_lookup(
        departure,
        arrival,
        browser=browser,
        show_all=all_routes,
        show_flights=flights,
        top_n=top,
        export_lc=export_lc,
    )


@main.command("export-routes")
@click.argument("departure", shell_complete=complete_airport)
@click.option(
    "--destinations",
    "-d",
    multiple=True,
    help="Specific destinations (default: common US airports)",
)
def export_routes(departure: str, destinations: tuple[str, ...]):
    """Export routes to LCTrainer cache for multiple destinations.

    Example: zoa export-routes KOAK
    Example: zoa export-routes KOAK -d KLAX -d KSFO -d KORD
    """
    from .commands import do_batch_route_export

    do_batch_route_export(departure, list(destinations) if destinations else None)


@main.command(help=COMMAND_HELP["airline"].strip())
@click.argument("query", nargs=-1, required=True)
@click.option("--browser", is_flag=True, help="Open browser instead of CLI display")
@click.option("--no-cache", is_flag=True, help="Bypass cache and fetch fresh data")
def airline(query: tuple[str, ...], browser: bool, no_cache: bool):
    do_icao_lookup("airline", " ".join(query), browser=browser, no_cache=no_cache)


@main.command("al", help=COMMAND_HELP["airline"].strip())
@click.argument("query", nargs=-1, required=True)
@click.option("--browser", is_flag=True, help="Open browser instead of CLI display")
@click.option("--no-cache", is_flag=True, help="Bypass cache and fetch fresh data")
def al(query: tuple[str, ...], browser: bool, no_cache: bool):
    do_icao_lookup("airline", " ".join(query), browser=browser, no_cache=no_cache)


@main.command(help=COMMAND_HELP["airport"].strip())
@click.argument("query", nargs=-1, required=True)
@click.option("--browser", is_flag=True, help="Open browser instead of CLI display")
@click.option("--no-cache", is_flag=True, help="Bypass cache and fetch fresh data")
def airport(query: tuple[str, ...], browser: bool, no_cache: bool):
    do_icao_lookup("airport", " ".join(query), browser=browser, no_cache=no_cache)


@main.command("ap", help=COMMAND_HELP["airport"].strip())
@click.argument("query", nargs=-1, required=True)
@click.option("--browser", is_flag=True, help="Open browser instead of CLI display")
@click.option("--no-cache", is_flag=True, help="Bypass cache and fetch fresh data")
def ap(query: tuple[str, ...], browser: bool, no_cache: bool):
    do_icao_lookup("airport", " ".join(query), browser=browser, no_cache=no_cache)


@main.command(help=COMMAND_HELP["aircraft"].strip())
@click.argument("query", nargs=-1, required=True)
@click.option("--browser", is_flag=True, help="Open browser instead of CLI display")
@click.option("--no-cache", is_flag=True, help="Bypass cache and fetch fresh data")
def aircraft(query: tuple[str, ...], browser: bool, no_cache: bool):
    do_icao_lookup("aircraft", " ".join(query), browser=browser, no_cache=no_cache)


@main.command("ac", help=COMMAND_HELP["aircraft"].strip())
@click.argument("query", nargs=-1, required=True)
@click.option("--browser", is_flag=True, help="Open browser instead of CLI display")
@click.option("--no-cache", is_flag=True, help="Bypass cache and fetch fresh data")
def ac(query: tuple[str, ...], browser: bool, no_cache: bool):
    do_icao_lookup("aircraft", " ".join(query), browser=browser, no_cache=no_cache)


@main.command(help=COMMAND_HELP["navaid"].strip())
@click.argument("query", nargs=-1, required=True, shell_complete=complete_navaid)
def navaid(query: tuple[str, ...]):
    do_navaid_lookup(" ".join(query))


@main.command(help=COMMAND_HELP["airway"].strip())
@click.argument("airway_id", required=True)
@click.argument("highlights", nargs=-1)
def airway(airway_id: str, highlights: tuple[str, ...]):
    do_airway_lookup(airway_id, list(highlights) if highlights else None)


@main.command("aw", help=COMMAND_HELP["airway"].strip())
@click.argument("airway_id", required=True)
@click.argument("highlights", nargs=-1)
def aw(airway_id: str, highlights: tuple[str, ...]):
    do_airway_lookup(airway_id, list(highlights) if highlights else None)


@main.command(help=COMMAND_HELP["descent"].strip())
@click.argument("first_arg")
@click.argument("second_arg")
def descent(first_arg: str, second_arg: str):
    # If both arguments are fix/airport/navaid identifiers, use fix-to-fix mode
    if is_fix_identifier(first_arg) and is_fix_identifier(second_arg):
        do_fix_descent(first_arg, second_arg)
    else:
        do_descent_calc(first_arg, second_arg)


@main.command("des", help=COMMAND_HELP["descent"].strip())
@click.argument("first_arg")
@click.argument("second_arg")
def des(first_arg: str, second_arg: str):
    # If both arguments are fix/airport/navaid identifiers, use fix-to-fix mode
    if is_fix_identifier(first_arg) and is_fix_identifier(second_arg):
        do_fix_descent(first_arg, second_arg)
    else:
        do_descent_calc(first_arg, second_arg)


@main.command(help=COMMAND_HELP["approaches"].strip())
@click.argument("airport", shell_complete=complete_airport)
@click.argument("star_or_fix")
@click.argument("runways", nargs=-1)
def approaches(airport: str, star_or_fix: str, runways: tuple[str, ...]):
    do_approaches_lookup(airport, star_or_fix, list(runways) if runways else None)


@main.command("apps", help=COMMAND_HELP["apps"].strip())
@click.argument("airport", shell_complete=complete_airport)
@click.argument("star_or_fix")
@click.argument("runways", nargs=-1)
def apps(airport: str, star_or_fix: str, runways: tuple[str, ...]):
    do_approaches_lookup(airport, star_or_fix, list(runways) if runways else None)


@main.command(help=COMMAND_HELP["mea"].strip())
@click.argument("route", nargs=-1, required=True)
@click.option(
    "--altitude",
    "-a",
    type=int,
    default=None,
    help="Altitude in hundreds of feet (e.g., 100 = 10,000 ft)",
)
def mea(route: tuple[str, ...], altitude: int | None):
    do_mea_lookup(" ".join(route), altitude)


# --- Procedure/SOP Commands ---


@main.command(help=COMMAND_HELP["sop"].strip())
@click.argument("query", nargs=-1, required=False, shell_complete=complete_sop_query)
@click.option("--list", "list_procs", is_flag=True, help="List available procedures")
@click.option("--no-cache", is_flag=True, help="Bypass cache and fetch fresh data")
def sop(query: tuple[str, ...], list_procs: bool, no_cache: bool):
    handle_sop_command(query or (), list_procs, no_cache)


@main.command("proc", help=COMMAND_HELP["proc"].strip())
@click.argument("query", nargs=-1, required=False, shell_complete=complete_sop_query)
@click.option("--list", "list_procs", is_flag=True, help="List available procedures")
@click.option("--no-cache", is_flag=True, help="Bypass cache and fetch fresh data")
def proc(query: tuple[str, ...], list_procs: bool, no_cache: bool):
    handle_sop_command(query or (), list_procs, no_cache)


@main.command(help=COMMAND_HELP["atis"].strip())
@click.argument("airport", required=False, shell_complete=complete_atis_airport)
@click.option(
    "--all", "-a", "show_all", is_flag=True, help="Show ATIS for all airports"
)
def atis(airport: str | None, show_all: bool):
    do_atis_lookup(airport, show_all=show_all)


@main.command(help=COMMAND_HELP["vis"].strip())
def vis():
    """Open ZOA airspace visualizer."""
    webbrowser.open(AIRSPACE_URL)
    click.echo("Opened airspace visualizer")


@main.command(help=COMMAND_HELP["tdls"].strip())
@click.argument(
    "facility", required=False, default=None, shell_complete=complete_facility
)
def tdls(facility: str | None):
    """Open TDLS (Pre-Departure Clearances)."""
    if facility:
        url = f"{TDLS_URL}{facility.upper()}"
        webbrowser.open(url)
        click.echo(f"Opened TDLS for {facility.upper()}")
    else:
        webbrowser.open(TDLS_URL)
        click.echo("Opened TDLS")


@main.command(help=COMMAND_HELP["strips"].strip())
@click.argument("facility", required=False, shell_complete=complete_facility)
def strips(facility: str | None):
    """Open flight strips."""
    if facility:
        url = f"{STRIPS_URL}{facility.upper()}"
        webbrowser.open(url)
        click.echo(f"Opened flight strips for {facility.upper()}")
    else:
        webbrowser.open(STRIPS_URL)
        click.echo("Opened flight strips")


@main.command("help")
@click.argument("command", required=False)
@click.pass_context
def help_cmd(ctx, command: str | None):
    """Show help for a command."""
    if command:
        # Show help for specific command
        cmd = main.get_command(ctx, command)
        if cmd:
            # Create context with main as parent so usage shows "zoa <cmd>" not "zoa help <cmd>"
            with click.Context(cmd, info_name=command, parent=ctx.parent) as cmd_ctx:
                click.echo(cmd.get_help(cmd_ctx))
        else:
            click.echo(f"Unknown command: {command}")
            click.echo("Run 'zoa --help' to see available commands.")
    else:
        # Show general help
        click.echo("ZOA Reference CLI - Quick lookups to ZOA's Reference Tool.")
        click.echo("Usage: zoa [--playwright] [command] [args...]\n")
        print_interactive_help(include_misc=False)
        click.echo("\nRun 'zoa help <command>' for detailed command help.")


# --- Position Commands ---


@main.command(help=COMMAND_HELP["position"].strip())
@click.argument("query", nargs=-1, required=True, shell_complete=complete_facility)
@click.option("--browser", is_flag=True, help="Open browser instead of CLI display")
@click.option("--no-cache", is_flag=True, help="Bypass cache and fetch fresh data")
def position(query: tuple[str, ...], browser: bool, no_cache: bool):
    do_position_lookup(" ".join(query), browser=browser, no_cache=no_cache)


@main.command("pos", help=COMMAND_HELP["pos"].strip())
@click.argument("query", nargs=-1, required=True, shell_complete=complete_facility)
@click.option("--browser", is_flag=True, help="Open browser instead of CLI display")
@click.option("--no-cache", is_flag=True, help="Bypass cache and fetch fresh data")
def pos(query: tuple[str, ...], browser: bool, no_cache: bool):
    do_position_lookup(" ".join(query), browser=browser, no_cache=no_cache)


# --- Scratchpad Commands ---


@main.command(help=COMMAND_HELP["scratchpad"].strip())
@click.argument("facility", required=False, shell_complete=complete_facility)
@click.option("--list", "list_facs", is_flag=True, help="List available facilities")
@click.option("--no-cache", is_flag=True, help="Bypass cache and fetch fresh data")
def scratchpad(facility: str | None, list_facs: bool, no_cache: bool):
    do_scratchpad_lookup(facility, list_facs=list_facs, no_cache=no_cache)


@main.command("scratch", help=COMMAND_HELP["scratch"].strip())
@click.argument("facility", required=False, shell_complete=complete_facility)
@click.option("--list", "list_facs", is_flag=True, help="List available facilities")
@click.option("--no-cache", is_flag=True, help="Bypass cache and fetch fresh data")
def scratch(facility: str | None, list_facs: bool, no_cache: bool):
    do_scratchpad_lookup(facility, list_facs=list_facs, no_cache=no_cache)


@main.command(help=COMMAND_HELP["setbrowser"].strip())
@click.argument("browser", required=False)
def setbrowser(browser: str | None):
    """Set preferred browser for opening charts."""
    do_setbrowser(browser)


if __name__ == "__main__":
    main()
