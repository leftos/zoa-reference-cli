"""Scratchpad code lookup functionality for ZOA Reference Tool."""

import json
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout

from zoa_ref.config import CACHE_DIR, CACHE_TTL_SECONDS

SCRATCHPADS_URL = "https://reference.oakartcc.org/scratchpads"


@dataclass
class Scratchpad:
    """Scratchpad code entry."""

    code: str  # Scratchpad code
    meaning: str  # What the code means


@dataclass
class ScratchpadResult:
    """Result of a scratchpad lookup."""

    facility: str
    scratchpads: list[Scratchpad]


@dataclass
class ScratchpadFacility:
    """Available facility for scratchpad lookup."""

    name: str  # Display name in dropdown
    value: str  # Value attribute for selection


# --- Caching ---


def _get_scratchpad_cache_path(facility: str) -> Path:
    """Get the cache file path for a facility's scratchpads."""
    safe_name = facility.lower().replace(" ", "_").replace("/", "_")
    return CACHE_DIR / "scratchpads" / f"{safe_name}.json"


def _get_facilities_cache_path() -> Path:
    """Get the cache file path for available facilities."""
    return CACHE_DIR / "scratchpads" / "_facilities.json"


def _load_scratchpad_cache(facility: str) -> list[Scratchpad] | None:
    """Load cached scratchpads for a facility if valid."""
    cache_path = _get_scratchpad_cache_path(facility)
    if not cache_path.exists():
        return None

    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Check TTL
        if time.time() - data.get("timestamp", 0) > CACHE_TTL_SECONDS:
            return None

        return [Scratchpad(**s) for s in data.get("scratchpads", [])]
    except (json.JSONDecodeError, OSError, TypeError):
        return None


def _save_scratchpad_cache(facility: str, scratchpads: list[Scratchpad]) -> None:
    """Save scratchpads to cache."""
    cache_path = _get_scratchpad_cache_path(facility)
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    data = {
        "timestamp": time.time(),
        "facility": facility,
        "scratchpads": [asdict(s) for s in scratchpads],
    }

    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except OSError:
        pass


def _load_facilities_cache() -> list[ScratchpadFacility] | None:
    """Load cached facilities list if valid."""
    cache_path = _get_facilities_cache_path()
    if not cache_path.exists():
        return None

    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Check TTL
        if time.time() - data.get("timestamp", 0) > CACHE_TTL_SECONDS:
            return None

        return [ScratchpadFacility(**f) for f in data.get("facilities", [])]
    except (json.JSONDecodeError, OSError, TypeError):
        return None


def _save_facilities_cache(facilities: list[ScratchpadFacility]) -> None:
    """Save facilities list to cache."""
    cache_path = _get_facilities_cache_path()
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    data = {
        "timestamp": time.time(),
        "facilities": [asdict(f) for f in facilities],
    }

    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except OSError:
        pass


# --- Page navigation and scraping ---


def _navigate_to_scratchpads_page(page: Page, timeout: int = 30000) -> bool:
    """Navigate to scratchpads page and wait for dropdown to load."""
    try:
        page.goto(SCRATCHPADS_URL, wait_until="networkidle", timeout=timeout)
        # Wait for dropdown to appear
        page.wait_for_selector("select", timeout=10000)
        # Extra wait for Blazor rendering
        page.wait_for_timeout(1500)
        return True
    except PlaywrightTimeout:
        return False


def _get_available_facilities(page: Page) -> list[ScratchpadFacility]:
    """Get list of available facilities from dropdown."""
    facilities = []
    try:
        # Find the select element
        select = page.locator("select").first
        options = select.locator("option").all()

        for option in options:
            value = option.get_attribute("value") or ""
            text = option.inner_text().strip()
            # Skip empty/placeholder options
            if value and text and text != "Select a facility":
                facilities.append(ScratchpadFacility(name=text, value=value))
    except Exception:
        pass
    return facilities


def _find_facility_value(
    facilities: list[ScratchpadFacility], query: str
) -> str | None:
    """Find facility value by matching query against name or value (case-insensitive)."""
    query_lower = query.lower()

    # Try exact match first
    for f in facilities:
        if f.value.lower() == query_lower or f.name.lower() == query_lower:
            return f.value

    # Try partial match on name
    for f in facilities:
        if query_lower in f.name.lower():
            return f.value

    # Try partial match on value
    for f in facilities:
        if query_lower in f.value.lower():
            return f.value

    return None


def _select_facility_and_scrape(page: Page, facility_value: str) -> list[Scratchpad]:
    """Select facility from dropdown and scrape the resulting table."""
    scratchpads = []
    try:
        # Select the facility from dropdown
        select = page.locator("select").first
        select.select_option(value=facility_value)

        # Wait for table to populate
        page.wait_for_timeout(2000)

        # Find the table (should appear after selection)
        table = page.locator("table").first
        rows = table.locator("tr").all()

        # Skip header row
        for row in rows[1:]:
            cells = row.locator("td").all()
            if len(cells) >= 2:
                scratchpads.append(
                    Scratchpad(
                        code=cells[0].inner_text().strip(),
                        meaning=cells[1].inner_text().strip(),
                    )
                )
    except Exception:
        pass
    return scratchpads


# --- Public API ---


def list_facilities(
    page: Page | None, timeout: int = 30000, use_cache: bool = True
) -> list[ScratchpadFacility] | None:
    """
    List available facilities for scratchpad lookup.

    Args:
        page: Playwright page (can be None if cache hit expected)
        timeout: Page navigation timeout
        use_cache: Whether to use cached results

    Returns list of ScratchpadFacility or None if failed.
    """
    # Check cache first
    if use_cache:
        cached = _load_facilities_cache()
        if cached:
            return cached

    # Need page for fresh lookup
    if page is None:
        return None

    if not _navigate_to_scratchpads_page(page, timeout):
        return None

    facilities = _get_available_facilities(page)

    # Cache results
    if use_cache and facilities:
        _save_facilities_cache(facilities)

    return facilities


def get_scratchpads(
    page: Page | None, facility: str, timeout: int = 30000, use_cache: bool = True
) -> ScratchpadResult | None:
    """
    Get scratchpads for a specific facility.

    Args:
        page: Playwright page (can be None if cache hit expected)
        facility: Facility name or code to look up
        timeout: Page navigation timeout
        use_cache: Whether to use cached results

    Returns ScratchpadResult or None if failed.
    """
    # Check cache first (using the query as cache key)
    if use_cache:
        cached = _load_scratchpad_cache(facility)
        if cached:
            return ScratchpadResult(facility=facility, scratchpads=cached)

    # Need page for fresh lookup
    if page is None:
        return None

    if not _navigate_to_scratchpads_page(page, timeout):
        return None

    # Get facilities list to find the correct value
    facilities = _get_available_facilities(page)
    facility_value = _find_facility_value(facilities, facility)

    if not facility_value:
        return ScratchpadResult(facility=facility, scratchpads=[])

    scratchpads = _select_facility_and_scrape(page, facility_value)

    # Cache results
    if use_cache and scratchpads:
        _save_scratchpad_cache(facility, scratchpads)

    return ScratchpadResult(facility=facility, scratchpads=scratchpads)


def open_scratchpads_browser(page: Page, timeout: int = 30000) -> bool:
    """
    Navigate to scratchpads page and leave browser open.

    Used for --browser mode where user wants to manually browse scratchpads.
    Returns True if navigation was successful.
    """
    return _navigate_to_scratchpads_page(page, timeout)
