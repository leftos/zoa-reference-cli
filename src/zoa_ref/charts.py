"""Chart lookup functionality for ZOA Reference Tool."""

import json
import re
import urllib.request
import urllib.error
from dataclasses import dataclass
from enum import Enum
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout


BASE_URL = "https://reference.oakartcc.org"
CHARTS_URL = f"{BASE_URL}/charts"
CHARTS_API_URL = "https://charts-api.oakartcc.org/v1/charts"

# Known airport codes in ZOA
ZOA_AIRPORTS = [
    "SFO",
    "OAK",
    "SJC",
    "SMF",
    "RNO",
    "FAT",
    "MRY",
    "BAB",
    "APC",
    "CCR",
    "CIC",
    "HWD",
    "LVK",
    "MER",
    "MHR",
    "MOD",
    "NUQ",
    "PAO",
    "RDD",
    "RHV",
    "SAC",
    "SCK",
    "SNS",
    "SQL",
    "STS",
    "SUU",
    "TRK",
]


class ChartType(Enum):
    """Types of aviation charts."""

    SID = "sid"  # Standard Instrument Departure
    STAR = "star"  # Standard Terminal Arrival Route
    IAP = "iap"  # Instrument Approach Procedure
    APD = "apd"  # Airport Diagram
    UNKNOWN = "unknown"


@dataclass
class ChartQuery:
    """Parsed chart query."""

    airport: str
    chart_name: str
    chart_type: ChartType = ChartType.UNKNOWN

    @classmethod
    def parse(cls, query: str) -> "ChartQuery":
        """Parse a query string like 'OAK CNDEL5' into a ChartQuery."""
        parts = query.strip().upper().split()
        if len(parts) < 2:
            raise ValueError(
                f"Invalid query format: '{query}'. Expected 'AIRPORT CHART_NAME'"
            )

        airport = parts[0]
        chart_name = " ".join(parts[1:])

        # Normalize chart name: "CNDEL5" -> "CNDEL FIVE"
        chart_name = _normalize_chart_name(chart_name)

        # Try to infer chart type from naming conventions
        chart_type = cls._infer_chart_type(chart_name)

        return cls(airport=airport, chart_name=chart_name, chart_type=chart_type)

    @staticmethod
    def _infer_chart_type(chart_name: str) -> ChartType:
        """Infer the chart type from naming conventions."""
        name = chart_name.upper()

        # IAPs have specific indicators
        if any(
            x in name for x in ["ILS", "LOC", "VOR", "RNAV", "RNP", "GPS", "NDB", "RWY"]
        ):
            return ChartType.IAP

        if "DIAGRAM" in name:
            return ChartType.APD

        # STARs often have ARRIVAL in name
        if "ARRIVAL" in name or "ARR" in name:
            return ChartType.STAR

        if "DEPARTURE" in name or "DEP" in name:
            return ChartType.SID

        return ChartType.UNKNOWN


def _normalize_chart_name(name: str) -> str:
    """
    Normalize chart name for matching.

    Examples:
        CNDEL5 -> CNDEL FIVE
        HUSSH2 -> HUSSH TWO
        ILS28R -> ILS RWY 28R (left as-is, no number word conversion)
    """
    # Number word mapping
    number_words = {
        "1": "ONE",
        "2": "TWO",
        "3": "THREE",
        "4": "FOUR",
        "5": "FIVE",
        "6": "SIX",
        "7": "SEVEN",
        "8": "EIGHT",
        "9": "NINE",
    }

    # Check if it ends with a single digit (SID/STAR pattern)
    match = re.match(r"^([A-Z]+)(\d)$", name)
    if match:
        base = match.group(1)
        digit = match.group(2)
        return f"{base} {number_words.get(digit, digit)}"

    return name


@dataclass
class ChartInfo:
    """Chart information from the API."""

    chart_name: str
    chart_code: str
    pdf_path: str
    faa_ident: str
    icao_ident: str

    @property
    def chart_type(self) -> ChartType:
        """Map chart_code to ChartType."""
        code_map = {
            "DP": ChartType.SID,
            "STAR": ChartType.STAR,
            "IAP": ChartType.IAP,
            "APD": ChartType.APD,
        }
        return code_map.get(self.chart_code, ChartType.UNKNOWN)


