"""Shared command implementations for CLI and interactive modes."""

import os
import re
import tempfile
import webbrowser
from pathlib import Path

import click

from .atis import fetch_atis, fetch_all_atis, ATIS_AIRPORTS
from .browser import BrowserSession, _calculate_viewport_size
from .charts import (
    ChartInfo,
    ChartMatch,
    ChartQuery,
    lookup_chart,
    fetch_charts_from_api,
    find_all_chart_pages,
    lookup_chart_with_pages,
    download_and_merge_pdfs,
    download_and_rotate_pdf,
    detect_pdf_view_mode,
    download_pdf,
    find_airport_page_in_min_chart,
)
from .cli_utils import open_in_browser, wait_for_input_or_close
from .display import (
    display_routes,
    display_airlines,
    display_airport_codes,
    display_aircraft,
    display_atis,
    display_chart_matches,
    display_navaids,
    display_procedure_matches,
    display_positions,
    display_scratchpads,
    display_scratchpad_facilities,
)
from .icao import (
    search_airline,
    search_airport_code,
    search_aircraft,
    open_codes_browser,
    CodesPage,
)
from .input import prompt_single_choice
from .navaids import search_navaids
from .positions import search_positions, open_positions_browser
from .procedures import (
    ProcedureQuery,
    ProcedureInfo,
    ProcedureMatch,
    fetch_procedures_list,
    find_procedure_by_name,
    find_heading_page,
    find_text_in_section,
    list_all_procedures,
    _download_pdf as download_procedure_pdf,
    AIRPORT_ALIASES,
)
from .routes import search_routes, open_routes_browser
from .scratchpads import get_scratchpads, list_facilities, open_scratchpads_browser


def prompt_procedure_choice(matches: list[ProcedureMatch]) -> ProcedureInfo | None:
    """Prompt user to select from numbered matches."""
    idx = prompt_single_choice(len(matches))
    if idx is not None:
        return matches[idx - 1].procedure
    return None


def prompt_chart_choice(matches: list[ChartMatch]) -> ChartInfo | None:
    """Prompt user to select from numbered chart matches."""
    idx = prompt_single_choice(len(matches))
    if idx is not None:
        return matches[idx - 1].chart
    return None


def sanitize_chart_filename(airport: str, chart_name: str) -> str:
    """Convert chart name to a clean, descriptive filename.

    Rules:
    - Keep CAT designations from parentheses (e.g., SA CAT I, CAT II - III)
    - Remove all other parenthesized content (RNAV, RNP, GPS, etc.)
    - Remove the word RWY
    - Strip standalone hyphens
    - Replace spaces with underscores
    - Convert trailing number words (ONE, TWO, etc.) to digits without underscore
    """
    # Reverse mapping: word -> digit for chart iteration numbers
    word_to_digit = {
        "ONE": "1",
        "TWO": "2",
        "THREE": "3",
        "FOUR": "4",
        "FIVE": "5",
        "SIX": "6",
        "SEVEN": "7",
        "EIGHT": "8",
        "NINE": "9",
    }

    name = chart_name
    # Extract CAT designations from parentheses before removal
    cat_matches = re.findall(r"\(([^)]*CAT[^)]*)\)", name)
    cat_suffix = ""
    if cat_matches:
        cat_text = cat_matches[0]
        cat_text = re.sub(r"\s+-\s+", "_", cat_text)  # Strip standalone hyphens
        cat_text = re.sub(r"\s+", "_", cat_text)
        cat_suffix = "_" + cat_text
    # Remove anything in parentheses
    name = re.sub(r"\s*\([^)]*\)", "", name)
    # Remove 'RWY' word
    name = re.sub(r"\bRWY\b", "", name)
    # Remove special chars (keep alphanumeric, spaces, hyphens)
    name = re.sub(r"[^\w\s-]", "", name)
    # Strip standalone hyphens (surrounded by spaces)
    name = re.sub(r"\s+-\s+", " ", name)
    # Collapse multiple spaces and convert to underscores
    name = re.sub(r"\s+", "_", name.strip())
    # Remove any trailing/leading underscores
    name = name.strip("_")
    # Convert trailing number words to digits (e.g., SCTWN_FOUR -> SCTWN4)
    for word, digit in word_to_digit.items():
        if name.endswith(f"_{word}"):
            name = name[: -len(word) - 1] + digit
            break
    # Extract runway number from end and move after airport (e.g., ILS_OR_LOC_15 -> RWY15_ILS_OR_LOC)
    runway_match = re.search(r"_(\d{1,2}[LRC]?)$", name)
    if runway_match:
        runway = runway_match.group(1)
        name = name[: runway_match.start()]
        return f"ZOA_{airport}_RWY{runway}_{name}{cat_suffix}.pdf"
    return f"ZOA_{airport}_{name}{cat_suffix}.pdf"


