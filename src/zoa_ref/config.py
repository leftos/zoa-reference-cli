"""Centralized configuration for ZOA Reference CLI."""

from pathlib import Path

# =============================================================================
# Cache Settings
# =============================================================================
CACHE_DIR = Path.home() / ".zoa-ref" / "cache"
CACHE_TTL_SECONDS = 7 * 24 * 60 * 60  # 7 days

# =============================================================================
# Browser Settings
# =============================================================================
BROWSER_PREF_FILE = Path.home() / ".zoa-ref" / "browser_pref.txt"

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
