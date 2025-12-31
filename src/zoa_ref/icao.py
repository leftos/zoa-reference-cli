"""ICAO code lookup functionality for ZOA Reference Tool."""

import json
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout

from zoa_ref.config import CACHE_DIR, CACHE_TTL_SECONDS

CODES_URL = "https://reference.oakartcc.org/codes"


@dataclass
class AirlineCode:
    """Airline ICAO code entry."""

    icao_id: str
    telephony: str
    name: str
    country: str


@dataclass
class AirportCode:
    """Airport code entry."""

    icao_id: str
    local_id: str
    name: str


@dataclass
class AircraftCode:
    """Aircraft type designator entry."""

    type_designator: str
    manufacturer: str
    model: str
    engine: str
    faa_weight: str
    cwt: str
    srs: str
    lahso: str


@dataclass
class AirlineSearchResult:
    """Result of an airline code search."""

    query: str
    results: list[AirlineCode]


@dataclass
class AirportSearchResult:
    """Result of an airport code search."""

    query: str
    results: list[AirportCode]


@dataclass
class AircraftSearchResult:
    """Result of an aircraft code search."""

    query: str
    results: list[AircraftCode]


# --- Caching ---


def _get_cache_path(cache_type: str, query: str) -> Path:
    """Get the cache file path for a given query."""
    safe_query = query.lower().replace(" ", "_").replace("/", "_")
    return CACHE_DIR / cache_type / f"{safe_query}.json"


def _load_from_cache(cache_type: str, query: str) -> dict | None:
    """Load cached result if valid, return None if expired or not found."""
    cache_path = _get_cache_path(cache_type, query)
    if not cache_path.exists():
        return None

    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Check TTL
        if time.time() - data.get("timestamp", 0) > CACHE_TTL_SECONDS:
            return None

        return data
    except (json.JSONDecodeError, OSError):
        return None


def _save_to_cache(cache_type: str, query: str, results: list[dict]) -> None:
    """Save results to cache."""
    cache_path = _get_cache_path(cache_type, query)
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    data = {"timestamp": time.time(), "query": query, "results": results}

    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except OSError:
        pass  # Silently fail if we can't cache


def clear_cache() -> int:
    """Clear all cached ICAO data. Returns number of files deleted."""
    count = 0
    if CACHE_DIR.exists():
        for cache_file in CACHE_DIR.rglob("*.json"):
            try:
                cache_file.unlink()
                count += 1
            except OSError:
                pass
    return count


# --- Page navigation and scraping ---


def _navigate_to_codes_page(page: Page, timeout: int = 30000) -> bool:
    """Navigate to codes page and wait for it to load."""
    try:
        page.goto(CODES_URL, wait_until="networkidle", timeout=timeout)
        # Wait for first input to appear as indicator page is loaded
        page.wait_for_selector('input[placeholder="Airline 3-letter"]', timeout=10000)
        return True
    except PlaywrightTimeout:
        return False


def _scrape_airline_table(page: Page) -> list[AirlineCode]:
    """Scrape the airline results table."""
    airlines = []
    try:
        table = page.locator("table").first
        rows = table.locator("tr").all()

        # Skip header row
        for row in rows[1:]:
            cells = row.locator("td").all()
            if len(cells) >= 4:
                airlines.append(
                    AirlineCode(
                        icao_id=cells[0].inner_text().strip(),
                        telephony=cells[1].inner_text().strip(),
                        name=cells[2].inner_text().strip(),
                        country=cells[3].inner_text().strip(),
                    )
                )
    except Exception:
        pass
    return airlines


def _scrape_airport_table(page: Page) -> list[AirportCode]:
    """Scrape the airport results table."""
    airports = []
    try:
        table = page.locator("table").nth(1)
        rows = table.locator("tr").all()

        # Skip header row
        for row in rows[1:]:
            cells = row.locator("td").all()
            if len(cells) >= 3:
                airports.append(
                    AirportCode(
                        icao_id=cells[0].inner_text().strip(),
                        local_id=cells[1].inner_text().strip(),
                        name=cells[2].inner_text().strip(),
                    )
                )
    except Exception:
        pass
    return airports


def _scrape_aircraft_table(page: Page) -> list[AircraftCode]:
    """Scrape the aircraft results table."""
    aircraft = []
    try:
        table = page.locator("table").nth(2)
        rows = table.locator("tr").all()

        # Skip header row
        for row in rows[1:]:
            cells = row.locator("td").all()
            if len(cells) >= 8:
                aircraft.append(
                    AircraftCode(
                        type_designator=cells[0].inner_text().strip(),
                        manufacturer=cells[1].inner_text().strip(),
                        model=cells[2].inner_text().strip(),
                        engine=cells[3].inner_text().strip(),
                        faa_weight=cells[4].inner_text().strip(),
                        cwt=cells[5].inner_text().strip(),
                        srs=cells[6].inner_text().strip(),
                        lahso=cells[7].inner_text().strip(),
                    )
                )
    except Exception:
        pass
    return aircraft


