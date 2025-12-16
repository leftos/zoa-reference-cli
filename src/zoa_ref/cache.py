"""AIRAC-aware caching for ZOA Reference Tool.

This module provides caching infrastructure with automatic invalidation
based on AIRAC (Aeronautical Information Regulation And Control) cycles.
AIRAC cycles are 28 days and follow a predictable schedule.

Chart PDFs and analysis results are cached per-AIRAC cycle and automatically
invalidate when a new cycle begins.
"""

import json
import re
import shutil
from datetime import date, timedelta
from pathlib import Path

from zoa_ref.config import CACHE_DIR

# AIRAC epoch: Cycle 2501 effective date
# All AIRAC cycles can be calculated from this reference point
AIRAC_EPOCH = date(2025, 1, 23)
CYCLE_DAYS = 28


# --- AIRAC Cycle Calculation ---


def get_current_airac_cycle() -> tuple[str, date, date]:
    """Calculate current AIRAC cycle and its date boundaries.

    AIRAC cycles follow a predictable 28-day schedule. This function
    calculates the current cycle ID and its exact start/end dates
    from a known epoch (cycle 2501 = January 23, 2025).

    Returns:
        Tuple of (cycle_id, start_date, end_date)
        Example: ("2512", date(2025, 11, 27), date(2025, 12, 24))
    """
    today = date.today()
    days_since_epoch = (today - AIRAC_EPOCH).days
    cycle_number = days_since_epoch // CYCLE_DAYS  # 0-indexed from 2501

    # Calculate year and cycle within year
    # Note: There are 13 cycles per year (28 * 13 = 364 days)
    year = 2025 + (cycle_number // 13)
    cycle_in_year = (cycle_number % 13) + 1
    cycle_id = f"{year % 100:02d}{cycle_in_year:02d}"

    start_date = AIRAC_EPOCH + timedelta(days=cycle_number * CYCLE_DAYS)
    end_date = start_date + timedelta(days=CYCLE_DAYS - 1)

    return cycle_id, start_date, end_date


def extract_airac_from_url(pdf_url: str) -> str | None:
    """Extract AIRAC cycle identifier from FAA chart URL.

    FAA chart URLs contain the AIRAC cycle in the path:
    https://aeronav.faa.gov/d-tpp/2512/filename.PDF

    Args:
        pdf_url: URL to an FAA chart PDF

    Returns:
        AIRAC cycle identifier (e.g., "2512") or None if not found
    """
    match = re.search(r"/d-tpp/(\d{4})/", pdf_url)
    return match.group(1) if match else None


def get_airac_for_caching(pdf_url: str | None = None) -> str:
    """Get the AIRAC cycle to use for caching.

    If a PDF URL is provided and contains an AIRAC cycle, use that.
    Otherwise, calculate the current cycle from the epoch.

    Args:
        pdf_url: Optional URL to extract AIRAC from

    Returns:
        AIRAC cycle identifier (e.g., "2512")
    """
    if pdf_url:
        airac = extract_airac_from_url(pdf_url)
        if airac:
            return airac

    cycle_id, _, _ = get_current_airac_cycle()
    return cycle_id


# --- Chart PDF Caching ---


def _sanitize_filename(name: str) -> str:
    """Sanitize a string for use as a filename."""
    # Replace spaces and special chars with underscores
    safe = re.sub(r"[^\w\-.]", "_", name)
    # Collapse multiple underscores
    safe = re.sub(r"_+", "_", safe)
    return safe.strip("_")


def get_chart_cache_path(airport: str, chart_name: str, airac: str) -> Path:
    """Get the cache path for a chart PDF.

    Args:
        airport: Airport code (e.g., "OAK")
        chart_name: Chart name (e.g., "CNDEL FIVE")
        airac: AIRAC cycle (e.g., "2512")

    Returns:
        Path to the cached PDF file
    """
    safe_name = _sanitize_filename(chart_name)
    return CACHE_DIR / "charts" / airac / airport.upper() / f"{safe_name}.pdf"


def get_cached_chart_pdf(airport: str, chart_name: str, airac: str) -> bytes | None:
    """Retrieve a cached chart PDF.

    Args:
        airport: Airport code
        chart_name: Chart name
        airac: AIRAC cycle

    Returns:
        PDF bytes if cached, None otherwise
    """
    cache_path = get_chart_cache_path(airport, chart_name, airac)
    if cache_path.exists():
        try:
            return cache_path.read_bytes()
        except OSError:
            return None
    return None


def cache_chart_pdf(
    airport: str, chart_name: str, pdf_data: bytes, airac: str
) -> Path | None:
    """Cache a chart PDF.

    Args:
        airport: Airport code
        chart_name: Chart name
        pdf_data: PDF bytes to cache
        airac: AIRAC cycle

    Returns:
        Path to cached file, or None if caching failed
    """
    cache_path = get_chart_cache_path(airport, chart_name, airac)
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(pdf_data)
        return cache_path
    except OSError:
        return None


def get_cached_chart_pdf_by_url(pdf_url: str) -> bytes | None:
    """Retrieve a cached chart PDF by its URL.

    Extracts the AIRAC cycle and generates a cache key from the URL.

    Args:
        pdf_url: Full URL to the chart PDF

    Returns:
        PDF bytes if cached, None otherwise
    """
    airac = extract_airac_from_url(pdf_url)
    if not airac:
        return None

    # Extract filename from URL as cache key
    # URL format: https://aeronav.faa.gov/d-tpp/2512/00294CNDEL.PDF
    match = re.search(r"/([^/]+\.PDF)$", pdf_url, re.IGNORECASE)
    if not match:
        return None

    filename = match.group(1)
    cache_path = CACHE_DIR / "charts" / airac / "by_url" / filename

    if cache_path.exists():
        try:
            return cache_path.read_bytes()
        except OSError:
            return None
    return None


def cache_chart_pdf_by_url(pdf_url: str, pdf_data: bytes) -> Path | None:
    """Cache a chart PDF using its URL as the key.

    Args:
        pdf_url: Full URL to the chart PDF
        pdf_data: PDF bytes to cache

    Returns:
        Path to cached file, or None if caching failed
    """
    airac = extract_airac_from_url(pdf_url)
    if not airac:
        return None

    # Extract filename from URL
    match = re.search(r"/([^/]+\.PDF)$", pdf_url, re.IGNORECASE)
    if not match:
        return None

    filename = match.group(1)
    cache_path = CACHE_DIR / "charts" / airac / "by_url" / filename

    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(pdf_data)
        return cache_path
    except OSError:
        return None


# --- Analysis Result Caching ---


def get_analysis_cache_path(
    airport: str, chart_name: str, analysis_type: str, airac: str
) -> Path:
    """Get the cache path for chart analysis results.

    Args:
        airport: Airport code
        chart_name: Chart name
        analysis_type: Type of analysis ("star" or "iap")
        airac: AIRAC cycle

    Returns:
        Path to the cached JSON file
    """
    safe_name = _sanitize_filename(chart_name)
    return (
        CACHE_DIR
        / "analysis"
        / airac
        / airport.upper()
        / f"{safe_name}_{analysis_type}.json"
    )


def get_cached_analysis(
    airport: str, chart_name: str, analysis_type: str, airac: str
) -> dict | None:
    """Retrieve cached analysis results.

    Args:
        airport: Airport code
        chart_name: Chart name
        analysis_type: Type of analysis ("star" or "iap")
        airac: AIRAC cycle

    Returns:
        Analysis dict if cached, None otherwise
    """
    cache_path = get_analysis_cache_path(airport, chart_name, analysis_type, airac)
    if cache_path.exists():
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return None
    return None


def cache_analysis(
    airport: str, chart_name: str, analysis_type: str, analysis: dict, airac: str
) -> None:
    """Cache analysis results.

    Args:
        airport: Airport code
        chart_name: Chart name
        analysis_type: Type of analysis ("star" or "iap")
        analysis: Analysis data to cache
        airac: AIRAC cycle
    """
    cache_path = get_analysis_cache_path(airport, chart_name, analysis_type, airac)
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(analysis, f)
    except OSError:
        pass


# --- Procedure Headings Caching (AIRAC-aware) ---


def get_headings_cache_path(uuid: str, airac: str) -> Path:
    """Get the cache path for procedure headings.

    Args:
        uuid: Procedure UUID
        airac: AIRAC cycle

    Returns:
        Path to the cached JSON file
    """
    safe_uuid = uuid.replace("/", "_").replace("\\", "_")
    return CACHE_DIR / "procedures" / "headings" / airac / f"{safe_uuid}.json"


def get_cached_headings(uuid: str, airac: str) -> list[dict] | None:
    """Retrieve cached procedure headings.

    Args:
        uuid: Procedure UUID
        airac: AIRAC cycle

    Returns:
        List of heading dicts if cached, None otherwise
    """
    cache_path = get_headings_cache_path(uuid, airac)
    if cache_path.exists():
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("headings", [])
        except (OSError, json.JSONDecodeError):
            return None
    return None


def cache_headings(uuid: str, headings: list[dict], airac: str) -> None:
    """Cache procedure headings.

    Args:
        uuid: Procedure UUID
        headings: List of heading dicts to cache
        airac: AIRAC cycle
    """
    cache_path = get_headings_cache_path(uuid, airac)
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump({"headings": headings}, f)
    except OSError:
        pass


# --- Cache Cleanup ---


def cleanup_old_airac_caches(keep_cycles: int = 2) -> int:
    """Remove cache directories for old AIRAC cycles.

    Keeps the most recent cycles and removes older ones to prevent
    cache bloat.

    Args:
        keep_cycles: Number of recent cycles to keep (default: 2)

    Returns:
        Number of directories removed
    """
    current_cycle, _, _ = get_current_airac_cycle()
    removed = 0

    # Check each AIRAC-based cache directory
    for cache_type in ["charts", "analysis"]:
        cache_base = CACHE_DIR / cache_type
        if not cache_base.exists():
            continue

        for airac_dir in cache_base.iterdir():
            if not airac_dir.is_dir():
                continue

            # Check if this looks like an AIRAC cycle directory
            if not re.match(r"^\d{4}$", airac_dir.name):
                continue

            # Skip if it's a recent cycle
            try:
                cycle_num = int(airac_dir.name)
                current_num = int(current_cycle)

                # Simple comparison - if more than keep_cycles behind, remove
                # This works because AIRAC cycles increment predictably
                if current_num - cycle_num > keep_cycles:
                    shutil.rmtree(airac_dir)
                    removed += 1
            except (ValueError, OSError):
                continue

    # Also clean up procedure headings cache
    headings_base = CACHE_DIR / "procedures" / "headings"
    if headings_base.exists():
        for airac_dir in headings_base.iterdir():
            if not airac_dir.is_dir():
                continue

            if not re.match(r"^\d{4}$", airac_dir.name):
                continue

            try:
                cycle_num = int(airac_dir.name)
                current_num = int(current_cycle)

                if current_num - cycle_num > keep_cycles:
                    shutil.rmtree(airac_dir)
                    removed += 1
            except (ValueError, OSError):
                continue

    # Clean up old CIFP data files
    cifp_base = CACHE_DIR / "cifp"
    if cifp_base.exists():
        for cifp_file in cifp_base.iterdir():
            if not cifp_file.is_file():
                continue

            # CIFP files are named like "FAACIFP18-2512"
            match = re.match(r"^FAACIFP\d+-(\d{4})$", cifp_file.name)
            if not match:
                continue

            try:
                cycle_num = int(match.group(1))
                current_num = int(current_cycle)

                if current_num - cycle_num > keep_cycles:
                    cifp_file.unlink()
                    removed += 1
            except (ValueError, OSError):
                continue

    return removed


def clear_all_airac_cache() -> int:
    """Clear all AIRAC-based cache data.

    Does NOT clear time-based caches (ICAO codes, etc.)

    Returns:
        Number of items removed
    """
    removed = 0

    for cache_type in ["charts", "analysis", "cifp"]:
        cache_base = CACHE_DIR / cache_type
        if cache_base.exists():
            try:
                shutil.rmtree(cache_base)
                removed += 1
            except OSError:
                pass

    headings_base = CACHE_DIR / "procedures" / "headings"
    if headings_base.exists():
        try:
            shutil.rmtree(headings_base)
            removed += 1
        except OSError:
            pass

    return removed
