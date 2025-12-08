"""ATC position lookup functionality for ZOA Reference Tool."""

import json
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout


POSITIONS_URL = "https://reference.oakartcc.org/positions"

# Cache configuration (reuse same directory structure as ICAO)
CACHE_DIR = Path.home() / ".zoa-ref" / "cache"
CACHE_TTL_SECONDS = 7 * 24 * 60 * 60  # 7 days - position data rarely changes


@dataclass
class Position:
    """ATC position entry."""

    name: str  # Position name (e.g., "Area A Morgan")
    tcp: str  # STARS TCP code
    callsign: str  # VATSIM callsign (e.g., "OAK_14_CTR")
    radio_name: str  # Radio callsign (e.g., "Oakland Center")
    frequency: str  # Frequency (e.g., "134.550")


@dataclass
class PositionSearchResult:
    """Result of a position search."""

    query: str
    results: list[Position]


# --- Caching ---


def _get_positions_cache_path() -> Path:
    """Get the cache file path for all positions."""
    return CACHE_DIR / "positions" / "all.json"


def _load_positions_cache() -> list[Position] | None:
    """Load cached positions if valid, return None if expired or not found."""
    cache_path = _get_positions_cache_path()
    if not cache_path.exists():
        return None

    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Check TTL
        if time.time() - data.get("timestamp", 0) > CACHE_TTL_SECONDS:
            return None

        return [Position(**p) for p in data.get("positions", [])]
    except (json.JSONDecodeError, OSError, TypeError):
        return None


def _save_positions_cache(positions: list[Position]) -> None:
    """Save positions to cache."""
    cache_path = _get_positions_cache_path()
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    data = {
        "timestamp": time.time(),
        "positions": [asdict(p) for p in positions],
    }

    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except OSError:
        pass  # Silently fail if we can't cache


# --- Page navigation and scraping ---


def _navigate_to_positions_page(page: Page, timeout: int = 30000) -> bool:
    """Navigate to positions page and wait for table to load."""
    try:
        page.goto(POSITIONS_URL, wait_until="networkidle", timeout=timeout)
        # Wait for table to appear
        page.wait_for_selector("table", timeout=10000)
        # Extra wait for Blazor rendering
        page.wait_for_timeout(1500)
        return True
    except PlaywrightTimeout:
        return False


def _scrape_positions_table(page: Page) -> list[Position]:
    """Scrape all positions from the table."""
    positions = []
    try:
        # Find all tables on the page
        tables = page.locator("table").all()

        for table in tables:
            rows = table.locator("tr").all()

            # Skip header row
            for row in rows[1:]:
                cells = row.locator("td").all()
                if len(cells) >= 5:
                    positions.append(
                        Position(
                            name=cells[0].inner_text().strip(),
                            tcp=cells[1].inner_text().strip(),
                            callsign=cells[2].inner_text().strip(),
                            radio_name=cells[3].inner_text().strip(),
                            frequency=cells[4].inner_text().strip(),
                        )
                    )
    except Exception:
        pass
    return positions


def _filter_positions(positions: list[Position], query: str) -> list[Position]:
    """Filter positions by query matching any field (case-insensitive)."""
    query_lower = query.lower()
    return [
        p
        for p in positions
        if query_lower in p.name.lower()
        or query_lower in p.tcp.lower()
        or query_lower in p.callsign.lower()
        or query_lower in p.radio_name.lower()
        or query_lower in p.frequency.lower()
    ]


# --- Public API ---


def fetch_all_positions(
    page: Page | None, timeout: int = 30000, use_cache: bool = True
) -> list[Position] | None:
    """
    Fetch all positions (from cache or by scraping).

    Args:
        page: Playwright page (can be None if cache hit expected)
        timeout: Page navigation timeout
        use_cache: Whether to use cached results

    Returns list of Position or None if failed.
    """
    # Check cache first
    if use_cache:
        cached = _load_positions_cache()
        if cached:
            return cached

    # Need page for fresh lookup
    if page is None:
        return None

    if not _navigate_to_positions_page(page, timeout):
        return None

    positions = _scrape_positions_table(page)

    # Cache results
    if use_cache and positions:
        _save_positions_cache(positions)

    return positions


def search_positions(
    page: Page | None, query: str, timeout: int = 30000, use_cache: bool = True
) -> PositionSearchResult | None:
    """
    Search for positions by any field (name, TCP, callsign, frequency).

    Args:
        page: Playwright page (can be None if cache hit expected)
        query: Search query
        timeout: Page navigation timeout
        use_cache: Whether to use cached results

    Returns PositionSearchResult or None if failed.
    """
    positions = fetch_all_positions(page, timeout, use_cache)
    if positions is None:
        return None

    filtered = _filter_positions(positions, query)
    return PositionSearchResult(query=query, results=filtered)


def open_positions_browser(page: Page, timeout: int = 30000) -> bool:
    """
    Navigate to positions page and leave browser open.

    Used for --browser mode where user wants to manually browse positions.
    Returns True if navigation was successful.
    """
    return _navigate_to_positions_page(page, timeout)