def fetch_charts_from_api(airport: str) -> list[ChartInfo]:
    """
    Fetch charts for an airport from the charts API.

    Args:
        airport: FAA or ICAO airport identifier (e.g., "OAK" or "KOAK")

    Returns:
        List of ChartInfo objects for the airport.
    """
    url = f"{CHARTS_API_URL}?apt={airport.upper()}"

    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            data = json.loads(response.read().decode())
    except urllib.error.URLError as e:
        print(f"Error fetching charts from API: {e}")
        return []
    except json.JSONDecodeError as e:
        print(f"Error parsing API response: {e}")
        return []

    # API returns data keyed by airport code (could be FAA or ICAO)
    charts = []
    for _, chart_list in data.items():
        for chart_data in chart_list:
            charts.append(
                ChartInfo(
                    chart_name=chart_data.get("chart_name", ""),
                    chart_code=chart_data.get("chart_code", ""),
                    pdf_path=chart_data.get("pdf_path", ""),
                    faa_ident=chart_data.get("faa_ident", ""),
                    icao_ident=chart_data.get("icao_ident", ""),
                )
            )

    return charts


@dataclass
class ChartMatch:
    """A chart match with similarity score."""

    chart: ChartInfo
    score: float


def find_chart_by_name(
    charts: list[ChartInfo],
    query: ChartQuery,
    ambiguity_threshold: float = 0.15,
) -> tuple[ChartInfo | None, list[ChartMatch]]:
    """
    Find a chart by name using fuzzy matching.

    Args:
        charts: List of charts to search
        query: The parsed chart query
        ambiguity_threshold: Score difference threshold for ambiguous matches

    Returns:
        Tuple of (best_match, all_matches_above_threshold).
        If ambiguous, best_match will be None and all_matches contains the candidates.
    """
    if not charts:
        return None, []

    chart_name_upper = query.chart_name.upper()

    # Tokenize query for all-terms matching
    query_tokens = set(re.findall(r"[A-Z0-9]+", chart_name_upper))

    # Score all charts, excluding continuation pages (CONT.1, CONT.2, etc.)
    # Continuation pages will be found later via find_all_chart_pages
    matches: list[ChartMatch] = []
    for chart in charts:
        # Skip continuation pages - they're not separate charts
        if ", CONT." in chart.chart_name:
            continue
        score = _calculate_similarity(chart_name_upper, chart.chart_name.upper())

        # Boost score if detected chart type matches the actual chart type
        # This helps prioritize IAPs when user searches for "RNAV 4R" etc.
        if (
            query.chart_type != ChartType.UNKNOWN
            and chart.chart_type == query.chart_type
        ):
            score += 0.15  # Type match bonus

        if score > 0.2:  # Minimum threshold
            matches.append(ChartMatch(chart=chart, score=score))

    if not matches:
        return None, []

    # Sort by score descending
    matches.sort(key=lambda m: m.score, reverse=True)

    best_match = matches[0]

    # Check for exact match
    if best_match.score == 1.0:
        return best_match.chart, matches

    # Check if only one match contains ALL query tokens
    # This handles cases like "ILS 28R" where only one result has both terms
    if len(query_tokens) > 1:
        full_matches = []
        for m in matches:
            chart_tokens = set(re.findall(r"[A-Z0-9]+", m.chart.chart_name.upper()))
            if query_tokens <= chart_tokens:  # All query tokens present
                full_matches.append(m)

        if len(full_matches) == 1:
            # Only one match has all query tokens - auto-select it
            return full_matches[0].chart, matches
        elif len(full_matches) > 1:
            # Multiple matches have all tokens - check ambiguity among them
            full_matches.sort(key=lambda m: m.score, reverse=True)
            if full_matches[0].score - full_matches[1].score >= ambiguity_threshold:
                return full_matches[0].chart, matches
            # Ambiguous among full matches
            return None, full_matches

    # Check for ambiguity
    if len(matches) > 1:
        second_score = matches[1].score
        if best_match.score - second_score < ambiguity_threshold:
            # Ambiguous - return None with all close matches
            close_matches = [
                m for m in matches if m.score >= best_match.score - ambiguity_threshold
            ]
            return None, close_matches

    return best_match.chart, matches