def _search_airlines(page: Page, query: str) -> list[AirlineCode]:
    """Fill airline search and scrape results."""
    try:
        # Fill input and click search
        page.locator('input[placeholder="Airline 3-letter"]').fill(query)
        page.locator('button:has-text("Search Airlines")').click()

        # Wait for Blazor to process and return results
        page.wait_for_timeout(1500)

        return _scrape_airline_table(page)
    except Exception:
        return []


def _search_airports(page: Page, query: str) -> list[AirportCode]:
    """Fill airport search and scrape results."""
    try:
        # Fill input and click search
        page.locator('input[placeholder="Airport code"]').fill(query)
        page.locator('button:has-text("Search Airports")').click()

        # Wait for Blazor to process and return results
        page.wait_for_timeout(1500)

        return _scrape_airport_table(page)
    except Exception:
        return []


def _search_aircraft(page: Page, query: str) -> list[AircraftCode]:
    """Fill aircraft search and scrape results."""
    try:
        # Fill input and click search
        page.locator('input[placeholder="Aircraft code / name"]').fill(query)
        page.locator('button:has-text("Search Aircraft")').click()

        # Wait for Blazor to process and return results
        page.wait_for_timeout(1500)

        return _scrape_aircraft_table(page)
    except Exception:
        return []


def _filter_aircraft_by_terms(
    aircraft: list[AircraftCode], terms: list[str]
) -> list[AircraftCode]:
    """Filter aircraft to only include those matching all search terms (case-insensitive)."""
    if not terms:
        return aircraft

    filtered = []
    for ac in aircraft:
        # Combine manufacturer and model for searching
        combined = f"{ac.manufacturer} {ac.model}".lower()
        # Check if all terms appear in the combined text
        if all(term.lower() in combined for term in terms):
            filtered.append(ac)

    return filtered


def _search_aircraft_multi_term(page: Page, query: str) -> list[AircraftCode]:
    """
    Search aircraft with multi-term support.

    If the query contains multiple words and returns no results, try searching
    individual terms and filter to matches containing all terms.
    """
    # Try the original query first
    results = _search_aircraft(page, query)
    if results:
        return results

    # If no results and query has multiple words, try word-by-word search
    terms = query.strip().split()
    if len(terms) <= 1:
        return []

    # Search with each term and combine results
    # Use composite key (type + manufacturer + model) to avoid losing entries
    # when the same type has multiple manufacturer/model combinations
    all_results: dict[tuple[str, str, str], AircraftCode] = {}

    for term in terms:
        term_results = _search_aircraft(page, term)
        for ac in term_results:
            key = (ac.type_designator, ac.manufacturer, ac.model)
            all_results[key] = ac

    # Filter combined results to only include aircraft matching ALL terms
    combined = list(all_results.values())
    return _filter_aircraft_by_terms(combined, terms)


# --- Persistent page for interactive mode ---


class CodesPage:
    """
    Wrapper for a page that stays on the codes URL for fast repeated lookups.

    Usage:
        codes_page = CodesPage(browser_session)
        codes_page.ensure_ready()  # Navigate once
        result = codes_page.search_airline("UAL")  # Fast - no navigation
        result = codes_page.search_aircraft("B738")  # Fast - reuses page
    """

    def __init__(self, session):
        """Initialize with a BrowserSession (headless recommended)."""
        self._session = session
        self._page = None
        self._ready = False

    def ensure_ready(self, timeout: int = 30000) -> bool:
        """Ensure page is created and navigated to codes URL."""
        if self._ready and self._page:
            return True

        try:
            if not self._page:
                self._page = self._session.new_page()

            self._page.goto(CODES_URL, wait_until="networkidle", timeout=timeout)
            self._page.wait_for_selector(
                'input[placeholder="Airline 3-letter"]', timeout=10000
            )
            self._ready = True
            return True
        except Exception:
            self._ready = False
            return False

    def search_airline(
        self, query: str, use_cache: bool = True
    ) -> AirlineSearchResult | None:
        """Search airlines on the persistent page."""
        # Check cache first
        if use_cache:
            cached = _load_from_cache("airline", query)
            if cached:
                results = [AirlineCode(**r) for r in cached["results"]]
                return AirlineSearchResult(query=query, results=results)

        if not self._ready or self._page is None:
            return None

        results = _search_airlines(self._page, query)

        if use_cache and results:
            _save_to_cache("airline", query, [asdict(r) for r in results])

        return AirlineSearchResult(query=query, results=results)

    def search_airport(
        self, query: str, use_cache: bool = True
    ) -> AirportSearchResult | None:
        """Search airports on the persistent page."""
        # Check cache first
        if use_cache:
            cached = _load_from_cache("airport", query)
            if cached:
                results = [AirportCode(**r) for r in cached["results"]]
                return AirportSearchResult(query=query, results=results)

        if not self._ready or self._page is None:
            return None

        results = _search_airports(self._page, query)

        if use_cache and results:
            _save_to_cache("airport", query, [asdict(r) for r in results])

        return AirportSearchResult(query=query, results=results)

    def search_aircraft(
        self, query: str, use_cache: bool = True
    ) -> AircraftSearchResult | None:
        """Search aircraft on the persistent page."""
        # Check cache first
        if use_cache:
            cached = _load_from_cache("aircraft", query)
            if cached:
                results = [AircraftCode(**r) for r in cached["results"]]
                return AircraftSearchResult(query=query, results=results)

        if not self._ready or self._page is None:
            return None

        results = _search_aircraft_multi_term(self._page, query)

        if use_cache and results:
            _save_to_cache("aircraft", query, [asdict(r) for r in results])

        return AircraftSearchResult(query=query, results=results)

    def close(self):
        """Close the page."""
        if self._page:
            try:
                self._page.close()
            except Exception:
                pass
            self._page = None
            self._ready = False


