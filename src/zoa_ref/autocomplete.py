"""Autocomplete engine for interactive mode.

Provides context-aware tab completion using prompt_toolkit's Completer
interface, with background prefetching of chart data for fast completions.
"""

import threading
from typing import Iterator

from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.document import Document

from .atis import ATIS_AIRPORTS
from .cache import cache_chart_list, get_cached_chart_list
from .charts import ZOA_AIRPORTS, fetch_charts_from_api
from .commands import CHART_TYPE_ALIASES, VALID_CHART_TYPES
from .frequency import get_prefetch_airports
from .navaids import get_all_identifiers
from .procedures import CLASS_D_AIRPORTS

# Commands that take airports as first argument (excluding 'list' which has special handling)
AIRPORT_COMMANDS = {
    "chart",
    "charts",
    "approaches",
    "apps",
    "route",
}

# Commands available in interactive mode
INTERACTIVE_COMMANDS = [
    "chart",
    "charts",
    "list",
    "route",
    "atis",
    "sop",
    "proc",
    "airline",
    "airport",
    "aircraft",
    "navaid",
    "descent",
    "des",
    "approaches",
    "apps",
    "position",
    "pos",
    "scratchpad",
    "scratch",
    "vis",
    "tdls",
    "strips",
    "setbrowser",
    "help",
    "quit",
]

# Common facility codes for tdls/strips/position
FACILITY_CODES = [
    "NCT",
    "NorCal",
    "Oakland",
    "SFO",
    "OAK",
    "SJC",
    "SMF",
    "RNO",
]


class ChartListCache:
    """Thread-safe cache for chart names with background prefetching.

    Fetches chart lists from the API and caches them both in memory
    and on disk (via cache.py) for fast autocomplete lookups.
    """

    def __init__(self):
        self._cache: dict[str, list[str]] = {}
        self._lock = threading.Lock()
        self._prefetch_thread: threading.Thread | None = None

    def prefetch_airports(self, airports: set[str] | None = None) -> None:
        """Start background prefetch of chart lists for airports.

        Args:
            airports: Set of airport codes to prefetch.
                     If None, uses get_prefetch_airports().
        """
        # Avoid spawning multiple prefetch threads
        if self._prefetch_thread is not None and self._prefetch_thread.is_alive():
            return

        if airports is None:
            airports = get_prefetch_airports()

        self._prefetch_thread = threading.Thread(
            target=self._fetch_worker,
            args=(list(airports),),
            daemon=True,
        )
        self._prefetch_thread.start()

    def _fetch_worker(self, airports: list[str]) -> None:
        """Worker function that fetches chart lists in background."""
        for airport in airports:
            # Check disk cache first
            cached = get_cached_chart_list(airport)
            if cached is not None:
                with self._lock:
                    self._cache[airport.upper()] = cached
                continue

            # Fetch from API
            try:
                charts = fetch_charts_from_api(airport)
                chart_names = [c.chart_name for c in charts]

                # Store in memory and disk cache
                with self._lock:
                    self._cache[airport.upper()] = chart_names
                cache_chart_list(airport, chart_names)
            except Exception:
                pass  # Silently skip failed fetches

    def get_charts(self, airport: str) -> list[str]:
        """Get chart names for an airport (thread-safe).

        Args:
            airport: Airport code

        Returns:
            List of chart names, or empty list if not cached
        """
        airport = airport.upper()

        with self._lock:
            if airport in self._cache:
                return self._cache[airport]

        # Check disk cache
        cached = get_cached_chart_list(airport)
        if cached is not None:
            with self._lock:
                self._cache[airport] = cached
            return cached

        return []

    def has_airport(self, airport: str) -> bool:
        """Check if chart data is available for an airport."""
        airport = airport.upper()
        with self._lock:
            if airport in self._cache:
                return True
        return get_cached_chart_list(airport) is not None


