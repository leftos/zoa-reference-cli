"""Centralized configuration for ZOA Reference CLI."""

import tempfile
from pathlib import Path

# =============================================================================
# Cache Settings
# =============================================================================
CACHE_DIR = Path.home() / ".zoa-ref" / "cache"
CACHE_TTL_SECONDS = 7 * 24 * 60 * 60  # 7 days

# =============================================================================
# Temp Directory
# =============================================================================
TEMP_DIR = Path(tempfile.gettempdir()) / "zoa-ref-cli"


def get_temp_dir() -> Path:
    """Get the temp directory for ZOA Reference CLI, creating it if needed."""
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    return TEMP_DIR

# =============================================================================
# Browser Settings
# =============================================================================
BROWSER_PREF_FILE = Path.home() / ".zoa-ref" / "browser_pref.txt"

# Playwright's Chromium install location. Set as PLAYWRIGHT_BROWSERS_PATH so
# the frozen binary's download lives alongside the user's other zoa-ref state
# rather than being scattered under %LOCALAPPDATA% / ~/.cache.
PLAYWRIGHT_BROWSERS_DIR = Path.home() / ".zoa-ref" / "browsers"

# =============================================================================
# Hotkey Settings
# =============================================================================
HOTKEY_PREF_FILE = Path.home() / ".zoa-ref" / "hotkey_pref.txt"

# =============================================================================
# Base URL
# =============================================================================
REFERENCE_BASE_URL = "https://reference.oakartcc.org"

# =============================================================================
# External Tools
# =============================================================================
AIRSPACE_URL = "https://airspace.oakartcc.org/"
TDLS_URL = "https://tdls.virtualnas.net/"
STRIPS_URL = "https://strips.virtualnas.net/"
VATSIM_RADAR_URL = "https://vatsim-radar.com/"