def lookup_chart_via_api(query: ChartQuery) -> tuple[str | None, list[ChartMatch]]:
    """
    Look up a chart using the API.

    Args:
        query: The parsed chart query

    Returns:
        Tuple of (pdf_url, matches). If ambiguous or not found, pdf_url is None.
    """
    charts = fetch_charts_from_api(query.airport)
    if not charts:
        return None, []

    chart, matches = find_chart_by_name(charts, query)
    if chart:
        return chart.pdf_path, matches
    return None, matches


def find_all_chart_pages(
    charts: list[ChartInfo],
    base_chart: ChartInfo,
) -> list[ChartInfo]:
    """
    Find all pages of a chart (main page + continuation pages).

    Args:
        charts: List of all charts for the airport
        base_chart: The main chart to find pages for

    Returns:
        List of ChartInfo objects for all pages, sorted by page order.
        The base chart is first, followed by CONT.1, CONT.2, etc.
    """
    base_name = base_chart.chart_name

    # If this is already a continuation page, find the real base
    if ", CONT." in base_name:
        base_name = base_name.split(", CONT.")[0]

    # Find all pages: base + continuations
    pages = []
    for chart in charts:
        if chart.chart_name == base_name:
            pages.append((0, chart))  # Main page
        elif chart.chart_name.startswith(f"{base_name}, CONT."):
            # Extract continuation number
            try:
                cont_part = chart.chart_name.split(", CONT.")[1]
                cont_num = int(cont_part)
                pages.append((cont_num, chart))
            except (IndexError, ValueError):
                # If we can't parse it, add at the end
                pages.append((999, chart))

    # Sort by page number and return just the charts
    pages.sort(key=lambda x: x[0])
    return [chart for _, chart in pages]


def detect_pdf_view_mode(pdf_path: str) -> str:
    """
    Detect the appropriate PDF view mode based on page orientation.

    Args:
        pdf_path: Path to the PDF file

    Returns:
        "FitV" for portrait PDFs (fit to height),
        "FitH" for landscape PDFs (fit to width)
    """
    from pypdf import PdfReader

    try:
        reader = PdfReader(pdf_path)
        if not reader.pages:
            return "FitV"

        page = reader.pages[0]
        # Get effective dimensions accounting for rotation
        rotation = page.get("/Rotate", 0) or 0
        width = float(page.mediabox.width)
        height = float(page.mediabox.height)

        # 90° or 270° rotation swaps effective width/height
        if rotation in (90, -90, 270, -270):
            width, height = height, width

        return "FitH" if width > height else "FitV"
    except Exception:
        return "FitV"


def detect_rotation_needed(pdf_data: bytes) -> int:
    """
    Detect if a PDF needs rotation based on text orientation.

    Analyzes text transformation matrices to determine if the majority
    of text is rotated 90 degrees, indicating the chart should be
    auto-rotated for proper viewing.

    Args:
        pdf_data: Raw PDF bytes

    Returns:
        Rotation angle needed: 0, 90, or -90
    """
    from pypdf import PdfReader
    import math
    from collections import Counter
    import io

    try:
        reader = PdfReader(io.BytesIO(pdf_data))
    except Exception:
        return 0

    angles: Counter[int] = Counter()

    def visitor(text, cm, tm, fontDict, fontSize):
        if text and text.strip() and tm:
            a, b = tm[0], tm[1]
            # Calculate rotation angle and round to nearest 10 degrees
            angle = round(math.atan2(b, a) * 180 / math.pi / 10) * 10
            angles[angle] += 1

    for page in reader.pages:
        try:
            page.extract_text(visitor_text=visitor)
        except Exception:
            continue

    total = sum(angles.values())
    if total == 0:
        return 0

    # Check for 90° rotation need (text is rotated CCW, needs CW page rotation)
    rotated_90 = sum(angles.get(a, 0) for a in [80, 90, 100])
    if rotated_90 / total > 0.50:
        return 90  # Rotate page clockwise

    # Check for -90° rotation need (text is rotated CW, needs CCW page rotation)
    rotated_neg90 = sum(angles.get(a, 0) for a in [-80, -90, -100])
    if rotated_neg90 / total > 0.50:
        return -90  # Rotate page counter-clockwise

    return 0


