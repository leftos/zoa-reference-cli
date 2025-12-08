"""Interactive mode handlers and main loop."""

import webbrowser

import click

from .browser import BrowserSession
from .charts import fetch_charts_from_api
from .cli_utils import (
    InteractiveContext,
    parse_interactive_args,
    print_interactive_help,
    print_command_help,
)
from .commands import (
    do_icao_lookup,
    do_route_lookup,
    do_atis_lookup,
    do_chart_lookup,
    do_charts_browse,
    handle_sop_command,
)
from .icao import CodesPage
from .input import create_prompt_session, prompt_with_history


def _handle_list_interactive(args: str) -> None:
    """Handle 'list <airport>' command in interactive mode."""
    parsed = parse_interactive_args(args)
    if parsed.show_help or not parsed.positional:
        # Import here to avoid circular import
        from .cli import main

        print_command_help("list", main)
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
    else:
        click.echo(f"No charts found for {airport}")


def _handle_charts_interactive(args: str, ctx: InteractiveContext) -> None:
    """Handle 'charts <query>' command in interactive mode."""
    parsed = parse_interactive_args(args)
    if parsed.show_help or not parsed.positional:
        from .cli import main

        print_command_help("charts", main)
        return
    query_str = " ".join(parsed.positional)

    # Get or create visible browser session for charts browsing
    visible_session = ctx.get_or_create_visible_session()
    do_charts_browse(query_str, visible_session=visible_session)


