"""Browser automation module using Playwright."""

import ctypes
from playwright.sync_api import sync_playwright, Browser, Page, Playwright
from contextlib import contextmanager

# Approximate taskbar height on Windows
TASKBAR_HEIGHT = 48
# Aspect ratio for chart viewing (width:height)
CHART_ASPECT_RATIO = 0.75  # 3:4 ratio, good for PDF viewing


def _get_screen_size() -> tuple[int, int]:
    """Get the primary screen dimensions."""
    try:
        user32 = ctypes.windll.user32
        width = user32.GetSystemMetrics(0)
        height = user32.GetSystemMetrics(1)
        return width, height
    except Exception:
        # Fallback to reasonable defaults
        return 1920, 1080


def _calculate_viewport_size() -> tuple[int, int]:
    """Calculate viewport size based on screen dimensions."""
    _, screen_height = _get_screen_size()
    # Use screen height minus taskbar
    viewport_height = screen_height - TASKBAR_HEIGHT
    # Calculate width from aspect ratio
    viewport_width = int(viewport_height * CHART_ASPECT_RATIO)
    return viewport_width, viewport_height


class BrowserSession:
    """Manages a Playwright browser session."""

    def __init__(
        self,
        headless: bool = False,
        window_size: tuple[int, int] | None = None,
        playwright: Playwright | None = None,
    ):
        self.headless = headless
        self.window_size = window_size
        self._playwright: Playwright | None = playwright
        self._owns_playwright = playwright is None  # Only stop playwright if we created it
        self._browser: Browser | None = None
        self._disconnected = False

    def start(self) -> None:
        """Start the browser session."""
        if self._playwright is None:
            self._playwright = sync_playwright().start()
            self._owns_playwright = True
        args = []
        if self.window_size:
            args.append(f"--window-size={self.window_size[0]},{self.window_size[1]}")
        self._browser = self._playwright.chromium.launch(
            headless=self.headless,
            args=args if args else None,
        )
        self._browser.on('disconnected', self._on_disconnected)

    def create_child_session(self, headless: bool = True) -> "BrowserSession":
        """Create a new browser session sharing the same Playwright instance."""
        if self._playwright is None:
            raise RuntimeError("Parent session not started. Call start() first.")
        child = BrowserSession(headless=headless, playwright=self._playwright)
        child.start()
        return child

    def _on_disconnected(self, _: Browser) -> None:
        """Handle browser disconnection (e.g., user closed the window)."""
        self._disconnected = True

    @property
    def is_connected(self) -> bool:
        """Check if the browser is still connected."""
        if self._browser is None:
            return False
        return self._browser.is_connected()

    def stop(self) -> None:
        """Stop the browser session."""
        if self._browser:
            self._browser.close()
            self._browser = None
        if self._playwright and self._owns_playwright:
            self._playwright.stop()
            self._playwright = None

    def new_page(self) -> Page:
        """Create a new browser page."""
        if not self._browser:
            raise RuntimeError("Browser not started. Call start() first.")
        # Use no_viewport so content fills the window (viewport matches window size)
        context = self._browser.new_context(no_viewport=True)
        return context.new_page()

    def __enter__(self) -> "BrowserSession":
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
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