class ZoaCompleter(Completer):
    """Context-aware completer for ZOA Reference CLI interactive mode.

    Provides completions for:
    - Recent command history (prioritized)
    - Commands (first word)
    - Airport codes (context-dependent)
    - Chart names (after airport)
    - Chart types (for list command)
    - Navaids (for navaid command)
    """

    def __init__(
        self,
        chart_cache: ChartListCache | None = None,
        history: "FileHistory | None" = None,
    ):
        """Initialize the completer.

        Args:
            chart_cache: ChartListCache instance for chart name completions.
                        If None, chart name completions will be unavailable.
            history: FileHistory instance for history-based completions.
                    If None, history completions will be unavailable.
        """
        self.chart_cache = chart_cache
        self.history = history
        self._navaids: list[str] | None = None

    def _get_navaids(self) -> list[str]:
        """Lazy-load navaid identifiers."""
        if self._navaids is None:
            try:
                self._navaids = get_all_identifiers()
            except Exception:
                self._navaids = []
        return self._navaids

    def _get_history_completions(self, text: str) -> Iterator[Completion]:
        """Get completions from command history.

        Yields history entries that start with the current input text,
        most recent first, limited to avoid clutter.
        """
        if self.history is None or not text:
            return

        text_lower = text.lower()
        seen: set[str] = set()
        count = 0
        max_history = 5  # Limit history suggestions

        # History is stored with most recent first after load
        for entry in self.history.get_strings():
            if count >= max_history:
                break

            entry_stripped = entry.strip()
            if not entry_stripped:
                continue

            # Match if entry starts with current text (case-insensitive)
            if entry_stripped.lower().startswith(text_lower):
                # Avoid duplicates
                if entry_stripped in seen:
                    continue
                seen.add(entry_stripped)
                count += 1

                yield Completion(
                    entry_stripped,
                    start_position=-len(text),
                    display_meta="history",
                )

    def get_completions(
        self, document: Document, complete_event
    ) -> Iterator[Completion]:
        """Generate completions based on current input context."""
        text = document.text_before_cursor
        words = text.split()

        # History completions first (if there's any text)
        if text.strip():
            yield from self._get_history_completions(text)

        # Handle empty or partial first word
        if len(words) == 0 or (len(words) == 1 and not text.endswith(" ")):
            prefix = words[0].lower() if words else ""
            yield from self._complete_first_word(prefix)
            return

        # First word is complete, determine context
        first_word = words[0].lower()
        first_word_upper = words[0].upper()

        # Determine what we're completing
        if text.endswith(" "):
            # Completing next word (nothing typed yet)
            current_prefix = ""
            word_index = len(words)
        else:
            # Completing partial word
            current_prefix = words[-1]
            word_index = len(words) - 1

        # Context-specific completions
        if first_word in AIRPORT_COMMANDS:
            yield from self._complete_airport_command(
                first_word, words, word_index, current_prefix
            )
        elif first_word_upper in ZOA_AIRPORTS:
            # Implicit chart lookup: OAK CNDEL5
            yield from self._complete_chart_names(first_word_upper, current_prefix)
        elif first_word == "list":
            yield from self._complete_list_command(words, word_index, current_prefix)
        elif first_word == "atis":
            yield from self._complete_atis(current_prefix)
        elif first_word in ("sop", "proc"):
            yield from self._complete_sop(current_prefix)
        elif first_word in ("route",):
            yield from self._complete_route(words, word_index, current_prefix)
        elif first_word == "navaid":
            yield from self._complete_navaids(current_prefix)
        elif first_word in ("tdls", "strips", "position", "pos"):
            yield from self._complete_facilities(current_prefix)
        elif first_word in ("scratchpad", "scratch"):
            yield from self._complete_facilities(current_prefix)

    def _complete_first_word(self, prefix: str) -> Iterator[Completion]:
        """Complete commands and airports for implicit chart lookup."""
        # Commands
        for cmd in INTERACTIVE_COMMANDS:
            if cmd.startswith(prefix):
                yield Completion(cmd, start_position=-len(prefix))

        # Airports (for implicit chart lookup like "OAK CNDEL5")
        for airport in ZOA_AIRPORTS:
            if airport.lower().startswith(prefix):
                yield Completion(airport, start_position=-len(prefix))

    def _complete_airport_command(
        self, command: str, words: list[str], word_index: int, prefix: str
    ) -> Iterator[Completion]:
        """Complete arguments for commands that take airports."""
        if word_index == 1:
            # First argument: airport
            yield from self._complete_airports(prefix)
        elif word_index == 2 and command in ("chart", "charts"):
            # Second argument for chart: chart name
            airport = words[1].upper()
            yield from self._complete_chart_names(airport, prefix)
        elif word_index >= 2 and command in ("chart", "charts"):
            # Additional words for chart query
            airport = words[1].upper()
            yield from self._complete_chart_names(airport, prefix)

    def _complete_list_command(
        self, words: list[str], word_index: int, prefix: str
    ) -> Iterator[Completion]:
        """Complete arguments for the list command."""
        if word_index == 1:
            # First argument: airport
            yield from self._complete_airports(prefix)
        elif word_index == 2:
            # Second argument: chart type
            yield from self._complete_chart_types(prefix)
        # Third argument is freeform search, no completion

    def _complete_route(
        self, words: list[str], word_index: int, prefix: str
    ) -> Iterator[Completion]:
        """Complete departure/arrival airports for route command."""
        if word_index in (1, 2):
            yield from self._complete_airports(prefix)

    def _complete_airports(self, prefix: str) -> Iterator[Completion]:
        """Complete airport codes."""
        prefix_upper = prefix.upper()
        for airport in ZOA_AIRPORTS:
            if airport.startswith(prefix_upper):
                yield Completion(airport, start_position=-len(prefix))

    def _complete_chart_names(self, airport: str, prefix: str) -> Iterator[Completion]:
        """Complete chart names for an airport."""
        if self.chart_cache is None:
            return

        charts = self.chart_cache.get_charts(airport)
        prefix_upper = prefix.upper()

        for chart_name in charts:
            if chart_name.upper().startswith(prefix_upper):
                yield Completion(chart_name, start_position=-len(prefix))

    def _complete_chart_types(self, prefix: str) -> Iterator[Completion]:
        """Complete chart types for list command."""
        prefix_upper = prefix.upper()

        # Primary types
        for ct in VALID_CHART_TYPES:
            if ct.startswith(prefix_upper):
                yield Completion(ct, start_position=-len(prefix))

        # Aliases
        for alias in CHART_TYPE_ALIASES:
            if alias.startswith(prefix_upper) and alias not in VALID_CHART_TYPES:
                yield Completion(alias, start_position=-len(prefix))

    def _complete_atis(self, prefix: str) -> Iterator[Completion]:
        """Complete ATIS airport codes."""
        prefix_upper = prefix.upper()
        for airport in ATIS_AIRPORTS:
            if airport.startswith(prefix_upper):
                yield Completion(airport, start_position=-len(prefix))

    def _complete_sop(self, prefix: str) -> Iterator[Completion]:
        """Complete SOP airports (Class D + major)."""
        prefix_upper = prefix.upper()

        # Major airports
        for airport in ["SFO", "OAK", "SJC", "SMF", "RNO"]:
            if airport.startswith(prefix_upper):
                yield Completion(airport, start_position=-len(prefix))

        # Class D airports
        for airport in CLASS_D_AIRPORTS:
            if airport.startswith(prefix_upper):
                yield Completion(airport, start_position=-len(prefix))

    def _complete_navaids(self, prefix: str) -> Iterator[Completion]:
        """Complete navaid identifiers."""
        navaids = self._get_navaids()
        prefix_upper = prefix.upper()

        for navaid in navaids:
            if navaid.startswith(prefix_upper):
                yield Completion(navaid, start_position=-len(prefix))

    def _complete_facilities(self, prefix: str) -> Iterator[Completion]:
        """Complete facility codes."""
        prefix_upper = prefix.upper()
        prefix_lower = prefix.lower()

        for facility in FACILITY_CODES:
            if facility.upper().startswith(prefix_upper) or facility.lower().startswith(
                prefix_lower
            ):
                yield Completion(facility, start_position=-len(prefix))