def download_and_merge_pdfs(
    pdf_urls: list[str],
    output_path: str,
    rotation: int | None = None,
) -> bool:
    """
    Download multiple PDFs and merge them into one file.

    Args:
        pdf_urls: List of PDF URLs to download and merge
        output_path: Path to save the merged PDF
        rotation: Rotation angle in degrees (0, 90, 180, 270).
                  If None, auto-detects from text orientation.

    Returns:
        True if successful, False otherwise.
    """
    from pypdf import PdfReader, PdfWriter
    import tempfile
    import os

    if not pdf_urls:
        return False

    writer = PdfWriter()
    temp_files = []
    pdf_data_list = []

    try:
        # Download all PDFs first
        for url in pdf_urls:
            try:
                with urllib.request.urlopen(url, timeout=30) as response:
                    pdf_data = response.read()
                    pdf_data_list.append(pdf_data)
            except urllib.error.URLError as e:
                print(f"Error downloading {url}: {e}")
                return False

        # Auto-detect rotation from first PDF if not specified
        if rotation is None and pdf_data_list:
            rotation = detect_rotation_needed(pdf_data_list[0])

        # Process each PDF
        for pdf_data in pdf_data_list:
            # Write to temp file (pypdf needs a file, not bytes)
            temp_fd, temp_path = tempfile.mkstemp(suffix=".pdf")
            temp_files.append(temp_path)
            with os.fdopen(temp_fd, "wb") as f:
                f.write(pdf_data)

            # Read and append pages with optional rotation
            reader = PdfReader(temp_path)
            for page in reader.pages:
                if rotation:
                    page.rotate(rotation)
                writer.add_page(page)

        # Write merged PDF
        with open(output_path, "wb") as f:
            writer.write(f)

        return True

    finally:
        # Clean up temp files
        for temp_path in temp_files:
            try:
                os.unlink(temp_path)
            except OSError:
                pass


def download_and_rotate_pdf(
    pdf_url: str, output_path: str, rotation: int | None = None
) -> bool:
    """
    Download a single PDF and optionally rotate it.

    Args:
        pdf_url: URL of the PDF to download
        output_path: Path to save the PDF
        rotation: Rotation angle in degrees (0, 90, 180, 270).
                  If None, auto-detects from text orientation.

    Returns:
        True if successful, False otherwise.
    """
    from pypdf import PdfReader, PdfWriter
    import tempfile
    import os

    try:
        with urllib.request.urlopen(pdf_url, timeout=30) as response:
            pdf_data = response.read()
    except urllib.error.URLError as e:
        print(f"Error downloading {pdf_url}: {e}")
        return False

    # Auto-detect rotation if not specified
    if rotation is None:
        rotation = detect_rotation_needed(pdf_data)

    if not rotation:
        # No rotation needed, just save directly
        with open(output_path, "wb") as f:
            f.write(pdf_data)
        return True

    # Need to rotate - write to temp, read, rotate, write to output
    temp_fd, temp_path = tempfile.mkstemp(suffix=".pdf")
    try:
        with os.fdopen(temp_fd, "wb") as f:
            f.write(pdf_data)

        reader = PdfReader(temp_path)
        writer = PdfWriter()
        for page in reader.pages:
            page.rotate(rotation)
            writer.add_page(page)

        with open(output_path, "wb") as f:
            writer.write(f)

        return True
    finally:
        try:
            os.unlink(temp_path)
        except OSError:
            pass


