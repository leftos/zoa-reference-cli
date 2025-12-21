"""Procedure/SOP lookup functionality for ZOA Reference Tool."""

import io
import json
import re
import time
import urllib.request
import urllib.error
from dataclasses import dataclass, asdict
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout

from zoa_ref.config import CACHE_DIR, CACHE_TTL_SECONDS, REFERENCE_BASE_URL

PROCEDURES_URL = f"{REFERENCE_BASE_URL}/procedures"

# Cache configuration
PROCEDURES_CACHE_FILE = CACHE_DIR / "procedures" / "procedures_list.json"
# Note: Headings cache uses AIRAC-based invalidation via cache module

# Class D airports - these share the "Class D Airports SOP"
# When queried alone, they map to their section in the Class D SOP
CLASS_D_AIRPORTS = {
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
    "TRK",
}


# --- Data Structures ---


@dataclass
class ProcedureInfo:
    """Procedure document information."""

    name: str  # Display name (e.g., "Oakland ATCT SOP")
    pdf_url: str  # Relative URL (e.g., "zoapdfs/<uuid>.pdf")
    category: str  # Category (e.g., "atct", "enroute", "loa")

    @property
    def uuid(self) -> str:
        """Extract UUID from PDF URL."""
        match = re.search(r"zoapdfs/([^/]+)\.pdf", self.pdf_url)
        return match.group(1) if match else ""

    @property
    def full_url(self) -> str:
        """Get full URL to PDF."""
        if self.pdf_url.startswith("http"):
            return self.pdf_url
        return f"{REFERENCE_BASE_URL}/{self.pdf_url}"


@dataclass
class HeadingInfo:
    """A heading/section within a procedure PDF."""

    title: str  # Heading text (e.g., "2-2 IFR Departures")
    page: int  # 1-based page number
    level: int  # Nesting level (0 = top-level)


@dataclass
class ProcedureMatch:
    """A procedure match with similarity score."""

    procedure: ProcedureInfo
    score: float


