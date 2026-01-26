"""Click shell completion callbacks for CLI tab completion.

These functions are used with Click's shell_complete parameter to provide
tab completion in bash/zsh/powershell for CLI arguments.
"""

from click import Context, Parameter
from click.shell_completion import CompletionItem

from .atis import ATIS_AIRPORTS
from .cache import get_cached_chart_list
from .charts import ZOA_AIRPORTS
from .commands import CHART_TYPE_ALIASES, VALID_CHART_TYPES
from .navaids import get_all_identifiers
from .procedures import CLASS_D_AIRPORTS

# Common facility codes
FACILITY_CODES = ["ZOA", "NCT", "NorCal", "Oakland", "SFO", "OAK", "SJC", "SMF", "RNO"]


def complete_airport(
    ctx: Context, param: Parameter, incomplete: str
) -> list[CompletionItem]:
    """Complete airport codes from ZOA_AIRPORTS."""
    incomplete_upper = incomplete.upper()
    return [
        CompletionItem(airport)
        for airport in ZOA_AIRPORTS
        if airport.startswith(incomplete_upper)
    ]


def complete_atis_airport(
    ctx: Context, param: Parameter, incomplete: str
) -> list[CompletionItem]:
    """Complete ATIS airport codes (subset of ZOA airports)."""
    incomplete_upper = incomplete.upper()
    return [
        CompletionItem(airport)
        for airport in ATIS_AIRPORTS
        if airport.startswith(incomplete_upper)
    ]


def complete_chart_type(
    ctx: Context, param: Parameter, incomplete: str
) -> list[CompletionItem]:
    """Complete chart types for list command."""
    incomplete_upper = incomplete.upper()
    results = []

    # Primary types
    for ct in VALID_CHART_TYPES:
        if ct.startswith(incomplete_upper):
            results.append(CompletionItem(ct))

    # Aliases
    for alias in CHART_TYPE_ALIASES:
        if alias.startswith(incomplete_upper) and alias not in VALID_CHART_TYPES:
            results.append(CompletionItem(alias))

    return results


def complete_chart_query(
    ctx: Context, param: Parameter, incomplete: str
) -> list[CompletionItem]:
    """Complete chart queries (airport + chart name).

    For the first word, completes airports.
    For subsequent words, completes chart names if airport is known.
    """
    # Get already-entered args
    args = ctx.params.get("query", ()) or ()

    if not args:
        # First word: complete airports
        return complete_airport(ctx, param, incomplete)

    # Subsequent words: try to complete chart names
    airport = args[0].upper() if args else ""
    cached = get_cached_chart_list(airport)

    if cached:
        incomplete_upper = incomplete.upper()
        return [
            CompletionItem(chart)
            for chart in cached
            if chart.upper().startswith(incomplete_upper)
        ]

    # Fallback to airports if no cache
    return complete_airport(ctx, param, incomplete)


def complete_sop_query(
    ctx: Context, param: Parameter, incomplete: str
) -> list[CompletionItem]:
    """Complete SOP airports (Class D + major airports)."""
    incomplete_upper = incomplete.upper()
    results = []

    # Major airports
    for airport in ["SFO", "OAK", "SJC", "SMF", "RNO"]:
        if airport.startswith(incomplete_upper):
            results.append(CompletionItem(airport))

    # Class D airports
    for airport in CLASS_D_AIRPORTS:
        if airport.startswith(incomplete_upper):
            results.append(CompletionItem(airport))

    return results


def complete_navaid(
    ctx: Context, param: Parameter, incomplete: str
) -> list[CompletionItem]:
    """Complete navaid identifiers."""
    try:
        identifiers = get_all_identifiers()
        incomplete_upper = incomplete.upper()
        return [
            CompletionItem(ident)
            for ident in identifiers
            if ident.startswith(incomplete_upper)
        ][:50]  # Limit results for performance
    except Exception:
        return []


def complete_facility(
    ctx: Context, param: Parameter, incomplete: str
) -> list[CompletionItem]:
    """Complete facility codes for tdls/strips/position/scratchpad."""
    incomplete_upper = incomplete.upper()
    return [
        CompletionItem(facility)
        for facility in FACILITY_CODES
        if facility.upper().startswith(incomplete_upper)
    ]