def sanitize_procedure_filename(procedure_name: str) -> str:
    """Convert procedure name to a clean, descriptive filename.

    Example: "Sacramento ATCT SOP" -> "ZOA_SOP_SMF_ATCT.pdf"
    Example: "ZOA - NCT LOA" -> "ZOA_LOA_ZOA_NCT.pdf"
    """
    # Build reverse mapping: city name -> airport code
    city_to_code = {name.upper(): code for code, name in AIRPORT_ALIASES.items()}
    # Add multi-word variants
    city_to_code["SAN FRANCISCO"] = "SFO"
    city_to_code["SAN JOSE"] = "SJC"
    city_to_code["OAKLAND CENTER"] = "ZOA"
    city_to_code["NORTHERN CALIFORNIA TRACON"] = "NCT"
    city_to_code["NORTHERN CALIFORNIA"] = "NCT"
    city_to_code["RENO-TAHOE"] = "RNO"

    # Detect document type (LOA takes precedence over SOP)
    doc_type = "SOP"
    if re.search(r"\bLOA\b", procedure_name, re.IGNORECASE):
        doc_type = "LOA"

    name = procedure_name
    # Remove parenthesized codes like (NCT), (FAT) - they're redundant
    name = re.sub(r"\s*\([A-Z]{2,4}\)", "", name)
    # Replace city names with airport codes (case-insensitive)
    for city, code in sorted(city_to_code.items(), key=lambda x: -len(x[0])):
        pattern = re.compile(re.escape(city), re.IGNORECASE)
        name = pattern.sub(code, name)
    # Replace slashes with underscores before removing special chars
    name = name.replace("/", "_")
    # Remove special chars (keep alphanumeric, spaces, hyphens)
    name = re.sub(r"[^\w\s-]", "", name)
    # Remove "SOP" and "LOA" since doc_type is in the prefix
    name = re.sub(r"\b(SOP|LOA)\b", "", name, flags=re.IGNORECASE)
    # Clean up standalone hyphens and multiple spaces
    name = re.sub(r"\s+-\s+", "_", name)
    name = re.sub(r"\s+", "_", name.strip())
    name = re.sub(r"_+", "_", name)  # Collapse multiple underscores
    name = name.strip("_")
    return f"ZOA_{doc_type}_{name}.pdf"


def open_procedure_pdf(procedure: ProcedureInfo, page_num: int = 1) -> None:
    """Open a procedure PDF at a specific page."""
    click.echo(f"Opening: {procedure.name}")
    if page_num > 1:
        click.echo(f"  Page: {page_num}")

    # Download PDF to temp file with descriptive name
    pdf_data = download_procedure_pdf(procedure.full_url)
    if pdf_data:
        filename = sanitize_procedure_filename(procedure.name)
        temp_path = os.path.join(tempfile.gettempdir(), filename)
        with open(temp_path, "wb") as f:
            f.write(pdf_data)

        # Open with page fragment
        if page_num > 1:
            open_in_browser(temp_path, page=page_num, view="FitV")
        else:
            open_in_browser(temp_path, view="FitV")
    else:
        # Fall back to opening URL directly
        click.echo("Failed to download, opening URL directly...", err=True)
        pdf_url = procedure.full_url
        if page_num > 1:
            url_with_page = f"{pdf_url}#page={page_num}&view=FitV"
        else:
            url_with_page = f"{pdf_url}#view=FitV"
        webbrowser.open(url_with_page)