def lookup_chart_with_pages(
    query: ChartQuery,
) -> tuple[list[str] | None, ChartInfo | None, list[ChartMatch]]:
    """
    Look up a chart and find all its pages using the API.

    Args:
        query: The parsed chart query

    Returns:
        Tuple of (pdf_urls, matched_chart, all_matches).
        - pdf_urls: List of PDF URLs for all pages (None if not found/ambiguous)
        - matched_chart: The matched chart info (None if not found/ambiguous)
        - all_matches: All matches above threshold for display
    """
    charts = fetch_charts_from_api(query.airport)
    if not charts:
        return None, None, []

    chart, matches = find_chart_by_name(charts, query)
    if not chart:
        return None, None, matches

    # Find all pages for this chart
    all_pages = find_all_chart_pages(charts, chart)
    pdf_urls = [page.pdf_path for page in all_pages]

    return pdf_urls, chart, matches


def lookup_chart(page: Page, query: ChartQuery, timeout: int = 30000) -> str | None:
    """
    Navigate to the charts page and look up the specified chart.

    Returns the PDF URL if found, None otherwise.
    """
    # Navigate to charts page
    page.goto(CHARTS_URL, wait_until="networkidle", timeout=timeout)

    # Wait for airport buttons to appear
    try:
        page.wait_for_selector("button:has-text('SFO')", timeout=10000)
    except PlaywrightTimeout:
        print("Warning: Page load timeout, airport buttons not found")
        return None

    # Check if the airport button exists
    airport_btn = page.locator(f"button:has-text('{query.airport}')")
    airport_exists = airport_btn.is_visible(timeout=2000)

    if airport_exists:
        # Airport already in list, just click it
        airport_btn.click()
    else:
        # Airport not in list - add it via the + button
        add_btn = page.locator("button:has(svg)").first
        if not add_btn.is_visible(timeout=2000):
            print(f"Airport {query.airport} not found and unable to add custom airport")
            return None

        add_btn.click()

        # Wait for and fill the airport input
        airport_input = page.locator("input[placeholder='FAA/ICAO']")
        try:
            airport_input.wait_for(timeout=5000)
            airport_input.fill(query.airport)
            airport_input.press("Enter")
        except PlaywrightTimeout:
            print(
                f"Airport {query.airport} not found and custom airport input not available"
            )
            return None

    # Wait for chart buttons to load (not just a fixed timeout)
    # After clicking/adding airport, chart list should populate
    try:
        # Wait for any chart button to appear (buttons with text longer than 3 chars, not airport codes)
        page.wait_for_function(
            """(airportCode) => {{
                const buttons = document.querySelectorAll('button');
                const defaultAirports = ['SFO', 'OAK', 'SJC', 'SMF', 'RNO', 'FAT', 'MRY', 'BAB',
                    'APC', 'CCR', 'CIC', 'HWD', 'LVK', 'MER', 'MHR', 'MOD',
                    'NUQ', 'PAO', 'RDD', 'RHV', 'SAC', 'SCK', 'SNS', 'SQL',
                    'STS', 'SUU', 'TRK'];
                for (const btn of buttons) {{
                    const text = btn.innerText.trim();
                    // Chart buttons have text > 3 chars and aren't airport codes
                    if (text.length > 3 && !defaultAirports.includes(text) && text !== airportCode) {{
                        return true;
                    }}
                }}
                return false;
            }}""",
            arg=query.airport,
            timeout=10000,
        )
    except PlaywrightTimeout:
        print(f"Warning: Timeout waiting for chart buttons to load for {query.airport}")
        return None

    # Determine the best filter text
    filter_text = _get_filter_text(query.chart_name, query.chart_type)

    # Use the filter to narrow down charts
    filter_input = page.locator("input[placeholder='Filter']")
    if filter_input.is_visible(timeout=2000) and filter_text:
        filter_input.fill(filter_text)
        # Small delay for filter to apply (UI debounce)
        page.wait_for_timeout(200)

    # Find and click the chart button using smart matching
    chart_btn = _find_chart_button(page, query.chart_name, query.chart_type)
    if chart_btn:
        chart_btn.click()
    else:
        print(f"Chart {query.chart_name} not found")
        return None

    # Wait for PDF to load (embedded via <object> tag) and get URL
    try:
        pdf_object = page.wait_for_selector("object[data*='.PDF']", timeout=5000)
        if pdf_object:
            return pdf_object.get_attribute("data")
        return None
    except PlaywrightTimeout:
        # Chart might still be visible even without PDF confirmation
        # Try to get the URL anyway
        pdf_object = page.locator("object[data*='.PDF']").first
        if pdf_object.count() > 0:
            return pdf_object.get_attribute("data")
        return None