# --- Public search functions ---


def search_airline(
    page: Page | None, query: str, timeout: int = 30000, use_cache: bool = True
) -> AirlineSearchResult | None:
    """
    Search for an airline by ICAO ID, telephony, name, or country.

    Args:
        page: Playwright page (can be None if cache hit expected)
        query: Search query
        timeout: Page navigation timeout
        use_cache: Whether to use cached results

    Returns AirlineSearchResult or None if failed.
    """
    # Check cache first
    if use_cache:
        cached = _load_from_cache("airline", query)
        if cached:
            results = [AirlineCode(**r) for r in cached["results"]]
            return AirlineSearchResult(query=query, results=results)

    # Need page for fresh lookup
    if page is None:
        return None

    if not _navigate_to_codes_page(page, timeout):
        return None

    results = _search_airlines(page, query)

    # Cache results
    if use_cache and results:
        _save_to_cache("airline", query, [asdict(r) for r in results])

    return AirlineSearchResult(query=query, results=results)


def search_airport_code(
    page: Page | None, query: str, timeout: int = 30000, use_cache: bool = True
) -> AirportSearchResult | None:
    """
    Search for an airport by ICAO ID, local ID, or name.

    Args:
        page: Playwright page (can be None if cache hit expected)
        query: Search query
        timeout: Page navigation timeout
        use_cache: Whether to use cached results

    Returns AirportSearchResult or None if failed.
    """
    # Check cache first
    if use_cache:
        cached = _load_from_cache("airport", query)
        if cached:
            results = [AirportCode(**r) for r in cached["results"]]
            return AirportSearchResult(query=query, results=results)

    # Need page for fresh lookup
    if page is None:
        return None

    if not _navigate_to_codes_page(page, timeout):
        return None

    results = _search_airports(page, query)

    # Cache results
    if use_cache and results:
        _save_to_cache("airport", query, [asdict(r) for r in results])

    return AirportSearchResult(query=query, results=results)


def search_aircraft(
    page: Page | None, query: str, timeout: int = 30000, use_cache: bool = True
) -> AircraftSearchResult | None:
    """
    Search for an aircraft by type designator or manufacturer/model.

    Supports multi-term searches (e.g., "piper comanche") by searching each term
    individually and filtering results that match all terms.

    Args:
        page: Playwright page (can be None if cache hit expected)
        query: Search query
        timeout: Page navigation timeout
        use_cache: Whether to use cached results

    Returns AircraftSearchResult or None if failed.
    """
    # Check cache first
    if use_cache:
        cached = _load_from_cache("aircraft", query)
        if cached:
            results = [AircraftCode(**r) for r in cached["results"]]
            return AircraftSearchResult(query=query, results=results)

    # Need page for fresh lookup
    if page is None:
        return None

    if not _navigate_to_codes_page(page, timeout):
        return None

    results = _search_aircraft_multi_term(page, query)

    # Cache results
    if use_cache and results:
        _save_to_cache("aircraft", query, [asdict(r) for r in results])

    return AircraftSearchResult(query=query, results=results)


def open_codes_browser(page: Page, timeout: int = 30000) -> bool:
    """
    Navigate to codes page and leave browser open.

    Used for --browser mode where user wants to manually browse codes.
    Returns True if navigation was successful.
    """
    return _navigate_to_codes_page(page, timeout)
