"""Procedure/SOP lookup functionality for ZOA Reference Tool."""

import io
import json
import re
import time
import urllib.request
import urllib.error
from dataclasses import dataclass, asdict
from pathlib import Path
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout


BASE_URL = "https://reference.oakartcc.org"
PROCEDURES_URL = f"{BASE_URL}/procedures"

# Cache configuration
CACHE_DIR = Path.home() / ".zoa-ref" / "cache"
PROCEDURES_CACHE_FILE = CACHE_DIR / "procedures" / "procedures_list.json"
HEADINGS_CACHE_DIR = CACHE_DIR / "procedures" / "headings"
CACHE_TTL_PROCEDURES = 7 * 24 * 60 * 60  # 7 days for procedure list
CACHE_TTL_HEADINGS = 30 * 24 * 60 * 60   # 30 days for heading mappings


# --- Data Structures ---

@dataclass
class ProcedureInfo:
    """Procedure document information."""
    name: str       # Display name (e.g., "Oakland ATCT SOP")
    pdf_url: str    # Relative URL (e.g., "zoapdfs/<uuid>.pdf")
    category: str   # Category (e.g., "atct", "enroute", "loa")

    @property
    def uuid(self) -> str:
        """Extract UUID from PDF URL."""
        match = re.search(r'zoapdfs/([^/]+)\.pdf', self.pdf_url)
        return match.group(1) if match else ""

    @property
    def full_url(self) -> str:
        """Get full URL to PDF."""
        if self.pdf_url.startswith("http"):
            return self.pdf_url
        return f"{BASE_URL}/{self.pdf_url}"


@dataclass
class HeadingInfo:
    """A heading/section within a procedure PDF."""
    title: str   # Heading text (e.g., "2-2 IFR Departures")
    page: int    # 1-based page number
    level: int   # Nesting level (0 = top-level)


@dataclass
class ProcedureMatch:
    """A procedure match with similarity score."""
    procedure: ProcedureInfo
    score: float