def _get_filter_text(chart_name: str, chart_type: ChartType) -> str:
    """Determine the best filter text for a chart search."""
    # For IAPs, filter by runway number if present
    runway_match = re.search(r"(\d{1,2}[LRC]?)\s*$", chart_name)
    if chart_type == ChartType.IAP and runway_match:
        return runway_match.group(1)

    # For SIDs/STARs, use the procedure name
    parts = chart_name.split()
    if parts:
        return parts[0]

    return chart_name


def _normalize_runway_numbers(text: str) -> str:
    """
    Normalize runway numbers to have leading zeros.

    Examples:
        "4R" -> "04R"
        "RNAV 4R" -> "RNAV 04R"
        "RWY 4L" -> "RWY 04L"
        "28R" -> "28R" (already 2 digits)
    """

    # Pattern: single digit followed by optional L/R/C (runway designator)
    # Must be preceded by space, start of string, or common prefixes
    def add_leading_zero(match):
        return match.group(1) + "0" + match.group(2)

    # Match single digit runway numbers with optional L/R/C suffix
    # (?:^|\s|RWY) - start of string, whitespace, or RWY prefix
    # (\d)([LRC]?) - single digit with optional L/R/C
    # (?=\s|$) - followed by whitespace or end of string
    return re.sub(r"(^|\s)(\d[LRC]?)(?=\s|$)", add_leading_zero, text)


def _levenshtein(s1: str, s2: str) -> int:
    """
    Calculate the Levenshtein (edit) distance between two strings.

    Returns the minimum number of single-character edits (insertions,
    deletions, or substitutions) needed to transform s1 into s2.
    """
    if len(s1) < len(s2):
        s1, s2 = s2, s1

    if len(s2) == 0:
        return len(s1)

    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            # Cost is 0 if characters match, 1 otherwise
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row

    return previous_row[-1]


def _calculate_similarity(query: str, target: str) -> float:
    """
    Calculate similarity score between query and target strings.

    Uses a combination of:
    - Token overlap (Jaccard similarity)
    - Substring matching bonus
    - Prefix matching bonus
    - Edit distance bonus (for typo tolerance)

    Returns a score between 0 and 1.
    """
    query = query.upper()
    target = target.upper()

    # Normalize runway numbers (4R -> 04R) for consistent matching
    query = _normalize_runway_numbers(query)
    target = _normalize_runway_numbers(target)

    # Exact match
    if query == target:
        return 1.0

    # Tokenize
    query_tokens = set(re.findall(r"[A-Z0-9]+", query))
    target_tokens = set(re.findall(r"[A-Z0-9]+", target))

    if not query_tokens or not target_tokens:
        return 0.0

    # Jaccard similarity
    intersection = len(query_tokens & target_tokens)
    union = len(query_tokens | target_tokens)
    jaccard = intersection / union if union > 0 else 0

    # Substring bonus
    substring_bonus = 0.0
    if query in target:
        substring_bonus = 0.3
    elif any(qt in target for qt in query_tokens):
        substring_bonus = 0.15

    # Prefix bonus (first token match)
    prefix_bonus = 0.0
    if query_tokens and target_tokens:
        query_first = sorted(query_tokens)[0] if query_tokens else ""
        if any(tt.startswith(query_first) for tt in target_tokens):
            prefix_bonus = 0.1

    # Edit distance bonus for typo tolerance
    # Only applies when no exact token match was found
    edit_bonus = 0.0
    if intersection == 0:
        for qt in query_tokens:
            if len(qt) < 4:
                continue  # Skip short tokens to avoid false positives
            for tt in target_tokens:
                if len(tt) < 4:
                    continue
                dist = _levenshtein(qt, tt)
                max_len = max(len(qt), len(tt))
                # Allow up to 2 edits for longer tokens, scale bonus by similarity
                if dist <= 2:
                    # Higher bonus for closer matches
                    similarity = 1 - (dist / max_len)
                    edit_bonus = max(edit_bonus, 0.4 * similarity)

    return min(1.0, jaccard + substring_bonus + prefix_bonus + edit_bonus)


