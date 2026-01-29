"""Route lookup functionality for ZOA Reference Tool."""

from dataclasses import dataclass
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout


ROUTES_URL = "https://reference.oakartcc.org/routes"


@dataclass
class TecAarAdrRoute:
    """TEC/AAR/ADR route entry."""

    dep_runway: str
    arr_runway: str
    types: str
    route: str


@dataclass
class LoaRule:
    """LOA (Letter of Agreement) rule entry."""

    route: str
    rnav: str
    notes: str


@dataclass
class RealWorldRoute:
    """Real-world route entry from historical data."""

    frequency: str
    route: str
    altitude: str


@dataclass
class RecentFlight:
    """Recent flight entry."""

    callsign: str
    aircraft_type: str
    route: str
    altitude: str


@dataclass
class RouteSearchResult:
    """Complete result of a route search."""

    departure: str
    arrival: str
    tec_aar_adr: list[TecAarAdrRoute]
    loa_rules: list[LoaRule]
    real_world: list[RealWorldRoute]
    recent_flights: list[RecentFlight]


def _fill_and_search(
    page: Page, departure: str, arrival: str, timeout: int = 30000
) -> bool:
    """
    Navigate to routes page, fill the search form, and click search.

    Returns True if search was successful.
    """
    page.goto(ROUTES_URL, wait_until="networkidle", timeout=timeout)

    # Wait for departure input to appear
    try:
        page.wait_for_selector("#departureInput", timeout=10000)
    except PlaywrightTimeout:
        print("Warning: Page load timeout, departure input not found")
        return False

    # Fill departure and arrival
    page.locator("#departureInput").fill(departure)
    page.locator("input[placeholder='Arrival ID']").fill(arrival)

    # Click search button
    page.locator("button:has-text('Search Routes')").click()

    # Wait for search to complete by waiting for network to settle
    # We can't wait for a table because no table is rendered if there are no results
    try:
        page.wait_for_load_state("networkidle", timeout=10000)
    except PlaywrightTimeout:
        print("Warning: Timeout waiting for route search to complete")
        return False

    return True


def _find_tables_after_h1(page: Page, h1_text: str) -> list:
    """
    Find all tables that follow an H1 with the given text.

    Returns tables between this H1 and the next H1 (or end of content).
    """
    try:
        h1 = page.locator(f"h1:has-text('{h1_text}')").first
        if h1.count() == 0:
            return []

        # Get all following siblings that are tables, stopping at next H1
        tables = []
        siblings = h1.locator("xpath=following-sibling::*")
        for i in range(siblings.count()):
            sibling = siblings.nth(i)
            tag = sibling.evaluate("el => el.tagName")
            if tag == "H1":
                break  # Stop at next H1
            if tag == "TABLE":
                tables.append(sibling)

        return tables
    except Exception:
        return []


def _scrape_tec_aar_adr_table(page: Page) -> list[TecAarAdrRoute]:
    """Scrape the TEC/AAR/ADR Routes table (under 'TEC/AAR/ADR Routes' H1)."""
    routes = []

    try:
        tables = _find_tables_after_h1(page, "TEC/AAR/ADR")
        if not tables:
            return routes

        table = tables[0]  # First table under this H1
        rows = table.locator("tr").all()

        # Skip header row
        for row in rows[1:]:
            cells = row.locator("td").all()
            if len(cells) >= 4:
                routes.append(
                    TecAarAdrRoute(
                        dep_runway=cells[0].inner_text().strip(),
                        arr_runway=cells[1].inner_text().strip(),
                        types=cells[2].inner_text().strip(),
                        route=cells[3].inner_text().strip(),
                    )
                )
    except Exception:
        pass

    return routes


def _scrape_loa_rules_table(page: Page) -> list[LoaRule]:
    """Scrape the LOA Rules table (under 'LOA Rules' H1)."""
    rules = []

    try:
        tables = _find_tables_after_h1(page, "LOA Rules")
        if not tables:
            return rules

        table = tables[0]  # First table under this H1
        rows = table.locator("tr").all()

        # Skip header row
        for row in rows[1:]:
            cells = row.locator("td").all()
            if len(cells) >= 3:
                rules.append(
                    LoaRule(
                        route=cells[0].inner_text().strip(),
                        rnav=cells[1].inner_text().strip(),
                        notes=cells[2].inner_text().strip(),
                    )
                )
    except Exception:
        pass

    return rules


def _scrape_real_world_and_recent_flights(
    page: Page,
) -> tuple[list[RealWorldRoute], list[RecentFlight]]:
    """
    Scrape both Real World Routes and Recent Flights tables.

    Both are under the 'Real World Routes' H1:
    - First table: Real World Routes
    - Second table: Recent Flights
    """
    routes = []
    flights = []

    try:
        tables = _find_tables_after_h1(page, "Real World Routes")

        # First table: Real World Routes
        if len(tables) >= 1:
            table = tables[0]
            rows = table.locator("tr").all()
            for row in rows[1:]:
                cells = row.locator("td").all()
                if len(cells) >= 3:
                    routes.append(
                        RealWorldRoute(
                            frequency=cells[0].inner_text().strip(),
                            route=cells[1].inner_text().strip(),
                            altitude=cells[2].inner_text().strip(),
                        )
                    )

        # Second table: Recent Flights
        if len(tables) >= 2:
            table = tables[1]
            rows = table.locator("tr").all()
            for row in rows[1:]:
                cells = row.locator("td").all()
                if len(cells) >= 4:
                    flights.append(
                        RecentFlight(
                            callsign=cells[0].inner_text().strip(),
                            aircraft_type=cells[1].inner_text().strip(),
                            route=cells[2].inner_text().strip(),
                            altitude=cells[3].inner_text().strip(),
                        )
                    )

    except Exception:
        pass

    return routes, flights


def search_routes(
    page: Page, departure: str, arrival: str, timeout: int = 30000
) -> RouteSearchResult | None:
    """
    Search for routes between two airports and scrape all results.

    Returns RouteSearchResult containing all scraped data, or None if search failed.
    """
    if not _fill_and_search(page, departure, arrival, timeout):
        return None

    # Small delay to ensure all tables are populated
    page.wait_for_timeout(500)

    # Scrape Real World Routes and Recent Flights together (both under same H1)
    real_world, recent_flights = _scrape_real_world_and_recent_flights(page)

    return RouteSearchResult(
        departure=departure,
        arrival=arrival,
        tec_aar_adr=_scrape_tec_aar_adr_table(page),
        loa_rules=_scrape_loa_rules_table(page),
        real_world=real_world,
        recent_flights=recent_flights,
    )


def open_routes_browser(
    page: Page, departure: str, arrival: str, timeout: int = 30000
) -> bool:
    """
    Navigate to routes page, fill the search form, and leave browser open.

    Used for --browser mode where user wants to manually browse results.
    Returns True if navigation was successful.
    """
    return _fill_and_search(page, departure, arrival, timeout)
