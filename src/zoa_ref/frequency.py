"""Airport usage frequency tracking for personalized prefetch.

Tracks which airports the user queries most often across all commands
(charts, routes, ATIS, approaches, SOPs) to prioritize prefetching
chart data for frequently-used airports.
"""

import json
from pathlib import Path

# Major airports always prefetched regardless of user history
MAJOR_AIRPORTS = {"SFO", "OAK", "SJC", "SMF", "RNO"}

# Storage location for frequency data
FREQ_FILE = Path.home() / ".zoa-ref" / "airport_freq.json"

# Maximum number of airports to track (prevents unbounded growth)
MAX_TRACKED_AIRPORTS = 50


def _load_freq() -> dict[str, int]:
    """Load frequency data from disk."""
    if not FREQ_FILE.exists():
        return {}
    try:
        with open(FREQ_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            # Ensure all values are ints
            return {k: int(v) for k, v in data.items() if isinstance(v, (int, float))}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_freq(freq: dict[str, int]) -> None:
    """Save frequency data to disk, trimming to MAX_TRACKED_AIRPORTS."""
    # Trim to top N airports if over limit
    if len(freq) > MAX_TRACKED_AIRPORTS:
        sorted_items = sorted(freq.items(), key=lambda x: x[1], reverse=True)
        freq = dict(sorted_items[:MAX_TRACKED_AIRPORTS])

    try:
        FREQ_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(FREQ_FILE, "w", encoding="utf-8") as f:
            json.dump(freq, f, indent=2)
    except OSError:
        pass  # Fail silently - frequency tracking is non-critical


def record_airport(airport: str) -> None:
    """Increment usage count for an airport.

    Args:
        airport: Airport code (e.g., "OAK", "SFO")
    """
    if not airport:
        return

    airport = airport.upper().strip()
    if len(airport) < 2 or len(airport) > 4:
        return  # Skip invalid codes

    freq = _load_freq()
    freq[airport] = freq.get(airport, 0) + 1
    _save_freq(freq)


def get_top_airports(n: int = 10) -> list[str]:
    """Get the n most frequently used airports.

    Args:
        n: Number of airports to return (default 10)

    Returns:
        List of airport codes sorted by frequency (highest first)
    """
    freq = _load_freq()
    sorted_airports = sorted(freq.keys(), key=lambda k: freq[k], reverse=True)
    return sorted_airports[:n]


def get_prefetch_airports() -> set[str]:
    """Get airports to prefetch for autocomplete.

    Combines major airports (always included) with the user's
    top 10 most frequently used airports.

    Returns:
        Set of airport codes to prefetch
    """
    user_top = set(get_top_airports(10))
    return MAJOR_AIRPORTS | user_top


def get_frequency(airport: str) -> int:
    """Get the usage count for a specific airport.

    Args:
        airport: Airport code

    Returns:
        Usage count (0 if never used)
    """
    freq = _load_freq()
    return freq.get(airport.upper(), 0)
