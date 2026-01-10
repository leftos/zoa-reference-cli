"""Fuzzy string matching utilities for procedure and chart lookups."""

import re
from dataclasses import dataclass


def normalize_runway_numbers(text: str) -> str:
    """
    Normalize runway numbers to have leading zeros.

    Examples:
        "4R" -> "04R"
        "RNAV 4R" -> "RNAV 04R"
        "RWY 4L" -> "RWY 04L"
        "28R" -> "28R" (already 2 digits)
    """

    def add_leading_zero(match):
        return match.group(1) + "0" + match.group(2)

    # Match single digit runway numbers with optional L/R/C suffix
    # (?:^|\s|RWY) - start of string, whitespace, or RWY prefix
    # (\d)([LRC]?) - single digit with optional L/R/C
    # (?=\s|$) - followed by whitespace or end of string
    return re.sub(r"(^|\s)(\d[LRC]?)(?=\s|$)", add_leading_zero, text)


def levenshtein(s1: str, s2: str) -> int:
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


def calculate_similarity(query: str, target: str) -> float:
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
    query = normalize_runway_numbers(query)
    target = normalize_runway_numbers(target)

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
                dist = levenshtein(qt, tt)
                max_len = max(len(qt), len(tt))
                # Allow up to 2 edits for longer tokens, scale bonus by similarity
                if dist <= 2:
                    # Higher bonus for closer matches
                    similarity = 1 - (dist / max_len)
                    edit_bonus = max(edit_bonus, 0.4 * similarity)

    return min(1.0, jaccard + substring_bonus + prefix_bonus + edit_bonus)


@dataclass
class FuzzyMatch:
    """A fuzzy match result with score."""

    name: str
    score: float
    data: object = None  # Optional associated data


def fuzzy_match(
    query: str,
    candidates: list[str],
    min_score: float = 0.2,
    ambiguity_threshold: float = 0.15,
) -> tuple[str | None, list[FuzzyMatch]]:
    """
    Find the best fuzzy match for a query among candidates.

    Args:
        query: The search query
        candidates: List of candidate strings to match against
        min_score: Minimum score threshold for matches
        ambiguity_threshold: Score difference threshold for ambiguous matches

    Returns:
        Tuple of (best_match, all_matches_above_threshold).
        If ambiguous, best_match will be None.
    """
    if not candidates:
        return None, []

    query_upper = query.upper()
    query_tokens = set(re.findall(r"[A-Z0-9]+", query_upper))

    matches: list[FuzzyMatch] = []
    for candidate in candidates:
        score = calculate_similarity(query_upper, candidate.upper())
        if score >= min_score:
            matches.append(FuzzyMatch(name=candidate, score=score))

    if not matches:
        return None, []

    # Sort by score descending
    matches.sort(key=lambda m: m.score, reverse=True)

    best_match = matches[0]

    # Check for exact match
    if best_match.score == 1.0:
        return best_match.name, matches

    # Check if only one match contains ALL query tokens
    if len(query_tokens) > 1:
        full_matches = []
        for m in matches:
            candidate_tokens = set(re.findall(r"[A-Z0-9]+", m.name.upper()))
            if query_tokens <= candidate_tokens:
                full_matches.append(m)

        if len(full_matches) == 1:
            return full_matches[0].name, matches

    # Check for ambiguous match
    if len(matches) > 1:
        score_diff = best_match.score - matches[1].score
        if score_diff < ambiguity_threshold:
            return None, matches

    return best_match.name, matches