@dataclass
class ProcedureQuery:
    """Parsed procedure query."""

    procedure_term: str  # e.g., "OAK", "NORCAL TRACON"
    section_term: str | None  # e.g., "2-2", "IFR Departures", None
    search_term: str | None  # e.g., "SJCE" - text to find within section

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
            "NCT",
            "ZOA",
            "ZLA",
            "ZLC",
            "ZSE",
            "NFL",
            "NLC",
            "ZAK",
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
                re.match(r"^\d+[-.]", part_upper)  # "2-2", "3.1"
                or (
                    i > 0
                    and part_upper not in proc_keywords
                    and part_upper not in airport_codes
                    and len(part) > 1
                )  # Multi-char non-keyword after first part
            )

            # If first part is an airport code or proc keyword, second part could be section
            if i == 1 and procedure_parts:
                first_upper = procedure_parts[0].upper()
                if (
                    first_upper in airport_codes or first_upper in proc_keywords
                ) and is_section_start:
                    break
                # If first part is NOT an airport code or proc keyword (e.g., "Class D"),
                # then this part is likely a section term (even if it's an airport code)
                if (
                    first_upper not in airport_codes
                    and first_upper not in proc_keywords
                ):
                    break

            # If we have airport + keyword, next part is section
            if len(procedure_parts) >= 2:
                first_upper = procedure_parts[0].upper()
                last_upper = procedure_parts[-1].upper()
                if first_upper in airport_codes and last_upper in proc_keywords:
                    break

            # Check if this starts a section (digit pattern)
            if re.match(r"^\d+[-.]", part_upper):
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

        # Transform Class D airport queries:
        # "SAC" -> procedure="Class D Airports", section="KSAC"
        # "SAC IFR" -> procedure="Class D Airports", section="KSAC", search="IFR"
        if procedure_term.upper() in CLASS_D_AIRPORTS:
            airport_code = procedure_term.upper()
            # Original section_term becomes search_term for finding within the airport section
            new_search_term = section_term
            # Section becomes K + airport code (e.g., KSAC)
            new_section_term = f"K{airport_code}"
            return cls(
                procedure_term="Class D Airports",
                section_term=new_section_term,
                search_term=new_search_term,
            )

        return cls(
            procedure_term=procedure_term,
            section_term=section_term,
            search_term=search_term,
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
        if time.time() - data.get("timestamp", 0) > CACHE_TTL_SECONDS:
            return None

        return [ProcedureInfo(**p) for p in data.get("procedures", [])]
    except (json.JSONDecodeError, OSError, TypeError):
        return None


def _save_procedures_cache(procedures: list[ProcedureInfo]) -> None:
    """Save procedures list to cache."""
    PROCEDURES_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)

    data = {"timestamp": time.time(), "procedures": [asdict(p) for p in procedures]}

    try:
        with open(PROCEDURES_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except OSError:
        pass


def _load_headings_cache(uuid: str) -> list[HeadingInfo] | None:
    """Load cached headings for a procedure.

    Headings are cached per AIRAC cycle and automatically invalidate
    when a new cycle begins.
    """
    from zoa_ref import cache

    airac, _, _ = cache.get_current_airac_cycle()
    cached = cache.get_cached_headings(uuid, airac)
    if cached:
        return [HeadingInfo(**h) for h in cached]
    return None


def _save_headings_cache(uuid: str, headings: list[HeadingInfo]) -> None:
    """Save headings to cache.

    Headings are cached per AIRAC cycle and automatically invalidate
    when a new cycle begins.
    """
    from zoa_ref import cache

    airac, _, _ = cache.get_current_airac_cycle()
    cache.cache_headings(uuid, [asdict(h) for h in headings], airac)


# --- Similarity Matching ---

# Airport code to city name aliases for better matching
# These expand airport codes to prefer ATCT SOPs over LOAs/other documents
AIRPORT_ALIASES = {
    "SFO": "SAN FRANCISCO ATCT",
    "OAK": "OAKLAND ATCT",
    "SJC": "SAN JOSE ATCT",
    "SMF": "SACRAMENTO ATCT",
    "RNO": "RENO ATCT",
    "FAT": "FRESNO ATCT TRACON SOP",
    "MRY": "MONTEREY ATCT",
    "NCT": "NORCAL TRACON",
    "ZOA": "OAKLAND CENTER",
}


def _expand_airport_aliases(query: str) -> str:
    """Expand airport codes in query to include city names.

    Only expands when the query is just the airport code alone.
    This allows 'SFO' to prefer ATCT SOP, but 'SFO Ramp' to find Ramp Tower.
    """
    query_upper = query.upper()
    tokens = query_upper.split()

    # Only expand if query is a single airport code
    if len(tokens) == 1 and tokens[0] in AIRPORT_ALIASES:
        code = tokens[0]
        return f"{code} {AIRPORT_ALIASES[code]}"

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
                    procedures.append(
                        ProcedureInfo(name=name, pdf_url=value, category=category)
                    )

    except Exception:
        pass

    return procedures


def fetch_procedures_list(
    page: Page | None = None, use_cache: bool = True, timeout: int = 30000
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

    # Tokenize query for all-terms matching
    query_tokens = set(re.findall(r"[A-Z0-9]+", search_term))

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

    # Check if only one match contains ALL query tokens
    # This handles cases like "ZOA NCT" where only one result has both terms
    if len(query_tokens) > 1:
        full_matches = []
        for m in matches:
            proc_tokens = set(re.findall(r"[A-Z0-9]+", m.procedure.name.upper()))
            if query_tokens <= proc_tokens:  # All query tokens present
                full_matches.append(m)

        if len(full_matches) == 1:
            # Only one match has all query tokens - auto-select it
            return full_matches[0].procedure, matches
        elif len(full_matches) > 1:
            # Multiple matches have all tokens - check ambiguity among them
            full_matches.sort(key=lambda m: m.score, reverse=True)
            if full_matches[0].score - full_matches[1].score >= ambiguity_threshold:
                return full_matches[0].procedure, matches
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

    return best_match.procedure, matches


# --- PDF Heading Extraction ---


def _download_pdf(url: str, timeout: int = 30) -> bytes | None:
    """Download PDF content from URL."""
    full_url = url if url.startswith("http") else f"{REFERENCE_BASE_URL}/{url}"

    try:
        req = urllib.request.Request(
            full_url, headers={"User-Agent": "ZOA-Reference-CLI/1.0"}
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
                                headings.append(
                                    HeadingInfo(title=title, page=page_num, level=level)
                                )
                    except Exception:
                        pass

        if reader.outline:
            process_outline(reader.outline)

    except Exception:
        pass

    return headings


def _calculate_proximity_score(text: str, query_words: list[str]) -> float:
    """
    Calculate a score based on how close query words appear to each other.

    Prioritizes:
    1. All words appearing in the same line (highest score)
    2. Words appearing close together with smaller spans
    3. Words appearing in query order (bonus)

    Returns 0 if not all words are present.
    """
    if not query_words:
        return 0.0

    text_upper = text.upper()

    # Check all words present
    if not all(word in text_upper for word in query_words):
        return 0.0

    # For single word, just presence is enough
    if len(query_words) == 1:
        return 1.0

    # First, check for lines containing ALL query words (best case)
    # Split by common line separators
    lines = text_upper.replace("\r", "\n").split("\n")
    best_line_score = 0.0

    for line in lines:
        if all(word in line for word in query_words):
            # All words in same line - calculate span within line
            positions = []
            for word in query_words:
                idx = line.find(word)
                if idx >= 0:
                    positions.append(idx)

            if len(positions) == len(query_words):
                span = max(positions) - min(positions) + len(query_words[-1])
                # Check if words are in query order
                in_order = positions == sorted(positions)
                # Line matches get high base score
                line_score = (
                    0.8 + (0.15 if in_order else 0) + (0.05 * max(0, 1 - span / 100))
                )
                best_line_score = max(best_line_score, min(1.0, line_score))

    if best_line_score > 0:
        return best_line_score

    # Fallback: find minimum span across the whole text
    word_positions: dict[str, list[int]] = {}
    for word in query_words:
        positions = []
        start = 0
        while True:
            idx = text_upper.find(word, start)
            if idx == -1:
                break
            positions.append(idx)
            start = idx + 1
        word_positions[word] = positions

    # Find the minimum span that contains all words
    best_span = float("inf")
    best_in_order = False

    first_word = query_words[0]
    for first_pos in word_positions[first_word]:
        positions_used = [first_pos]
        in_order = True
        prev_pos = first_pos

        for word in query_words[1:]:
            closest = None
            closest_dist = float("inf")
            for pos in word_positions[word]:
                dist = abs(pos - prev_pos)
                if dist < closest_dist:
                    closest_dist = dist
                    closest = pos
            if closest is not None:
                positions_used.append(closest)
                if closest < prev_pos:
                    in_order = False
                prev_pos = closest

        if len(positions_used) == len(query_words):
            span = max(positions_used) - min(positions_used)
            if span < best_span or (
                span == best_span and in_order and not best_in_order
            ):
                best_span = span
                best_in_order = in_order

    if best_span == float("inf"):
        return 0.0

    # Score for cross-line matches (lower than same-line matches)
    # Cap at 0.7 since same-line matches get 0.8+
    base_score = max(0.1, 0.7 - (best_span / 1000))
    order_bonus = 0.05 if best_in_order else 0.0

    return min(0.75, base_score + order_bonus)


def _search_pdf_text_for_heading(pdf_data: bytes, heading_query: str) -> int | None:
    """
    Search PDF text for a heading pattern when bookmarks unavailable.

    Looks for patterns like "2-2", "2.2", "Section 2-2", heading text, etc.
    For multi-word queries, scores pages by word proximity and returns best match.
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
        section_match = re.match(r"^(\d+)[-.](\d+)$", heading_query)
        if section_match:
            # Create flexible pattern for section numbers
            section_pattern = re.compile(
                rf"\b{section_match.group(1)}[-.\s]*{section_match.group(2)}\b",
                re.IGNORECASE,
            )

        # Split query into words for multi-word matching
        query_words = query_upper.split()

        # Track best match across all pages
        best_page = None
        best_score = 0.0

        for page_num, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            text_upper = text.upper()

            # Try section pattern first - exact match is best
            if section_pattern and section_pattern.search(text):
                return page_num

            # Try direct text match (exact phrase) - also best
            if query_upper in text_upper:
                return page_num

            # For multi-word queries, score by proximity
            if len(query_words) > 1:
                score = _calculate_proximity_score(text_upper, query_words)
                if score > best_score:
                    best_score = score
                    best_page = page_num

        # Return best match if found
        if best_page is not None and best_score > 0:
            return best_page

    except Exception:
        pass

    return None


def _find_matching_heading(
    headings: list[HeadingInfo], query: str
) -> HeadingInfo | None:
    """Find a heading that matches the query."""
    query_upper = query.upper()

    # Check for section number pattern like "2-2" or "2.2"
    section_match = re.match(r"^(\d+)[-.](\d+)$", query)
    if section_match:
        section_pattern = re.compile(
            rf"\b{section_match.group(1)}[-.\s]*{section_match.group(2)}\b",
            re.IGNORECASE,
        )
        for heading in headings:
            if section_pattern.search(heading.title):
                return heading

    # Try direct substring match
    for heading in headings:
        if query_upper in heading.title.upper():
            return heading

    # For multi-word queries, check if ALL words are in heading
    query_words = query_upper.split()
    if len(query_words) > 1:
        for heading in headings:
            title_upper = heading.title.upper()
            if all(word in title_upper for word in query_words):
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
    procedure: ProcedureInfo, use_cache: bool = True
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
    procedure: ProcedureInfo, section_query: str, use_cache: bool = True
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
    use_cache: bool = True,
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
                -1,
            )
            # Find next heading at same or higher level (lower number = higher level)
            # Start from after the section heading in the list order
            for heading in headings[section_idx + 1 :]:
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
    page: Page | None = None, use_cache: bool = True
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