def open_chart_pdf(
    pdf_urls: list[str],
    airport: str,
    chart_name: str,
    rotation: int | None = None,
    session: "BrowserSession | None" = None,
    page_num: int | None = None,
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
        page_num: Optional page number to open at (1-based). Used for MIN charts.

    Returns:
        Path to opened file/URL, or None on failure.
    """
    num_pages = len(pdf_urls)

    if num_pages == 1:
        pdf_url = pdf_urls[0]

        if session is not None:
            # Playwright mode: check if already open (tab reuse)
            pw_page, was_existing = session.get_or_create_page(pdf_url)
            if was_existing:
                click.echo(f"Chart already open: {chart_name}")
            else:
                fragment = f"view=FitV"
                if page_num:
                    fragment = f"page={page_num}&{fragment}"
                pw_page.goto(f"{pdf_url}#{fragment}")
                click.echo(f"Chart found: {chart_name}")
                if page_num:
                    click.echo(f"  Page: {page_num}")
            return pdf_url

        # System browser mode: download, optionally rotate, and open
        filename = sanitize_chart_filename(airport, chart_name)
        temp_path = os.path.join(tempfile.gettempdir(), filename)

        if download_and_rotate_pdf(pdf_url, temp_path, rotation):
            view_mode = detect_pdf_view_mode(temp_path)
            click.echo(f"Opening chart: {chart_name}")
            if page_num:
                click.echo(f"  Page: {page_num}")
            open_in_browser(temp_path, view=view_mode, page=page_num)
            return temp_path
        else:
            click.echo("Failed to download chart", err=True)
            # Fall back to opening URL directly (no rotation)
            fragment = f"view=FitV"
            if page_num:
                fragment = f"page={page_num}&{fragment}"
            webbrowser.open(f"{pdf_url}#{fragment}")
            return pdf_url
    else:
        # Multi-page chart - merge pages
        click.echo(f"Chart has {num_pages} pages, merging...")

        filename = sanitize_chart_filename(airport, chart_name)
        temp_path = os.path.join(tempfile.gettempdir(), filename)

        if download_and_merge_pdfs(pdf_urls, temp_path, rotation):
            view_mode = detect_pdf_view_mode(temp_path)
            if session is not None:
                # Playwright mode
                page = session.new_page()
                page.goto(f"{Path(temp_path).as_uri()}#view={view_mode}")
            else:
                # System browser mode
                open_in_browser(temp_path, view=view_mode)
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


def list_procedures(
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
        "policy",
        "enroute",
        "tracon",
        "atct",
        "loa_internal",
        "loa_external",
        "loa_military",
        "zak",
        "quick_ref",
        "other",
    ]

    for cat in display_order:
        if cat in by_category:
            procs = by_category[cat]
            display_name = category_names.get(cat, cat.title())
            click.echo(f"\n{display_name}:")
            click.echo("-" * 40)
            for proc in procs:
                click.echo(f"  {proc.name}")


def handle_sop_command(
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
        list_procedures(no_cache, headless_session=headless_session)
        return

    # Parse query - pass tuple directly to preserve quoted strings
    if not query:
        click.echo("Usage: sop <query>  (e.g., sop OAK 2-2)")
        click.echo('       sop SJC "IFR Departures" SJCE  (multi-step lookup)')
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
            choice = prompt_procedure_choice(matches)
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
        click.echo(
            f"Searching for '{parsed.search_term}' in section '{parsed.section_term}'..."
        )
        found_page = find_text_in_section(
            procedure, parsed.section_term, parsed.search_term, use_cache=not no_cache
        )
        if found_page:
            page_num = found_page
            click.echo(f"Found '{parsed.search_term}' at page {page_num}")
        else:
            # Fall back to just the section
            click.echo(
                f"'{parsed.search_term}' not found in section, trying section only..."
            )
            found_page = find_heading_page(
                procedure, parsed.section_term, use_cache=not no_cache
            )
            if found_page:
                page_num = found_page
                click.echo(f"Found section at page {page_num}")
            else:
                click.echo(
                    f"Section '{parsed.section_term}' not found, opening first page"
                )
    elif parsed.section_term:
        # Single section lookup
        click.echo(f"Searching for section '{parsed.section_term}'...")
        found_page = find_heading_page(
            procedure, parsed.section_term, use_cache=not no_cache
        )
        if found_page:
            page_num = found_page
            click.echo(f"Found section at page {page_num}")
        else:
            click.echo(f"Section '{parsed.section_term}' not found, opening first page")

    # Open PDF at page
    open_procedure_pdf(procedure, page_num)


def do_icao_lookup(
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
                wait_for_input_or_close(
                    session, "Codes page open. Press Enter to close browser...", page
                )
            else:
                wait_for_input_or_close(
                    session,
                    "Failed to load codes page. Press Enter to close browser...",
                    page,
                )
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


def do_route_lookup(
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
                wait_for_input_or_close(
                    session, "Routes page open. Press Enter to close browser...", page
                )
            else:
                wait_for_input_or_close(
                    session,
                    "Failed to load routes page. Press Enter to close browser...",
                    page,
                )
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
                    display_routes(
                        result,
                        max_real_world=None if show_all else top_n,
                        show_flights=show_flights,
                    )
                else:
                    click.echo("Failed to retrieve routes.", err=True)
        else:
            assert headless_session is not None
            page = headless_session.new_page()
            result = search_routes(page, departure, arrival)
            page.close()
            if result:
                display_routes(
                    result,
                    max_real_world=None if show_all else top_n,
                    show_flights=show_flights,
                )
            else:
                click.echo("Failed to retrieve routes.", err=True)


def do_atis_lookup(
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


def do_chart_lookup(
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
        page_num = None

        # For MIN charts (TAKEOFF MINIMUMS, ALTERNATE MINIMUMS), find the airport page
        if matched_chart.chart_code == "MIN":
            click.echo("  Searching for airport in document...")
            pdf_data = download_pdf(pdf_urls[0])
            if pdf_data:
                page_num = find_airport_page_in_min_chart(pdf_data, parsed.airport)
                if page_num:
                    click.echo(f"  Found {parsed.airport} at page {page_num}")
                else:
                    click.echo(f"  {parsed.airport} not found in document")

        if headless:
            # In headless mode, just output URL(s)
            for url in pdf_urls:
                click.echo(url)
            return pdf_urls[0]

        # Open the chart in browser
        return open_chart_pdf(
            pdf_urls=pdf_urls,
            airport=parsed.airport,
            chart_name=chart_name,
            rotation=rotation,
            session=visible_session,
            page_num=page_num,
        )

    # No unambiguous match found
    if matches:
        # Ambiguous match - show numbered disambiguation prompt
        display_chart_matches(matches)
        choice = prompt_chart_choice(matches)
        if choice:
            # Get all pages for the selected chart
            charts = fetch_charts_from_api(parsed.airport)
            all_pages = find_all_chart_pages(charts, choice)
            pdf_urls = [page.pdf_path for page in all_pages]
            page_num = None

            # For MIN charts, find the airport page
            if choice.chart_code == "MIN":
                click.echo("  Searching for airport in document...")
                pdf_data = download_pdf(pdf_urls[0])
                if pdf_data:
                    page_num = find_airport_page_in_min_chart(pdf_data, parsed.airport)
                    if page_num:
                        click.echo(f"  Found {parsed.airport} at page {page_num}")
                    else:
                        click.echo(f"  {parsed.airport} not found in document")

            if headless:
                for url in pdf_urls:
                    click.echo(url)
                return pdf_urls[0]

            return open_chart_pdf(
                pdf_urls=pdf_urls,
                airport=parsed.airport,
                chart_name=choice.chart_name,
                rotation=rotation,
                session=visible_session,
                page_num=page_num,
            )
    else:
        click.echo(f"No charts found for {parsed.airport}", err=True)

    return None


def do_charts_browse(
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
            wait_for_input_or_close(session, page=page)

        return pdf_url
    finally:
        if own_session:
            session.stop()


def do_position_lookup(
    query: str,
    browser: bool = False,
    no_cache: bool = False,
    headless_session: "BrowserSession | None" = None,
) -> None:
    """Handle position lookup.

    Args:
        query: Search query (matches name, TCP, callsign, or frequency)
        browser: If True, open positions page in visible browser
        no_cache: If True, bypass cache and fetch fresh data
        headless_session: Shared headless session (interactive mode)
    """
    click.echo(f"Searching positions: {query}...")

    if browser:
        # Browser mode: open positions page in visible browser
        own_session = headless_session is None
        if own_session:
            session = BrowserSession(headless=False)
            session.start()
        else:
            assert headless_session is not None
            session = headless_session.create_child_session(headless=False)

        try:
            page = session.new_page()
            success = open_positions_browser(page)
            if success:
                wait_for_input_or_close(
                    session, "Positions page open. Press Enter to close browser...", page
                )
            else:
                wait_for_input_or_close(
                    session,
                    "Failed to load positions page. Press Enter to close browser...",
                    page,
                )
        finally:
            if own_session:
                session.stop()
    else:
        # CLI mode: search and display
        own_session = headless_session is None
        if own_session:
            with BrowserSession(headless=True) as session:
                page = session.new_page()
                result = search_positions(page, query, use_cache=not no_cache)
                if result:
                    display_positions(result)
                else:
                    click.echo("Failed to retrieve positions.", err=True)
        else:
            assert headless_session is not None
            page = headless_session.new_page()
            result = search_positions(page, query, use_cache=not no_cache)
            page.close()
            if result:
                display_positions(result)
            else:
                click.echo("Failed to retrieve positions.", err=True)


def do_scratchpad_lookup(
    facility: str | None,
    list_facs: bool = False,
    no_cache: bool = False,
    headless_session: "BrowserSession | None" = None,
) -> None:
    """Handle scratchpad lookup.

    Args:
        facility: Facility name or code to look up
        list_facs: If True, list available facilities
        no_cache: If True, bypass cache and fetch fresh data
        headless_session: Shared headless session (interactive mode)
    """
    if list_facs:
        click.echo("Fetching available facilities...")

        own_session = headless_session is None
        if own_session:
            with BrowserSession(headless=True) as session:
                page = session.new_page()
                facilities = list_facilities(page, use_cache=not no_cache)
                if facilities:
                    display_scratchpad_facilities(facilities)
                else:
                    click.echo("Failed to retrieve facilities list.", err=True)
        else:
            assert headless_session is not None
            page = headless_session.new_page()
            facilities = list_facilities(page, use_cache=not no_cache)
            page.close()
            if facilities:
                display_scratchpad_facilities(facilities)
            else:
                click.echo("Failed to retrieve facilities list.", err=True)
        return

    if not facility:
        click.echo("Usage: scratchpad <facility>  (e.g., scratchpad OAK)")
        click.echo("       scratchpad --list      (list available facilities)")
        return

    click.echo(f"Fetching scratchpads for: {facility}...")

    own_session = headless_session is None
    if own_session:
        with BrowserSession(headless=True) as session:
            page = session.new_page()
            result = get_scratchpads(page, facility, use_cache=not no_cache)
            if result:
                display_scratchpads(result)
            else:
                click.echo("Failed to retrieve scratchpads.", err=True)
    else:
        assert headless_session is not None
        page = headless_session.new_page()
        result = get_scratchpads(page, facility, use_cache=not no_cache)
        page.close()
        if result:
            display_scratchpads(result)
        else:
            click.echo("Failed to retrieve scratchpads.", err=True)


def do_navaid_lookup(query: str) -> None:
    """Handle navaid lookup.

    Args:
        query: Search query (identifier like "FMG" or name like "MUSTANG")
    """
    result = search_navaids(query)
    display_navaids(result)


# Chart type aliases for list command
CHART_TYPE_ALIASES = {
    "SID": "DP",
    "APP": "IAP",
    "TAXI": "APD",
}

VALID_CHART_TYPES = {"DP", "STAR", "IAP", "APD"}


def do_list_charts(airport: str, chart_type: str | None = None) -> None:
    """List charts for an airport, optionally filtered by type.

    Args:
        airport: Airport code (e.g., "SFO", "OAK")
        chart_type: Optional chart type filter (DP, STAR, IAP, APD or aliases)
    """
    airport = airport.upper()

    # Normalize chart type
    filter_type = None
    if chart_type:
        chart_type = chart_type.upper()
        filter_type = CHART_TYPE_ALIASES.get(chart_type, chart_type)
        # Validate the chart type
        if filter_type not in VALID_CHART_TYPES:
            click.echo(
                f"Unknown chart type: {chart_type}. "
                f"Valid types: DP/SID, STAR, IAP/APP, APD/TAXI"
            )
            return

    if filter_type:
        click.echo(f"Fetching {filter_type} charts for {airport}...")
    else:
        click.echo(f"Fetching charts for {airport}...")

    charts_list = fetch_charts_from_api(airport)

    # Filter by chart type if specified
    if filter_type and charts_list:
        charts_list = [c for c in charts_list if c.chart_code == filter_type]

    if charts_list:
        if filter_type:
            click.echo(f"\n{filter_type} charts for {airport}:")
        else:
            click.echo(f"\nAvailable charts for {airport}:")
        click.echo("-" * 40)
        for chart_info in charts_list:
            if filter_type:
                # When filtered, don't show the type prefix
                click.echo(f"  {chart_info.chart_name}")
            else:
                type_str = chart_info.chart_code if chart_info.chart_code else "?"
                click.echo(f"  [{type_str:<4}] {chart_info.chart_name}")
    else:
        if filter_type:
            click.echo(f"No {filter_type} charts found for {airport}")
        else:
            click.echo(f"No charts found for {airport}")