def _handle_route_interactive(args: str, ctx: InteractiveContext) -> None:
    """Handle 'route <departure> <arrival> [options]' command in interactive mode."""
    parsed = parse_interactive_args(
        args,
        flag_defs={
            "all": ("-a", "--all"),
            "flights": ("-f", "--flights"),
            "browser": ("--browser",),
        },
        option_defs={"top": ("-n", "--top")},
    )

    if parsed.show_help or len(parsed.positional) < 2:
        from .cli import main

        print_command_help("route", main)
        return

    try:
        top_n = int(parsed.options.get("top", 5))
    except ValueError:
        top_n = 5

    do_route_lookup(
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
    parsed = parse_interactive_args(
        args,
        flag_defs={"all": ("-a", "--all")},
    )

    if parsed.show_help:
        from .cli import main

        print_command_help("atis", main)
        return

    # "atis all" or "atis -a" means show all
    show_all = parsed.flags.get("all", False)
    if parsed.positional and parsed.positional[0].upper() == "ALL":
        show_all = True
        parsed.positional.pop(0)

    airport = parsed.positional[0] if parsed.positional else None

    do_atis_lookup(
        airport,
        show_all=show_all,
        headless_session=ctx.headless_session,
    )


def _handle_airline_interactive(args: str, ctx: InteractiveContext) -> None:
    """Handle 'airline <query> [--browser] [--no-cache]' command in interactive mode."""
    parsed = parse_interactive_args(
        args,
        flag_defs={"browser": ("--browser",), "no_cache": ("--no-cache",)},
    )
    if parsed.show_help or not parsed.positional:
        from .cli import main

        print_command_help("airline", main)
        return

    do_icao_lookup(
        "airline",
        " ".join(parsed.positional),
        browser=parsed.flags.get("browser", False),
        no_cache=parsed.flags.get("no_cache", False),
        codes_page=ctx.codes_page,
        headless_session=ctx.headless_session,
    )


def _handle_airport_interactive(args: str, ctx: InteractiveContext) -> None:
    """Handle 'airport <query> [--browser] [--no-cache]' command in interactive mode."""
    parsed = parse_interactive_args(
        args,
        flag_defs={"browser": ("--browser",), "no_cache": ("--no-cache",)},
    )
    if parsed.show_help or not parsed.positional:
        from .cli import main

        print_command_help("airport", main)
        return

    do_icao_lookup(
        "airport",
        " ".join(parsed.positional),
        browser=parsed.flags.get("browser", False),
        no_cache=parsed.flags.get("no_cache", False),
        codes_page=ctx.codes_page,
        headless_session=ctx.headless_session,
    )


def _handle_aircraft_interactive(args: str, ctx: InteractiveContext) -> None:
    """Handle 'aircraft <query> [--browser] [--no-cache]' command in interactive mode."""
    parsed = parse_interactive_args(
        args,
        flag_defs={"browser": ("--browser",), "no_cache": ("--no-cache",)},
    )
    if parsed.show_help or not parsed.positional:
        from .cli import main

        print_command_help("aircraft", main)
        return

    do_icao_lookup(
        "aircraft",
        " ".join(parsed.positional),
        browser=parsed.flags.get("browser", False),
        no_cache=parsed.flags.get("no_cache", False),
        codes_page=ctx.codes_page,
        headless_session=ctx.headless_session,
    )


def _handle_chart_interactive(query: str, ctx: InteractiveContext) -> None:
    """Handle implicit chart lookup in interactive mode.

    Supports flags: -r (rotate 90), --rotate 90/180/270, --no-rotate
    """
    parsed = parse_interactive_args(
        query,
        flag_defs={"rotate_flag": ("-r",), "no_rotate": ("--no-rotate",)},
        option_defs={"rotate": ("--rotate",)},
    )

    if parsed.show_help or not parsed.positional:
        from .cli import main

        print_command_help("chart", main)
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
    visible_session = (
        ctx.get_or_create_visible_session() if ctx.use_playwright else None
    )

    do_chart_lookup(
        " ".join(parsed.positional),
        rotation=rotation,
        visible_session=visible_session,
    )


def _handle_sop_interactive(args: str, ctx: InteractiveContext) -> None:
    """Handle 'sop <query> [--list] [--no-cache]' command in interactive mode."""
    parsed = parse_interactive_args(
        args,
        flag_defs={"list": ("--list",), "no_cache": ("--no-cache",)},
    )

    if parsed.show_help:
        from .cli import main

        print_command_help("sop", main)
        return

    # Convert positional args to tuple for handle_sop_command
    # This preserves the ability to handle quoted strings from the original input
    query_tuple = tuple(parsed.positional)

    handle_sop_command(
        query_tuple,
        list_procs=parsed.flags.get("list", False),
        no_cache=parsed.flags.get("no_cache", False),
        headless_session=ctx.headless_session,
    )


def _handle_vis_interactive(args: str) -> None:
    """Handle 'vis' command in interactive mode."""
    webbrowser.open("https://airspace.oakartcc.org/")
    click.echo("Opened airspace visualizer")


def _handle_tdls_interactive(args: str) -> None:
    """Handle 'tdls' command in interactive mode."""
    airport = args.strip()
    if airport:
        url = f"https://tdls.virtualnas.net/{airport.upper()}"
        webbrowser.open(url)
        click.echo(f"Opened TDLS for {airport.upper()}")
    else:
        webbrowser.open("https://tdls.virtualnas.net/")
        click.echo("Opened TDLS")


def _handle_strips_interactive(args: str) -> None:
    """Handle 'strips' command in interactive mode."""
    webbrowser.open("https://strips.virtualnas.net/")
    click.echo("Opened flight strips")


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
    "vis": (_handle_vis_interactive, 3, False),
    "tdls": (_handle_tdls_interactive, 4, False),
    "strips": (_handle_strips_interactive, 6, False),
}


def interactive_mode(use_playwright: bool = False):
    """Run in interactive mode for continuous lookups.

    Args:
        use_playwright: If True, use Playwright browser with tab management.
                       If False (default), use system browser via webbrowser.open().
    """
    # Import here to avoid circular import at module level
    from .cli import main

    click.echo("ZOA Reference CLI - Interactive Mode")
    if use_playwright:
        click.echo("(Using Playwright browser with tab management)")
    click.echo("=" * 50)
    print_interactive_help(include_help_line=True)
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
                print_interactive_help()
                click.echo()
                continue

            if lower_query.startswith("help "):
                cmd_name = query[5:].strip()
                if cmd_name:
                    if not print_command_help(cmd_name, main):
                        click.echo(f"Unknown command: {cmd_name}")
                        click.echo(
                            "Available commands: chart, charts, list, route, atis, sop, proc, airline, airport, aircraft"
                        )
                else:
                    print_interactive_help()
                click.echo()
                continue

            # Check command registry
            handled = False
            for prefix, (
                handler,
                prefix_len,
                needs_ctx,
            ) in INTERACTIVE_COMMANDS.items():
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
                    click.echo(
                        "Usage: chart <airport> <chart>  (e.g., chart OAK CNDEL5)"
                    )
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