def _find_chart_button(
    page: Page,
    chart_name: str,
    chart_type: ChartType,
    ambiguity_threshold: float = 0.15,
):
    """
    Find the best matching chart button.

    Uses fuzzy matching with ambiguity detection. Returns None if multiple
    charts have similar scores (ambiguous match).
    """
    # Get all visible chart buttons
    buttons = page.locator("button").all()
    visible_buttons = []

    for btn in buttons:
        try:
            if btn.is_visible(timeout=100):
                text = btn.inner_text().strip().upper()
                if text and text not in ZOA_AIRPORTS and len(text) > 3:
                    visible_buttons.append((btn, text))
        except Exception:
            continue

    if not visible_buttons:
        return None

    chart_name_upper = chart_name.upper()

    # Strategy 1: Exact match (highest priority)
    for btn, text in visible_buttons:
        if chart_name_upper == text:
            return btn

    # Strategy 2: For IAPs, match approach type + runway (high priority)
    if chart_type == ChartType.IAP:
        iap_match = re.match(r"(ILS|LOC|VOR|RNAV|RNP|GPS|NDB)\s*(.+)", chart_name_upper)
        if iap_match:
            approach_type = iap_match.group(1)
            runway = iap_match.group(2).strip()

            # Find charts matching both approach type and runway
            matching = []
            for btn, text in visible_buttons:
                if approach_type in text and runway in text:
                    matching.append((btn, text))

            if len(matching) == 1:
                return matching[0][0]
            elif len(matching) > 1:
                # Multiple matches for same approach type + runway
                # Use fuzzy matching to pick the best one
                scores = [
                    (btn, text, _calculate_similarity(chart_name_upper, text))
                    for btn, text in matching
                ]
                scores.sort(key=lambda x: x[2], reverse=True)
                if scores[0][2] - scores[1][2] >= ambiguity_threshold:
                    return scores[0][0]
                # Ambiguous match - warn user and return None
                print(f"Ambiguous match for '{chart_name}':")
                for btn, text, score in scores:
                    if score >= scores[0][2] - ambiguity_threshold:
                        print(f"  - {text} (score: {score:.2f})")
                return None

    # Strategy 3: Fuzzy matching with ambiguity detection
    scores = []
    for btn, text in visible_buttons:
        score = _calculate_similarity(chart_name_upper, text)
        scores.append((btn, text, score))

    # Sort by score descending
    scores.sort(key=lambda x: x[2], reverse=True)

    if not scores:
        return None

    best_score = scores[0][2]

    # Require minimum score threshold
    if best_score < 0.3:
        return None

    # Check for ambiguity
    if len(scores) > 1:
        second_score = scores[1][2]
        if best_score - second_score < ambiguity_threshold:
            # Ambiguous match - multiple charts with similar scores
            print(f"Ambiguous match for '{chart_name}':")
            for btn, text, score in scores[:3]:
                if score >= best_score - ambiguity_threshold:
                    print(f"  - {text} (score: {score:.2f})")
            return None

    return scores[0][0]


def list_charts(page: Page, airport: str) -> list[str]:
    """List all available charts for an airport."""
    page.goto(CHARTS_URL, wait_until="networkidle")

    # Wait and click airport
    page.wait_for_selector(f"button:has-text('{airport}')", timeout=10000)
    page.click(f"button:has-text('{airport}')")
    page.wait_for_timeout(500)

    # Get all chart buttons (excluding airport buttons)
    charts = []
    buttons = page.locator("button").all()

    for btn in buttons:
        try:
            text = btn.inner_text().strip()
            # Skip airport codes and empty buttons
            if text and text not in ZOA_AIRPORTS and len(text) > 3:
                charts.append(text)
        except Exception:
            continue

    return charts
