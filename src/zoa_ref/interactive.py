"""Interactive mode handlers and main loop."""

import webbrowser

import click

from .autocomplete import ChartListCache, ZoaCompleter
from .browser import BrowserSession
from .cli_utils import (
    InteractiveContext,
    parse_interactive_args,
    print_interactive_help,
    print_command_help,
)
from .config import AIRSPACE_URL, TDLS_URL, STRIPS_URL
from .commands import (
    do_icao_lookup,
    do_navaid_lookup,
    do_airway_lookup,
    do_descent_calc,
    do_fix_descent,
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
from .icao import CodesPage
from .input import (
    create_prompt_session,
    prompt_with_history,
    NoDuplicatesFileHistory,
    HISTORY_FILE,
)


def _handle_list_interactive(args: str) -> None:
    """Handle 'list <airport> [chart_type] [search_term]' command in interactive mode."""
    parsed = parse_interactive_args(args)
    if parsed.show_help or not parsed.positional:
        # Import here to avoid circular import
        from .cli import main

        print_command_help("list", main)
        return

    airport = parsed.positional[0]
    chart_type = parsed.positional[1] if len(parsed.positional) > 1 else None
    search_term = parsed.positional[2] if len(parsed.positional) > 2 else None
    do_list_charts(airport, chart_type, search_term)


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

    Supports flags: -r (rotate 90), --rotate 90/180/270, --no-rotate, --link/-l
    """
    parsed = parse_interactive_args(
        query,
        flag_defs={
            "rotate_flag": ("-r",),
            "no_rotate": ("--no-rotate",),
            "link_only": ("--link", "-l"),
        },
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

    link_only = parsed.flags.get("link_only", False)

    # Get session if in playwright mode (not needed if link_only)
    visible_session = (
        ctx.get_or_create_visible_session()
        if ctx.use_playwright and not link_only
        else None
    )

    do_chart_lookup(
        " ".join(parsed.positional),
        link_only=link_only,
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
    webbrowser.open(AIRSPACE_URL)
    click.echo("Opened airspace visualizer")


def _handle_tdls_interactive(args: str) -> None:
    """Handle 'tdls' command in interactive mode."""
    facility = args.strip()
    if facility:
        url = f"{TDLS_URL}{facility.upper()}"
        webbrowser.open(url)
        click.echo(f"Opened TDLS for {facility.upper()}")
    else:
        webbrowser.open(TDLS_URL)
        click.echo("Opened TDLS")


def _handle_strips_interactive(args: str) -> None:
    """Handle 'strips' command in interactive mode."""
    facility = args.strip()
    if facility:
        url = f"{STRIPS_URL}{facility.upper()}"
        webbrowser.open(url)
        click.echo(f"Opened flight strips for {facility.upper()}")
    else:
        webbrowser.open(STRIPS_URL)
        click.echo("Opened flight strips")


def _handle_position_interactive(args: str, ctx: InteractiveContext) -> None:
    """Handle 'position <query> [--browser] [--no-cache]' command in interactive mode."""
    parsed = parse_interactive_args(
        args,
        flag_defs={"browser": ("--browser",), "no_cache": ("--no-cache",)},
    )
    if parsed.show_help or not parsed.positional:
        from .cli import main

        print_command_help("position", main)
        return

    do_position_lookup(
        " ".join(parsed.positional),
        browser=parsed.flags.get("browser", False),
        no_cache=parsed.flags.get("no_cache", False),
        headless_session=ctx.headless_session,
    )


def _handle_scratchpad_interactive(args: str, ctx: InteractiveContext) -> None:
    """Handle 'scratchpad [facility] [--list] [--no-cache]' command in interactive mode."""
    parsed = parse_interactive_args(
        args,
        flag_defs={"list": ("--list",), "no_cache": ("--no-cache",)},
    )

    if parsed.show_help:
        from .cli import main

        print_command_help("scratchpad", main)
        return

    facility = parsed.positional[0] if parsed.positional else None

    do_scratchpad_lookup(
        facility,
        list_facs=parsed.flags.get("list", False),
        no_cache=parsed.flags.get("no_cache", False),
        headless_session=ctx.headless_session,
    )


def _handle_navaid_interactive(args: str) -> None:
    """Handle 'navaid <query>' command in interactive mode."""
    parsed = parse_interactive_args(args)
    if parsed.show_help or not parsed.positional:
        from .cli import main

        print_command_help("navaid", main)
        return

    do_navaid_lookup(" ".join(parsed.positional))


def _handle_airway_interactive(args: str) -> None:
    """Handle 'airway <id> [highlight...]' command in interactive mode."""
    parsed = parse_interactive_args(args)
    if parsed.show_help or not parsed.positional:
        from .cli import main

        print_command_help("airway", main)
        return

    airway_id = parsed.positional[0]
    highlights = parsed.positional[1:] if len(parsed.positional) > 1 else None
    do_airway_lookup(airway_id, highlights)


def _handle_descent_interactive(args: str) -> None:
    """Handle 'descent <current_alt> <target_or_distance>' command in interactive mode."""
    parsed = parse_interactive_args(args)
    if parsed.show_help or len(parsed.positional) < 2:
        from .cli import main

        print_command_help("descent", main)
        return

    first_arg = parsed.positional[0]
    second_arg = parsed.positional[1]

    # If both arguments are fix/airport/navaid identifiers, use fix-to-fix mode
    if is_fix_identifier(first_arg) and is_fix_identifier(second_arg):
        do_fix_descent(first_arg, second_arg)
    else:
        do_descent_calc(first_arg, second_arg)


def _handle_approaches_interactive(args: str) -> None:
    """Handle 'approaches <airport> <star_or_fix> [runways...]' command in interactive mode."""
    parsed = parse_interactive_args(args)
    if parsed.show_help or len(parsed.positional) < 2:
        from .cli import main

        print_command_help("approaches", main)
        return

    # Remaining positional args after airport and star_or_fix are runway filters
    runways = parsed.positional[2:] if len(parsed.positional) > 2 else None
    do_approaches_lookup(parsed.positional[0], parsed.positional[1], runways)


def _handle_setbrowser_interactive(args: str) -> None:
    """Handle 'setbrowser [browser]' command in interactive mode."""
    parsed = parse_interactive_args(args)
    if parsed.show_help:
        from .cli import main

        print_command_help("setbrowser", main)
        return

    browser = parsed.positional[0] if parsed.positional else None
    do_setbrowser(browser)


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
    "al ": (_handle_airline_interactive, 3, True),
    "airport ": (_handle_airport_interactive, 8, True),
    "ap ": (_handle_airport_interactive, 3, True),
    "aircraft ": (_handle_aircraft_interactive, 9, True),
    "ac ": (_handle_aircraft_interactive, 3, True),
    "navaid ": (_handle_navaid_interactive, 7, False),
    "airway ": (_handle_airway_interactive, 7, False),
    "aw ": (_handle_airway_interactive, 3, False),
    "descent ": (_handle_descent_interactive, 8, False),
    "des ": (_handle_descent_interactive, 4, False),
    "approaches ": (_handle_approaches_interactive, 11, False),
    "apps ": (_handle_approaches_interactive, 5, False),
    "position ": (_handle_position_interactive, 9, True),
    "pos ": (_handle_position_interactive, 4, True),
    "scratchpad ": (_handle_scratchpad_interactive, 11, True),
    "scratch ": (_handle_scratchpad_interactive, 8, True),
    "vis": (_handle_vis_interactive, 3, False),
    "tdls": (_handle_tdls_interactive, 4, False),
    "strips": (_handle_strips_interactive, 6, False),
    "setbrowser": (_handle_setbrowser_interactive, 10, False),
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
    print_interactive_help()
    click.echo("=" * 50)
    click.echo()

    # Initialize chart list cache and start background prefetch
    chart_cache = ChartListCache()
    chart_cache.prefetch_airports()  # Uses major airports + user's top 10

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

    # Create shared history for both auto-suggest and completion menu
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    history = NoDuplicatesFileHistory(str(HISTORY_FILE))

    # Create prompt session with history and autocomplete
    completer = ZoaCompleter(chart_cache=chart_cache, history=history)
    prompt_session = create_prompt_session(completer=completer, history=history)

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
                            "Available commands: chart, charts, list, route, atis, sop, proc, airline (al), airport (ap), aircraft (ac)"
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

            # Check for "AIRPORT sop/proc" pattern before chart fallback
            parts = query.split(None, 2)  # Split into max 3 parts
            if len(parts) >= 2 and parts[1].lower() in ("sop", "proc"):
                # Rewrite "OAK sop 2-2" -> "OAK 2-2" as args to sop handler
                sop_args = parts[0] + (" " + parts[2] if len(parts) > 2 else "")
                _handle_sop_interactive(sop_args, ctx)
                click.echo()
                continue

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
