"""Browser automation module using Playwright."""

from playwright.sync_api import sync_playwright, Browser, Page, Playwright
from contextlib import contextmanager


class BrowserSession:
    """Manages a Playwright browser session."""

    def __init__(self, headless: bool = False):
        self.headless = headless
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None

    def start(self) -> None:
        """Start the browser session."""
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=self.headless)

    def stop(self) -> None:
        """Stop the browser session."""
        if self._browser:
            self._browser.close()
            self._browser = None
        if self._playwright:
            self._playwright.stop()
            self._playwright = None

    def new_page(self) -> Page:
        """Create a new browser page."""
        if not self._browser:
            raise RuntimeError("Browser not started. Call start() first.")
        return self._browser.new_page()

    def __enter__(self) -> "BrowserSession":
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.stop()


@contextmanager
def browser_session(headless: bool = False):
    """Context manager for a browser session."""
    session = BrowserSession(headless=headless)
    session.start()
    try:
        yield session
    finally:
        session.stop()
