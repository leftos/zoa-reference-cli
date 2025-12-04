"""ATIS lookup functionality for ZOA Reference Tool."""

from dataclasses import dataclass
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout


ATIS_URL = "https://reference.oakartcc.org/atis"
ATIS_AIRPORTS = ["SFO", "SJC", "RNO", "OAK", "SMF"]


@dataclass
class AtisInfo:
    """ATIS information for an airport."""
    airport: str
    raw_text: str


@dataclass
class AtisResult:
    """Result of an ATIS fetch."""
    atis_list: list[AtisInfo]


def _navigate_to_atis_page(page: Page, timeout: int = 30000) -> bool:
    """Navigate to ATIS page and wait for it to load."""
    try:
        page.goto(ATIS_URL, wait_until="networkidle", timeout=timeout)
        # Wait for content to load - look for any ATIS text
        page.wait_for_timeout(2000)  # Allow Blazor to render
        return True
    except PlaywrightTimeout:
        return False


def _scrape_atis_for_airport(page: Page, airport: str) -> AtisInfo | None:
    """Scrape ATIS for a specific airport."""
    try:
        airport = airport.upper()

        # Each ATIS block is a div.flex.mb-2 containing airport code and text
        # Find the div containing this airport's code
        atis_blocks = page.locator("div.flex.mb-2").all()

        for block in atis_blocks:
            block_text = block.inner_text().strip()
            # Check if this block starts with our airport code
            lines = block_text.split('\n')
            if lines and lines[0].strip() == airport:
                return AtisInfo(
                    airport=airport,
                    raw_text=block_text
                )

        return None
    except Exception:
        return None


def _scrape_all_atis(page: Page) -> list[AtisInfo]:
    """Scrape ATIS for all airports."""
    atis_list = []
    try:
        # Each ATIS block is a div.flex.mb-2
        atis_blocks = page.locator("div.flex.mb-2").all()

        for block in atis_blocks:
            try:
                block_text = block.inner_text().strip()
                if not block_text:
                    continue

                # First line should be the airport code
                lines = block_text.split('\n')
                if not lines:
                    continue

                first_line = lines[0].strip()
                if first_line in ATIS_AIRPORTS:
                    atis_list.append(AtisInfo(
                        airport=first_line,
                        raw_text=block_text
                    ))
            except Exception:
                continue

    except Exception:
        pass

    return atis_list


def fetch_atis(page: Page, airport: str, timeout: int = 30000) -> AtisInfo | None:
    """
    Fetch ATIS for a specific airport.

    Args:
        page: Playwright page
        airport: Airport code (e.g., "SFO")
        timeout: Page navigation timeout

    Returns AtisInfo or None if failed.
    """
    airport = airport.upper()

    if airport not in ATIS_AIRPORTS:
        return None

    if not _navigate_to_atis_page(page, timeout):
        return None

    return _scrape_atis_for_airport(page, airport)


def fetch_all_atis(page: Page, timeout: int = 30000) -> AtisResult | None:
    """
    Fetch ATIS for all airports.

    Args:
        page: Playwright page
        timeout: Page navigation timeout

    Returns AtisResult or None if failed.
    """
    if not _navigate_to_atis_page(page, timeout):
        return None

    atis_list = _scrape_all_atis(page)
    return AtisResult(atis_list=atis_list)


def open_atis_browser(page: Page, timeout: int = 30000) -> bool:
    """
    Navigate to ATIS page and leave browser open.

    Used for --browser mode where user wants to view ATIS page.
    Returns True if navigation was successful.
    """
    return _navigate_to_atis_page(page, timeout)
