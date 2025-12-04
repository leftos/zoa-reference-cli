"""CLI interface for ZOA Reference Tool lookups."""

import click
from .browser import BrowserSession
from .charts import ChartQuery, lookup_chart, list_charts, ZOA_AIRPORTS


@click.group(invoke_without_command=True)
@click.pass_context
def main(ctx):
    """ZOA Reference CLI - Quick lookups to ZOA's Reference Tool.

    Run without arguments to enter interactive mode.

    Examples:

        zoa chart OAK CNDEL5     - Look up the CNDEL FIVE departure at OAK

        zoa chart SFO ILS 28L    - Look up the ILS 28L approach at SFO

        zoa list OAK             - List all charts available for OAK
    """
    if ctx.invoked_subcommand is None:
        interactive_mode()


@main.command()
@click.argument("query", nargs=-1, required=True)
@click.option("--headless", is_flag=True, help="Run browser in headless mode")
def chart(query: tuple[str, ...], headless: bool):
    """Look up a chart.

    Examples:

        zoa chart OAK CNDEL5     - CNDEL FIVE departure

        zoa chart OAK ILS 28R    - ILS or LOC RWY 28R approach

        zoa chart SFO RNAV 28L   - RNAV approach to runway 28L
    """
    query_str = " ".join(query)
    _lookup_chart(query_str, headless=headless)


@main.command("list")
@click.argument("airport")
@click.option("--headless", is_flag=True, help="Run browser in headless mode")
def list_cmd(airport: str, headless: bool):
    """List all charts for an airport.

    Example: zoa list OAK
    """
    airport = airport.upper()
    if airport not in ZOA_AIRPORTS:
        click.echo(f"Warning: {airport} is not a known ZOA airport")

    click.echo(f"Fetching charts for {airport}...")

    with BrowserSession(headless=headless) as session:
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


def _lookup_chart(query_str: str, headless: bool = False, session: BrowserSession | None = None) -> bool:
    """Internal function to look up a chart."""
    try:
        parsed = ChartQuery.parse(query_str)
        click.echo(f"Looking up: {parsed.airport} - {parsed.chart_name}")
        if parsed.chart_type.value != "unknown":
            click.echo(f"  Detected type: {parsed.chart_type.value.upper()}")
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        return False

    own_session = session is None
    if own_session:
        session = BrowserSession(headless=headless)
        session.start()

    try:
        page = session.new_page()
        success = lookup_chart(page, parsed)

        if success:
            click.echo("Chart found! Browser will remain open.")
        else:
            click.echo("Could not find chart. Browser will remain open for manual navigation.")

        if own_session and not headless:
            click.echo("\nPress Enter to close the browser...")
            input()

        return success
    finally:
        if own_session:
            session.stop()


def interactive_mode():
    """Run in interactive mode for continuous lookups."""
    click.echo("ZOA Reference CLI - Interactive Mode")
    click.echo("=" * 50)
    click.echo("Commands:")
    click.echo("  <airport> <chart>  - Look up a chart (e.g., OAK CNDEL5)")
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

            # Treat as chart lookup
            try:
                parsed = ChartQuery.parse(query)
                click.echo(f"Looking up: {parsed.airport} - {parsed.chart_name}")

                page = session.new_page()
                success = lookup_chart(page, parsed)

                if success:
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