@dataclass
class ProcedureQuery:
    """Parsed procedure query."""
    procedure_term: str        # e.g., "OAK", "NORCAL TRACON"
    section_term: str | None   # e.g., "2-2", "IFR Departures", None
    search_term: str | None    # e.g., "SJCE" - text to find within section

    @classmethod
    def parse(cls, query: str | tuple[str, ...]) -> "ProcedureQuery":
        """
        Parse a query into procedure, section, and optional search terms.

        Can accept either a string or a tuple of parts (from CLI arguments).
        When given a tuple, quoted strings are preserved as single elements.

        Examples:
            "OAK 2-2"                    -> proc="OAK", section="2-2", search=None
            "OAK ATCT 2-2"               -> proc="OAK ATCT", section="2-2", search=None
            ("SJC", "2-2", "SJCE")       -> proc="SJC", section="2-2", search="SJCE"
            ("SJC", "IFR Departures", "SJCE") -> proc="SJC", section="IFR Departures", search="SJCE"
        """
        # Handle tuple input (preserves quoted strings from CLI)
        if isinstance(query, tuple):
            return cls._parse_tuple(query)

        # Handle string input
        return cls._parse_string(query)

    @classmethod
    def _parse_tuple(cls, parts: tuple[str, ...]) -> "ProcedureQuery":
        """Parse a tuple of parts, treating each element as a distinct component."""
        if not parts:
            raise ValueError("Empty query")

        # Known keywords and codes for procedure detection
        proc_keywords = {"ATCT", "SOP", "TRACON", "LOA", "CPS", "CENTER"}
        airport_codes = {
            "SFO", "OAK", "SJC", "SMF", "RNO", "FAT", "MRY", "BAB",
            "APC", "CCR", "CIC", "HWD", "LVK", "MER", "MHR", "MOD",
            "NUQ", "PAO", "RDD", "RHV", "SAC", "SCK", "SNS", "SQL",
            "STS", "SUU", "TRK", "NCT", "ZOA", "ZLA", "ZLC", "ZSE",
            "NFL", "NLC", "ZAK"
        }

        parts_list = list(parts)
        procedure_parts = []
        section_term = None
        search_term = None

        # Determine how many parts belong to the procedure name
        # Strategy: consume parts until we hit something that looks like a section
        i = 0
        while i < len(parts_list):
            part = parts_list[i]
            part_upper = part.upper()

            # Check if this looks like a section indicator
            is_section_start = (
                re.match(r'^\d+[-.]', part_upper) or  # "2-2", "3.1"
                (i > 0 and part_upper not in proc_keywords and
                 part_upper not in airport_codes and
                 len(part) > 1)  # Multi-char non-keyword after first part
            )

            # If first part is an airport code or proc keyword, second part could be section
            if i == 1 and procedure_parts:
                first_upper = procedure_parts[0].upper()
                if (first_upper in airport_codes or first_upper in proc_keywords) and is_section_start:
                    break

            # If we have airport + keyword, next part is section
            if len(procedure_parts) >= 2:
                first_upper = procedure_parts[0].upper()
                last_upper = procedure_parts[-1].upper()
                if first_upper in airport_codes and last_upper in proc_keywords:
                    break

            # Check if this starts a section (digit pattern)
            if re.match(r'^\d+[-.]', part_upper):
                break

            procedure_parts.append(part)
            i += 1

        # Remaining parts are section and optional search
        remaining = parts_list[i:]

        if len(remaining) >= 2:
            # Last part is search term, rest is section
            section_term = " ".join(remaining[:-1])
            search_term = remaining[-1]
        elif len(remaining) == 1:
            # Single remaining part is section
            section_term = remaining[0]

        procedure_term = " ".join(procedure_parts) if procedure_parts else ""

        if not procedure_term:
            raise ValueError("No procedure term found in query")

        return cls(
            procedure_term=procedure_term,
            section_term=section_term,
            search_term=search_term
        )

    @classmethod
    def _parse_string(cls, query: str) -> "ProcedureQuery":
        """Parse a string query, handling quoted strings for interactive mode."""
        import shlex

        query = query.strip()
        if not query:
            raise ValueError("Empty query")

        # Use shlex to handle quoted strings (e.g., "IFR Departures")
        try:
            parts = shlex.split(query)
        except ValueError:
            # Fall back to simple split if shlex fails (e.g., unbalanced quotes)
            parts = query.split()

        # Reuse tuple parsing logic for consistency
        return cls._parse_tuple(tuple(parts))


# --- Caching ---

def _load_procedures_cache() -> list[ProcedureInfo] | None:
    """Load cached procedures list if valid."""
    if not PROCEDURES_CACHE_FILE.exists():
        return None

    try:
        with open(PROCEDURES_CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Check TTL
        if time.time() - data.get("timestamp", 0) > CACHE_TTL_PROCEDURES:
            return None

        return [ProcedureInfo(**p) for p in data.get("procedures", [])]
    except (json.JSONDecodeError, OSError, TypeError):
        return None


def _save_procedures_cache(procedures: list[ProcedureInfo]) -> None:
    """Save procedures list to cache."""
    PROCEDURES_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)

    data = {
        "timestamp": time.time(),
        "procedures": [asdict(p) for p in procedures]
    }

    try:
        with open(PROCEDURES_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except OSError:
        pass


def _get_headings_cache_path(uuid: str) -> Path:
    """Get cache file path for procedure headings."""
    safe_uuid = uuid.replace("/", "_").replace("\\", "_")
    return HEADINGS_CACHE_DIR / f"{safe_uuid}.json"


def _load_headings_cache(uuid: str) -> list[HeadingInfo] | None:
    """Load cached headings for a procedure."""
    cache_path = _get_headings_cache_path(uuid)
    if not cache_path.exists():
        return None

    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Check TTL
        if time.time() - data.get("timestamp", 0) > CACHE_TTL_HEADINGS:
            return None

        return [HeadingInfo(**h) for h in data.get("headings", [])]
    except (json.JSONDecodeError, OSError, TypeError):
        return None


def _save_headings_cache(uuid: str, headings: list[HeadingInfo]) -> None:
    """Save headings to cache."""
    cache_path = _get_headings_cache_path(uuid)
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    data = {
        "timestamp": time.time(),
        "headings": [asdict(h) for h in headings]
    }

    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except OSError:
        pass


# --- Similarity Matching ---

# Airport code to city name aliases for better matching
AIRPORT_ALIASES = {
    "SFO": "SAN FRANCISCO",
    "OAK": "OAKLAND",
    "SJC": "SAN JOSE",
    "SMF": "SACRAMENTO",
    "RNO": "RENO",
    "FAT": "FRESNO",
    "MRY": "MONTEREY",
    "NCT": "NORCAL",
    "ZOA": "OAKLAND CENTER",
}


def _expand_airport_aliases(query: str) -> str:
    """Expand airport codes in query to include city names."""
    query_upper = query.upper()
    for code, name in AIRPORT_ALIASES.items():
        if code in query_upper.split():
            # Replace the code with both code and name for matching
            query_upper = query_upper.replace(code, f"{code} {name}")
    return query_upper


def _levenshtein(s1: str, s2: str) -> int:
    """Calculate Levenshtein edit distance between two strings."""
    if len(s1) < len(s2):
        s1, s2 = s2, s1

    if len(s2) == 0:
        return len(s1)

    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
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
    # Expand airport aliases in query (e.g., "SFO" -> "SFO SAN FRANCISCO")
    query = _expand_airport_aliases(query)
    target = target.upper()

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
    edit_bonus = 0.0
    if intersection == 0:
        for qt in query_tokens:
            if len(qt) < 4:
                continue
            for tt in target_tokens:
                if len(tt) < 4:
                    continue
                dist = _levenshtein(qt, tt)
                max_len = max(len(qt), len(tt))
                if dist <= 2:
                    similarity = 1 - (dist / max_len)
                    edit_bonus = max(edit_bonus, 0.4 * similarity)

    return min(1.0, jaccard + substring_bonus + prefix_bonus + edit_bonus)


# --- Procedures List Fetching ---

def _categorize_procedure(name: str, optgroup: str) -> str:
    """Determine category from procedure name and optgroup."""
    name_lower = name.lower()
    optgroup_lower = optgroup.lower()

    if "central policy" in optgroup_lower or name_lower.startswith("cps"):
        return "policy"
    if "enroute" in optgroup_lower or "oakland center" in name_lower:
        return "enroute"
    if "tracon" in optgroup_lower or "tracon" in name_lower:
        return "tracon"
    if "airport traffic control" in optgroup_lower or "atct" in name_lower:
        return "atct"
    if "internal" in optgroup_lower:
        return "loa_internal"
    if "external" in optgroup_lower:
        return "loa_external"
    if "military" in optgroup_lower:
        return "loa_military"
    if "zak" in optgroup_lower or "pacific" in name_lower:
        return "zak"
    if "quick reference" in optgroup_lower:
        return "quick_ref"

    return "other"


def _scrape_procedures_dropdown(page: Page) -> list[ProcedureInfo]:
    """Scrape procedure entries from the dropdown on the page."""
    procedures = []

    try:
        # Find the select element
        select = page.locator("select").first
        if not select:
            return []

        # Get all optgroups and options
        optgroups = select.locator("optgroup").all()

        for optgroup in optgroups:
            optgroup_label = optgroup.get_attribute("label") or ""

            options = optgroup.locator("option").all()
            for option in options:
                value = option.get_attribute("value") or ""
                name = option.inner_text().strip()

                if value and name:
                    category = _categorize_procedure(name, optgroup_label)
                    procedures.append(ProcedureInfo(
                        name=name,
                        pdf_url=value,
                        category=category
                    ))

    except Exception:
        pass

    return procedures


def fetch_procedures_list(
    page: Page | None = None,
    use_cache: bool = True,
    timeout: int = 30000
) -> list[ProcedureInfo]:
    """
    Fetch the list of available procedures.

    Args:
        page: Playwright page (can be None if cache hit expected)
        use_cache: Whether to use cached results
        timeout: Page navigation timeout

    Returns:
        List of ProcedureInfo objects.
    """
    # Check cache first
    if use_cache:
        cached = _load_procedures_cache()
        if cached:
            return cached

    # Need page for fresh lookup
    if page is None:
        return []

    try:
        page.goto(PROCEDURES_URL, wait_until="networkidle", timeout=timeout)
        # Wait for select to appear
        page.wait_for_selector("select", timeout=10000)
    except PlaywrightTimeout:
        return []

    procedures = _scrape_procedures_dropdown(page)

    # Cache results
    if use_cache and procedures:
        _save_procedures_cache(procedures)

    return procedures


# --- Fuzzy Matching ---

# Aliases for common procedure search terms
# Maps a search term to additional terms that should also be searched
PROCEDURE_ALIASES: dict[str, list[str]] = {
    "NCT": ["NORCAL TRACON", "NORTHERN CALIFORNIA TRACON"],
    "NORCAL": ["NCT", "NORTHERN CALIFORNIA TRACON"],
    "ZOA": ["OAKLAND CENTER"],
    "OAKLAND": ["ZOA"],
}


def find_procedure_by_name(
    procedures: list[ProcedureInfo],
    query: ProcedureQuery,
    ambiguity_threshold: float = 0.15,
) -> tuple[ProcedureInfo | None, list[ProcedureMatch]]:
    """
    Find a procedure by name using fuzzy matching.

    Args:
        procedures: List of procedures to search
        query: The parsed procedure query
        ambiguity_threshold: Score difference threshold for ambiguous matches

    Returns:
        Tuple of (best_match, all_matches_above_threshold).
        If ambiguous, best_match will be None and all_matches contains candidates.
    """
    search_term = query.procedure_term.upper()

    # Expand search terms with aliases
    search_terms = [search_term]
    if search_term in PROCEDURE_ALIASES:
        search_terms.extend(PROCEDURE_ALIASES[search_term])

    matches = []
    seen_procs: set[str] = set()  # Track by PDF URL to avoid duplicates

    for proc in procedures:
        if proc.pdf_url in seen_procs:
            continue

        # Calculate similarity against all search terms, use best score
        best_score = 0.0
        for term in search_terms:
            score = _calculate_similarity(term, proc.name)
            best_score = max(best_score, score)

        if best_score > 0.2:  # Minimum threshold
            matches.append(ProcedureMatch(procedure=proc, score=best_score))
            seen_procs.add(proc.pdf_url)

    if not matches:
        return None, []

    # Sort by score descending
    matches.sort(key=lambda m: m.score, reverse=True)

    best_match = matches[0]

    # Check for exact match
    if best_match.score == 1.0:
        return best_match.procedure, matches

    # Check for ambiguity
    if len(matches) > 1:
        second_score = matches[1].score
        if best_match.score - second_score < ambiguity_threshold:
            # Ambiguous - return None with all close matches
            close_matches = [
                m for m in matches
                if m.score >= best_match.score - ambiguity_threshold
            ]
            return None, close_matches

    return best_match.procedure, matches


# --- PDF Heading Extraction ---

def _download_pdf(url: str, timeout: int = 30) -> bytes | None:
    """Download PDF content from URL."""
    full_url = url if url.startswith("http") else f"{BASE_URL}/{url}"

    try:
        req = urllib.request.Request(
            full_url,
            headers={"User-Agent": "ZOA-Reference-CLI/1.0"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.read()
    except (urllib.error.URLError, TimeoutError):
        return None


def _extract_pdf_bookmarks(pdf_data: bytes) -> list[HeadingInfo]:
    """
    Extract bookmarks/outline from PDF using pypdf.

    Returns list of HeadingInfo sorted by page number.
    """
    try:
        from pypdf import PdfReader
    except ImportError:
        return []

    headings = []

    try:
        reader = PdfReader(io.BytesIO(pdf_data))

        def process_outline(outline, level=0):
            for item in outline:
                if isinstance(item, list):
                    # Nested outline - recurse
                    process_outline(item, level + 1)
                else:
                    # Destination object
                    try:
                        page_idx = reader.get_destination_page_number(item)
                        if page_idx is not None:
                            page_num = page_idx + 1
                            title = str(item.title) if item.title else ""
                            if title:
                                headings.append(HeadingInfo(
                                    title=title,
                                    page=page_num,
                                    level=level
                                ))
                    except Exception:
                        pass

        if reader.outline:
            process_outline(reader.outline)

    except Exception:
        pass

    return headings


def _search_pdf_text_for_heading(pdf_data: bytes, heading_query: str) -> int | None:
    """
    Search PDF text for a heading pattern when bookmarks unavailable.

    Looks for patterns like "2-2", "2.2", "Section 2-2", heading text, etc.
    Returns 1-based page number if found, None otherwise.
    """
    try:
        from pypdf import PdfReader
    except ImportError:
        return None

    try:
        reader = PdfReader(io.BytesIO(pdf_data))
        query_upper = heading_query.upper()

        # Build pattern for section numbers like "2-2" or "2.2"
        section_pattern = None
        section_match = re.match(r'^(\d+)[-.](\d+)$', heading_query)
        if section_match:
            # Create flexible pattern for section numbers
            section_pattern = re.compile(
                rf'\b{section_match.group(1)}[-.\s]*{section_match.group(2)}\b',
                re.IGNORECASE
            )

        for page_num, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            text_upper = text.upper()

            # Try section pattern first
            if section_pattern and section_pattern.search(text):
                return page_num

            # Try direct text match
            if query_upper in text_upper:
                return page_num

    except Exception:
        pass

    return None


def _find_matching_heading(headings: list[HeadingInfo], query: str) -> HeadingInfo | None:
    """Find a heading that matches the query."""
    query_upper = query.upper()

    # Check for section number pattern like "2-2" or "2.2"
    section_match = re.match(r'^(\d+)[-.](\d+)$', query)
    if section_match:
        section_pattern = re.compile(
            rf'\b{section_match.group(1)}[-.\s]*{section_match.group(2)}\b',
            re.IGNORECASE
        )
        for heading in headings:
            if section_pattern.search(heading.title):
                return heading

    # Try direct substring match
    for heading in headings:
        if query_upper in heading.title.upper():
            return heading

    # Try fuzzy match
    best_match = None
    best_score = 0.0
    for heading in headings:
        score = _calculate_similarity(query, heading.title)
        if score > best_score and score > 0.4:
            best_score = score
            best_match = heading

    return best_match


def get_procedure_headings(
    procedure: ProcedureInfo,
    use_cache: bool = True
) -> list[HeadingInfo]:
    """
    Get headings for a procedure, using cache or fetching PDF.

    Strategy:
    1. Check cache for heading mapping
    2. If not cached, download PDF
    3. Extract bookmarks
    4. Cache results (even if empty, to avoid repeated downloads)
    """
    uuid = procedure.uuid
    if not uuid:
        return []

    if use_cache:
        cached = _load_headings_cache(uuid)
        if cached is not None:
            return cached

    # Download PDF
    pdf_data = _download_pdf(procedure.pdf_url)
    if not pdf_data:
        return []

    # Extract bookmarks
    headings = _extract_pdf_bookmarks(pdf_data)

    # Cache results
    if use_cache:
        _save_headings_cache(uuid, headings)

    return headings


def find_heading_page(
    procedure: ProcedureInfo,
    section_query: str,
    use_cache: bool = True
) -> int | None:
    """
    Find the page number for a section heading.

    Args:
        procedure: The procedure to search
        section_query: Section identifier (e.g., "2-2", "IFR Departures")
        use_cache: Whether to use cached heading data

    Returns:
        1-based page number, or None if not found.
    """
    # First try bookmarks (fast, cached)
    headings = get_procedure_headings(procedure, use_cache)

    if headings:
        # Search bookmarks for matching heading
        best_match = _find_matching_heading(headings, section_query)
        if best_match:
            return best_match.page

    # Fallback: text search (requires downloading PDF if not already done)
    pdf_data = _download_pdf(procedure.pdf_url)
    if pdf_data:
        return _search_pdf_text_for_heading(pdf_data, section_query)

    return None


def find_text_in_section(
    procedure: ProcedureInfo,
    section_query: str,
    search_term: str,
    use_cache: bool = True
) -> int | None:
    """
    Find the page number where search_term appears within a section.

    This performs a multi-step lookup:
    1. Find the section's starting page
    2. Search from that page forward for the search_term
    3. Return the first page where search_term is found

    Args:
        procedure: The procedure to search
        section_query: Section identifier (e.g., "2-2", "IFR Departures")
        search_term: Text to find within the section (e.g., "SJCE")
        use_cache: Whether to use cached heading data

    Returns:
        1-based page number, or None if not found.
    """
    # First find the section's starting page
    section_page = find_heading_page(procedure, section_query, use_cache)
    if section_page is None:
        return None

    # Get headings to determine section boundaries
    headings = get_procedure_headings(procedure, use_cache)

    # Find the end page and heading of the section (next section at same or higher level)
    end_page = None
    next_section_title = None
    if headings:
        # Find the heading that matches our section and its index
        section_heading = _find_matching_heading(headings, section_query)
        if section_heading:
            section_level = section_heading.level
            # Find index of section heading in the list
            section_idx = next(
                (i for i, h in enumerate(headings) if h.title == section_heading.title),
                -1
            )
            # Find next heading at same or higher level (lower number = higher level)
            # Start from after the section heading in the list order
            for heading in headings[section_idx + 1:]:
                if heading.level <= section_level:
                    end_page = heading.page
                    next_section_title = heading.title
                    break

    # Download PDF and search for the term
    pdf_data = _download_pdf(procedure.pdf_url)
    if not pdf_data:
        return None

    try:
        from pypdf import PdfReader
    except ImportError:
        return None

    try:
        reader = PdfReader(io.BytesIO(pdf_data))
        search_upper = search_term.upper()

        # Search from section start to section end (inclusive of end page)
        start_idx = section_page - 1  # 0-based
        # Include end_page in search range (content may appear before next heading)
        end_idx = end_page if end_page else len(reader.pages)

        for page_idx in range(start_idx, end_idx):
            if page_idx >= len(reader.pages):
                break

            page = reader.pages[page_idx]
            text = page.extract_text() or ""

            # On the last page, only search up to the next section heading
            if end_page and page_idx == end_page - 1 and next_section_title:
                # Find where the next section heading starts and truncate
                heading_pos = text.upper().find(next_section_title.upper())
                if heading_pos > 0:
                    text = text[:heading_pos]

            text_upper = text.upper()

            if search_upper in text_upper:
                return page_idx + 1  # Convert to 1-based

    except Exception:
        pass

    return None


# --- Utility Functions ---

def list_all_procedures(
    page: Page | None = None,
    use_cache: bool = True
) -> dict[str, list[ProcedureInfo]]:
    """
    Get all procedures grouped by category.

    Returns dict mapping category names to lists of procedures.
    """
    procedures = fetch_procedures_list(page, use_cache)

    by_category: dict[str, list[ProcedureInfo]] = {}
    for proc in procedures:
        if proc.category not in by_category:
            by_category[proc.category] = []
        by_category[proc.category].append(proc)

    return by_category


def clear_procedures_cache() -> int:
    """Clear all cached procedure data. Returns number of files deleted."""
    count = 0
    cache_base = CACHE_DIR / "procedures"
    if cache_base.exists():
        for cache_file in cache_base.rglob("*.json"):
            try:
                cache_file.unlink()
                count += 1
            except OSError:
                pass
    return count
